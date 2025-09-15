from __future__ import annotations
import os
import json
import time
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

import ray
import sqlalchemy as sa
from sqlalchemy import text

from seedcore.graph.embeddings import GraphEmbedder, upsert_embeddings

PG_DSN = os.getenv("SEEDCORE_PG_DSN", os.getenv("PG_DSN", "postgresql://postgres:postgres@postgresql:5432/seedcore"))
AGENT_NAMESPACE = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))
logger = logging.getLogger(__name__)

# ---- tunables / env knobs ----
EMBED_TIMEOUT_S       = float(os.getenv("GRAPH_EMBED_TIMEOUT_S", "600"))
UPSERT_TIMEOUT_S      = float(os.getenv("GRAPH_UPSERT_TIMEOUT_S", "600"))
HEARTBEAT_PING_S      = float(os.getenv("GRAPH_HEARTBEAT_PING_S", "5"))
LEASE_EXTENSION_S     = int(os.getenv("GRAPH_LEASE_EXTENSION_S", "600"))   # extend lease this many seconds per ping
DB_POOL_SIZE          = int(os.getenv("GRAPH_DB_POOL_SIZE", "5"))
DB_MAX_OVERFLOW       = int(os.getenv("GRAPH_DB_MAX_OVERFLOW", "5"))
DB_POOL_RECYCLE_S     = int(os.getenv("GRAPH_DB_POOL_RECYCLE_S", "600"))
DB_ECHO               = os.getenv("GRAPH_DB_ECHO", "false").lower() in ("1","true","yes")
TASK_POLL_INTERVAL_S  = float(os.getenv("GRAPH_TASK_POLL_INTERVAL_S", "1.0"))
EMBED_BATCH_CHUNK     = int(os.getenv("GRAPH_EMBED_BATCH_CHUNK", "0"))  # 0 = disabled
LOG_DSN               = os.getenv("GRAPH_LOG_DSN", "masked").lower()    # "plain" to print full DSN (not recommended)
STRICT_JSON_RESULT    = os.getenv("GRAPH_STRICT_JSON_RESULT", "true").lower() in ("1","true","yes")

# supported task types (legacy + HGNN-aware)
GRAPH_TASK_TYPES = (
    "graph_embed",
    "graph_rag_query",
    # HGNN-aware v2 that accept UUID/text IDs and map via graph_node_map:
    "graph_embed_v2",
    "graph_rag_query_v2",
    # maintenance / mapping:
    "graph_sync_nodes",
)

def _redact_dsn(dsn: str) -> str:
    if LOG_DSN == "plain":
        return dsn
    try:
        if "@" in dsn and "://" in dsn and ":" in dsn.split("://", 1)[1]:
            head, tail = dsn.split("://", 1)
            userpass, hostpart = tail.split("@", 1)
            if ":" in userpass:
                user, _ = userpass.split(":", 1)
                return f"{head}://{user}:****@{hostpart}"
    except Exception:
        pass
    return "***"

@ray.remote
class GraphDispatcher:
    """
    Handles graph-related tasks:

      Legacy:
        - graph_embed:        params {"start_ids":[int,...], "k":2}
        - graph_rag_query:    params {"start_ids":[int,...], "k":2, "topk":10}

      HGNN-aware:
        - graph_embed_v2:     params may include any of:
                                {"start_node_ids":[int,...]}                       # as before
                                {"start_task_ids":[uuid,...]}                       # task UUIDs -> ensure_task_node()
                                {"start_agent_ids":[text,...]}                      # agent ids  -> ensure_agent_node()
                                {"start_organ_ids":[text,...]}                      # organ ids  -> ensure_organ_node()
                              plus {"k":2}
        - graph_rag_query_v2: same inputs as graph_embed_v2 + {"topk":10}

      Maintenance:
        - graph_sync_nodes:   calls backfill_task_nodes() to populate graph_node_map for tasks
    """

    def __init__(self, dsn: Optional[str] = None, name: str = "seedcore_graph_dispatcher", checkpoint_path: Optional[str] = None):
        logger.info("🚀 GraphDispatcher '%s' init...", name)
        start_time = time.time()

        self.dsn = dsn or PG_DSN
        self.name = name
        self._running = True
        self._metrics = {
            "tasks_claimed": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "last_task_id": None,
            "last_error": None,
            "last_complete_ms": None,
        }
        self._embedder_name = f"{name}_embedder"

        # --- DB engine ---
        logger.info("📊 GraphDispatcher '%s' DB engine: %s", self.name, _redact_dsn(self.dsn))
        self.engine = sa.create_engine(
            self.dsn,
            future=True,
            pool_size=DB_POOL_SIZE,
            max_overflow=DB_MAX_OVERFLOW,
            pool_pre_ping=True,
            pool_recycle=DB_POOL_RECYCLE_S,
            echo=DB_ECHO,
        )
        with self.engine.begin() as conn:
            conn.execute(text("SELECT 1"))

        # --- GraphEmbedder actor ---
        try:
            self.embedder = ray.get_actor(self._embedder_name, namespace=AGENT_NAMESPACE)
            logger.info("✅ Reusing GraphEmbedder: %s", self._embedder_name)
        except ValueError:
            self.embedder = GraphEmbedder.options(
                name=self._embedder_name,
                lifetime="detached",
                namespace=AGENT_NAMESPACE,
            ).remote(checkpoint_path)
            logger.info("✅ Created GraphEmbedder: %s", self._embedder_name)

        # quick ping (best-effort)
        try:
            ray.get(self.embedder.ping.remote(), timeout=10)
        except Exception:
            logger.debug("Embedder ping skipped/failed (non-fatal).")

        self._startup_complete = True
        self._startup_time = time.time() - start_time
        logger.info("🎉 GraphDispatcher '%s' ready in %.2fs", self.name, self._startup_time)

    # ---------------- Utils ----------------

    def _heartbeat_thread(self, task_id: str, stop_evt: threading.Event):
        """Extend lease + bump heartbeat while long work runs."""
        q = text("""
            UPDATE tasks
               SET last_heartbeat = NOW(),
                   lease_expires_at = NOW() + (:extend || ' seconds')::interval
             WHERE id = :id
               AND status = 'running'
               AND owner_id = :owner
        """)
        while not stop_evt.wait(HEARTBEAT_PING_S):
            try:
                with self.engine.begin() as conn:
                    conn.execute(q, {"id": task_id, "owner": self.name, "extend": LEASE_EXTENSION_S})
            except Exception as e:
                logger.debug("heartbeat update failed for %s: %s", task_id, e)

    def _start_heartbeat(self, task_id: str) -> threading.Event:
        ev = threading.Event()
        t = threading.Thread(target=self._heartbeat_thread, args=(task_id, ev), daemon=True)
        t.start()
        # stash on self to keep reference
        setattr(self, f"_hb_{task_id}", (ev, t))
        return ev

    def _stop_heartbeat(self, task_id: str):
        tup = getattr(self, f"_hb_{task_id}", None)
        if tup:
            ev, t = tup
            ev.set()
            try:
                t.join(timeout=2)
            except Exception:
                pass
            delattr(self, f"_hb_{task_id}")

    # ---- HGNN helpers: map external IDs -> numeric node_ids via graph_node_map ----

    def _ensure_task_nodes(self, task_uuids: List[str]) -> List[int]:
        if not task_uuids:
            return []
        q = text("SELECT ensure_task_node(:tid) AS node_id")
        node_ids: List[int] = []
        with self.engine.begin() as conn:
            for tid in task_uuids:
                row = conn.execute(q, {"tid": tid}).mappings().first()
                if row and row["node_id"] is not None:
                    node_ids.append(int(row["node_id"]))
        return node_ids

    def _ensure_agent_nodes(self, agent_ids: List[str]) -> List[int]:
        if not agent_ids:
            return []
        q = text("SELECT ensure_agent_node(:aid) AS node_id")
        node_ids: List[int] = []
        with self.engine.begin() as conn:
            for aid in agent_ids:
                row = conn.execute(q, {"aid": aid}).mappings().first()
                if row and row["node_id"] is not None:
                    node_ids.append(int(row["node_id"]))
        return node_ids

    def _ensure_organ_nodes(self, organ_ids: List[str]) -> List[int]:
        if not organ_ids:
            return []
        q = text("SELECT ensure_organ_node(:oid) AS node_id")
        node_ids: List[int] = []
        with self.engine.begin() as conn:
            for oid in organ_ids:
                row = conn.execute(q, {"oid": oid}).mappings().first()
                if row and row["node_id"] is not None:
                    node_ids.append(int(row["node_id"]))
        return node_ids

    def _resolve_start_node_ids(self, params: Dict[str, Any]) -> Tuple[List[int], Dict[str, Any]]:
        """
        Accepts multiple forms:
          - start_node_ids / start_ids: direct numeric node IDs
          - start_task_ids: list of UUIDs -> ensure_task_node()
          - start_agent_ids: list of text -> ensure_agent_node()
          - start_organ_ids: list of text -> ensure_organ_node()
        Returns (node_id list, debug dict)
        """
        debug: Dict[str, Any] = {"sources": {}}
        node_ids: List[int] = []

        # numeric node ids (legacy)
        for key in ("start_node_ids", "start_ids"):
            ids = params.get(key)
            if isinstance(ids, list) and ids and isinstance(ids[0], int):
                node_ids.extend([int(x) for x in ids])
                debug["sources"][key] = len(ids)

        # HGNN mappings
        t_ids = params.get("start_task_ids") or []
        a_ids = params.get("start_agent_ids") or []
        o_ids = params.get("start_organ_ids") or []

        if t_ids:
            tids = [str(x) for x in t_ids]
            tids_nodes = self._ensure_task_nodes(tids)
            node_ids.extend(tids_nodes)
            debug["sources"]["start_task_ids"] = len(tids)

        if a_ids:
            aids = [str(x) for x in a_ids]
            aids_nodes = self._ensure_agent_nodes(aids)
            node_ids.extend(aids_nodes)
            debug["sources"]["start_agent_ids"] = len(aids)

        if o_ids:
            oids = [str(x) for x in o_ids]
            oids_nodes = self._ensure_organ_nodes(oids)
            node_ids.extend(oids_nodes)
            debug["sources"]["start_organ_ids"] = len(oids)

        # de-dup + keep order
        seen = set()
        node_ids = [x for x in node_ids if (x not in seen and not seen.add(x))]
        debug["node_count"] = len(node_ids)
        return node_ids, debug

    def _fetch_node_meta(self, node_ids: List[int]) -> List[Dict[str, Any]]:
        """Return raw rows from graph_node_map as JSON-ish dicts (best effort)."""
        if not node_ids:
            return []
        q = text("SELECT to_jsonb(t) AS j FROM graph_node_map t WHERE t.node_id = ANY(:ids)")
        with self.engine.begin() as conn:
            rows = conn.execute(q, {"ids": node_ids}).mappings().all()
        return [r["j"] for r in rows if r and r.get("j") is not None]

    # ---------------- Health / control ----------------

    def get_startup_status(self) -> Dict[str, Any]:
        return {
            "startup_complete": getattr(self, '_startup_complete', False),
            "startup_time": getattr(self, '_startup_time', None),
            "name": self.name,
            "embedder_name": self._embedder_name,
            "timestamp": time.time(),
            "engine_available": hasattr(self, 'engine') and self.engine is not None,
            "embedder_available": hasattr(self, 'embedder') and self.embedder is not None,
        }

    def ping(self) -> str:
        return "pong"

    def get_metrics(self) -> Dict[str, Any]:
        return dict(self._metrics, timestamp=time.time())

    def set_log_level(self, level: str = "INFO") -> bool:
        try:
            logger.setLevel(getattr(logging, level.upper(), logging.INFO))
            return True
        except Exception:
            return False

    def heartbeat(self) -> Dict[str, Any]:
        return {
            "status": "healthy" if self._startup_complete else "initializing",
            "timestamp": time.time(),
            "name": self.name,
        }

    # ---------------- Run loop ----------------

    def run(self, poll_interval: float = TASK_POLL_INTERVAL_S):
        logger.info("🚀 GraphDispatcher '%s' run loop (poll=%.1fs)", self.name, poll_interval)
        self._run_thread = threading.Thread(target=self._run_loop, args=(poll_interval,), daemon=True)
        self._run_thread.start()

    def _run_loop(self, poll_interval: float = TASK_POLL_INTERVAL_S):
        loop_count = 0
        while self._running:
            try:
                loop_count += 1
                task = self._claim_next_task()
                if not task:
                    time.sleep(poll_interval)
                    continue
                self._process(task)
            except Exception as e:
                logger.exception("run loop error: %s", e)
                time.sleep(2.0)

    def stop(self) -> bool:
        self._running = False
        return True

    # ---------------- DB task ops ----------------

    def _claim_next_task(self) -> Optional[Dict[str, Any]]:
        # include lease ownership + expiry; include retry; filter by run_after
        q = """
        UPDATE tasks
           SET status='running',
               locked_by=:name,
               locked_at=NOW(),
               owner_id=:name,
               last_heartbeat = NOW(),
               lease_expires_at = NOW() + (:lease || ' seconds')::interval
         WHERE id = (
           SELECT id FROM tasks
            WHERE status IN ('queued','retry')
              AND type = ANY(:types)
              AND (run_after IS NULL OR run_after <= NOW())
            ORDER BY created_at ASC
            LIMIT 1
         )
        RETURNING id, type, params::text;
        """
        try:
            with self.engine.begin() as conn:
                row = conn.execute(
                    text(q),
                    {"name": self.name, "lease": LEASE_EXTENSION_S, "types": list(GRAPH_TASK_TYPES)},
                ).mappings().first()
            return dict(row) if row else None
        except Exception as e:
            logger.error("claim_next_task failed: %s", e)
            return None

    def _complete(self, task_id, result=None, error=None, retry_after=None):
        try:
            if error:
                new_status = "retry" if retry_after else "failed"
                q = """
                UPDATE tasks
                   SET status=:st,
                       error=:err,
                       attempts=attempts+1,
                       run_after=CASE WHEN :retry > 0 THEN NOW() + (:retry || ' seconds')::interval ELSE run_after END
                 WHERE id=:id
                """
                params = {"st": new_status, "err": str(error), "retry": retry_after or 0, "id": task_id}
            else:
                structured_result = result if result is not None else {"status": "completed"}
                if STRICT_JSON_RESULT:
                    try:
                        json.dumps(structured_result)
                    except Exception:
                        structured_result = {"status": "completed", "note": "Non-JSON result sanitized"}
                q = "UPDATE tasks SET status='completed', result=:res, error=NULL WHERE id=:id"
                params = {"res": json.dumps(structured_result), "id": task_id}

            with self.engine.begin() as conn:
                conn.execute(text(q), params)

            if error:
                self._metrics["tasks_failed"] += 1
            else:
                self._metrics["tasks_completed"] += 1
        except Exception as e:
            logger.error("complete() failed for %s: %s", task_id, e)

    # ---------------- Task processing ----------------

    def _process(self, task: Dict[str, Any]):
        tid = task["id"]
        ttype = task["type"]
        self._metrics["tasks_claimed"] += 1
        self._metrics["last_task_id"] = tid
        t0 = time.time()

        # start a heartbeat ticker for long work
        hb_ev = self._start_heartbeat(tid)

        try:
            params = json.loads(task["params"])
        except Exception as e:
            self._stop_heartbeat(tid)
            self._complete(tid, error=f"Invalid task params: {e}")
            return

        try:
            if ttype in ("graph_embed", "graph_embed_v2"):
                # resolve node ids (legacy: start_ids; v2: map UUID/text ids)
                node_ids, debug = self._resolve_start_node_ids(params)
                k = int(params.get("k", 2))
                if not node_ids:
                    raise ValueError("No start nodes resolved")

                # chunking support
                if EMBED_BATCH_CHUNK and len(node_ids) > EMBED_BATCH_CHUNK:
                    all_maps: Dict[int, List[float]] = {}
                    for i in range(0, len(node_ids), EMBED_BATCH_CHUNK):
                        chunk = node_ids[i:i+EMBED_BATCH_CHUNK]
                        emb_map = ray.get(self.embedder.compute_embeddings.remote(chunk, k), timeout=EMBED_TIMEOUT_S)
                        all_maps.update(emb_map or {})
                    emb_map = all_maps
                else:
                    emb_map = ray.get(self.embedder.compute_embeddings.remote(node_ids, k), timeout=EMBED_TIMEOUT_S)

                n = ray.get(upsert_embeddings.remote(emb_map), timeout=UPSERT_TIMEOUT_S)

                # richer result with node meta (optional)
                meta_nodes = self._fetch_node_meta(list(emb_map.keys()))
                result = {
                    "embedded": n,
                    "k": k,
                    "start_node_count": len(node_ids),
                    "embedding_count": len(emb_map or {}),
                    "start_debug": debug,
                    "node_meta": meta_nodes[:64],  # cap result size
                }
                self._stop_heartbeat(tid)
                self._complete(tid, result=result)
                return

            if ttype in ("graph_rag_query", "graph_rag_query_v2"):
                import numpy as np

                node_ids, debug = self._resolve_start_node_ids(params)
                k = int(params.get("k", 2))
                topk = int(params.get("topk", 10))
                if not node_ids:
                    raise ValueError("No start nodes resolved")

                # ensure embeddings exist for seeds
                emb_map = ray.get(self.embedder.compute_embeddings.remote(node_ids, k), timeout=EMBED_TIMEOUT_S)
                ray.get(upsert_embeddings.remote(emb_map), timeout=UPSERT_TIMEOUT_S)

                vecs = list(emb_map.values())
                centroid = np.asarray(vecs, dtype="float32").mean(0).tolist() if vecs else None

                hits: List[Dict[str, Any]] = []
                if centroid:
                    centroid_json = json.dumps(centroid)
                    centroid_vec_literal = "[" + ",".join(f"{x:.6f}" for x in centroid) + "]"
                    try:
                        with self.engine.begin() as conn:
                            rows = conn.execute(
                                text("""
                                  SELECT node_id, emb <-> (:c::jsonb::vector) AS dist
                                    FROM graph_embeddings
                                ORDER BY emb <-> (:c::jsonb::vector)
                                   LIMIT :k
                                """),
                                {"c": centroid_json, "k": topk},
                            ).mappings().all()
                            hits = [{"node_id": r["node_id"], "score": float(r["dist"])} for r in rows]
                    except Exception:
                        with self.engine.begin() as conn:
                            rows = conn.execute(
                                text("""
                                  SELECT node_id, emb <-> (:c)::vector AS dist
                                    FROM graph_embeddings
                                ORDER BY emb <-> (:c)::vector
                                   LIMIT :k
                                """),
                                {"c": centroid_vec_literal, "k": topk},
                            ).mappings().all()
                            hits = [{"node_id": r["node_id"], "score": float(r["dist"])} for r in rows]

                meta_nodes = self._fetch_node_meta([h["node_id"] for h in hits])
                result = {
                    "neighbors": hits,
                    "neighbor_count": len(hits),
                    "seed_count": len(emb_map or {}),
                    "k": k,
                    "topk": topk,
                    "centroid_computed": centroid is not None,
                    "start_debug": debug,
                    "node_meta": meta_nodes[:64],
                }
                self._stop_heartbeat(tid)
                self._complete(tid, result=result)
                return

            if ttype == "graph_sync_nodes":
                # ensure every existing task has a node in graph_node_map
                with self.engine.begin() as conn:
                    # optional: versioned function name; fall back if not present
                    try:
                        r = conn.execute(text("SELECT backfill_task_nodes() AS updated")).mappings().first()
                        updated = int(r["updated"]) if r and r.get("updated") is not None else None
                    except Exception:
                        # tolerate absence
                        updated = None
                self._stop_heartbeat(tid)
                self._complete(tid, result={"backfill_task_nodes": updated})
                return

            # Unknown type
            self._stop_heartbeat(tid)
            self._complete(
                tid,
                result={
                    "error": f"Unsupported task type: {ttype}",
                    "supported_types": list(GRAPH_TASK_TYPES),
                },
            )

        except Exception as e:
            logger.exception("Task %s failed: %s", tid, e)
            self._stop_heartbeat(tid)
            self._complete(tid, error=str(e), retry_after=30)
        finally:
            self._metrics["last_complete_ms"] = round((time.time() - t0) * 1000.0, 2)

    # ---------------- Cleanup ----------------

    def cleanup(self):
        try:
            if hasattr(self, 'embedder'):
                ray.get(self.embedder.close.remote(), timeout=30)
        except Exception as e:
            logger.warning("failed to cleanup embedder: %s", e)
        try:
            if hasattr(self, 'engine'):
                self.engine.dispose()
        except Exception as e:
            logger.warning("failed to dispose engine: %s", e)
