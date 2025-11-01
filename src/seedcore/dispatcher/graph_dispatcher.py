from __future__ import annotations

# Import graph modules FIRST before logging setup (prevents logger hijacking)
from seedcore.graph import GraphEmbedder, NimRetrievalEmbedder, upsert_embeddings

import os
import json
import time
import logging
import threading
import hashlib
from typing import Any, Dict, List, Optional, Tuple

import ray
import sqlalchemy as sa
from sqlalchemy import text

from ray.util import log_once
import logging, sys
from seedcore.logging_setup import ensure_serve_logger

def get_seedcore_logger(name: str, level="DEBUG"):
    logger = ensure_serve_logger(name, level=level)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            "%H:%M:%S"))
        logger.addHandler(handler)
    logger.propagate = True
    if log_once(f"logger-init-{name}"):
        logger.info(f"[Logger Initialized] {name}")
    return logger

# Usage
logger = get_seedcore_logger("seedcore.dispatchers")

PG_DSN = os.getenv("SEEDCORE_PG_DSN", os.getenv("PG_DSN", "postgresql://postgres:postgres@postgresql:5432/seedcore"))
AGENT_NAMESPACE = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))
NIM_MODEL = os.getenv("NIM_RETRIEVAL_MODEL", "nvidia/nv-embedqa-e5-v5")


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
    # facts system support (Migration 009):
    "graph_fact_embed",
    "graph_fact_query",
    # NIM retrieval embedding (Migration 017):
    "nim_task_embed",
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
                                {"start_fact_ids":[uuid,...]}                       # fact UUIDs -> ensure_fact_node() (Migration 009)
                                {"start_artifact_ids":[uuid,...]}                   # artifact UUIDs -> ensure_artifact_node() (Migration 007)
                                {"start_capability_ids":[uuid,...]}                 # capability UUIDs -> ensure_capability_node() (Migration 007)
                                {"start_memory_cell_ids":[uuid,...]}                # memory_cell UUIDs -> ensure_memory_cell_node() (Migration 007)
                                {"start_model_ids":[text,...]}                      # model names -> ensure_model_node() (Migration 008)
                                {"start_policy_ids":[text,...]}                     # policy names -> ensure_policy_node() (Migration 008)
                                {"start_service_ids":[text,...]}                    # service names -> ensure_service_node() (Migration 008)
                                {"start_skill_ids":[text,...]}                      # skill names -> ensure_skill_node() (Migration 008)
                              plus {"k":2}
        - graph_rag_query_v2: same inputs as graph_embed_v2 + {"topk":10}

      NIM Retrieval (Migration 017):
        - nim_task_embed:     params {"start_task_ids":[uuid,...]}                  # task UUIDs -> fetch from Postgres, embed with NIM

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

        # --- GraphEmbedder actor (SAGE/Neo4j) ---
        try:
            self.embedder = ray.get_actor(self._embedder_name, namespace=AGENT_NAMESPACE)
            logger.info("✅ Reusing GraphEmbedder: %s", self._embedder_name)
        except ValueError:
            self.embedder = GraphEmbedder.options(
                name=self._embedder_name,
                lifetime="detached",
                namespace=AGENT_NAMESPACE,
            ).remote()
            logger.info("✅ Created GraphEmbedder: %s", self._embedder_name)

        # quick ping (best-effort)
        try:
            ray.get(self.embedder.ping.remote(), timeout=10)
        except Exception:
            logger.debug("GraphEmbedder ping skipped/failed (non-fatal).")

        # --- NimRetrievalEmbedder actor (NIM/Postgres) ---
        self._nim_embedder_name = f"{name}_nim_embedder"
        try:
            self.nim_embedder = ray.get_actor(self._nim_embedder_name, namespace=AGENT_NAMESPACE)
            logger.info("✅ Reusing NimRetrievalEmbedder: %s", self._nim_embedder_name)
        except ValueError:
            self.nim_embedder = NimRetrievalEmbedder.options(
                name=self._nim_embedder_name,
                lifetime="detached",
                namespace=AGENT_NAMESPACE,
            ).remote()
            logger.info("✅ Created NimRetrievalEmbedder: %s", self._nim_embedder_name)

        # quick ping (best-effort)
        try:
            ray.get(self.nim_embedder.ping.remote(), timeout=10)
        except Exception:
            logger.debug("NimRetrievalEmbedder ping skipped/failed (non-fatal).")

        self._startup_complete = True
        self._startup_time = time.time() - start_time
        logger.info("🎉 GraphDispatcher '%s' ready in %.2fs", self.name, self._startup_time)
        
        # Auto-start run loop if not already running
        # This ensures the run loop starts even if bootstrap script doesn't call run()
        self._run_thread = None
        try:
            self.run()
            logger.info("✅ GraphDispatcher '%s' run loop auto-started in __init__", self.name)
        except Exception as e:
            logger.error("❌ GraphDispatcher '%s' failed to auto-start run loop: %s", self.name, e, exc_info=True)

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

    def _ensure_fact_nodes(self, fact_uuids: List[str]) -> List[int]:
        """Ensure fact nodes exist in graph_node_map (Migration 009)."""
        if not fact_uuids:
            return []
        q = text("SELECT ensure_fact_node(:fid) AS node_id")
        node_ids: List[int] = []
        with self.engine.begin() as conn:
            for fid in fact_uuids:
                row = conn.execute(q, {"fid": fid}).mappings().first()
                if row and row["node_id"] is not None:
                    node_ids.append(int(row["node_id"]))
        return node_ids

    def _ensure_artifact_nodes(self, artifact_uuids: List[str]) -> List[int]:
        """Ensure artifact nodes exist in graph_node_map (Migration 007)."""
        if not artifact_uuids:
            return []
        q = text("SELECT ensure_artifact_node(:aid) AS node_id")
        node_ids: List[int] = []
        with self.engine.begin() as conn:
            for aid in artifact_uuids:
                row = conn.execute(q, {"aid": aid}).mappings().first()
                if row and row["node_id"] is not None:
                    node_ids.append(int(row["node_id"]))
        return node_ids

    def _ensure_capability_nodes(self, capability_uuids: List[str]) -> List[int]:
        """Ensure capability nodes exist in graph_node_map (Migration 007)."""
        if not capability_uuids:
            return []
        q = text("SELECT ensure_capability_node(:cid) AS node_id")
        node_ids: List[int] = []
        with self.engine.begin() as conn:
            for cid in capability_uuids:
                row = conn.execute(q, {"cid": cid}).mappings().first()
                if row and row["node_id"] is not None:
                    node_ids.append(int(row["node_id"]))
        return node_ids

    def _ensure_memory_cell_nodes(self, memory_cell_uuids: List[str]) -> List[int]:
        """Ensure memory_cell nodes exist in graph_node_map (Migration 007)."""
        if not memory_cell_uuids:
            return []
        q = text("SELECT ensure_memory_cell_node(:mid) AS node_id")
        node_ids: List[int] = []
        with self.engine.begin() as conn:
            for mid in memory_cell_uuids:
                row = conn.execute(q, {"mid": mid}).mappings().first()
                if row and row["node_id"] is not None:
                    node_ids.append(int(row["node_id"]))
        return node_ids

    def _ensure_model_nodes(self, model_names: List[str]) -> List[int]:
        """Ensure model nodes exist in graph_node_map (Migration 008)."""
        if not model_names:
            return []
        q = text("SELECT ensure_model_node(:mname) AS node_id")
        node_ids: List[int] = []
        with self.engine.begin() as conn:
            for mname in model_names:
                row = conn.execute(q, {"mname": mname}).mappings().first()
                if row and row["node_id"] is not None:
                    node_ids.append(int(row["node_id"]))
        return node_ids

    def _ensure_policy_nodes(self, policy_names: List[str]) -> List[int]:
        """Ensure policy nodes exist in graph_node_map (Migration 008)."""
        if not policy_names:
            return []
        q = text("SELECT ensure_policy_node(:pname) AS node_id")
        node_ids: List[int] = []
        with self.engine.begin() as conn:
            for pname in policy_names:
                row = conn.execute(q, {"pname": pname}).mappings().first()
                if row and row["node_id"] is not None:
                    node_ids.append(int(row["node_id"]))
        return node_ids

    def _ensure_service_nodes(self, service_names: List[str]) -> List[int]:
        """Ensure service nodes exist in graph_node_map (Migration 008)."""
        if not service_names:
            return []
        q = text("SELECT ensure_service_node(:sname) AS node_id")
        node_ids: List[int] = []
        with self.engine.begin() as conn:
            for sname in service_names:
                row = conn.execute(q, {"sname": sname}).mappings().first()
                if row and row["node_id"] is not None:
                    node_ids.append(int(row["node_id"]))
        return node_ids

    def _ensure_skill_nodes(self, skill_names: List[str]) -> List[int]:
        """Ensure skill nodes exist in graph_node_map (Migration 008)."""
        if not skill_names:
            return []
        q = text("SELECT ensure_skill_node(:sname) AS node_id")
        node_ids: List[int] = []
        with self.engine.begin() as conn:
            for sname in skill_names:
                row = conn.execute(q, {"sname": sname}).mappings().first()
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
          - start_fact_ids: list of UUIDs -> ensure_fact_node() (Migration 009)
          - start_artifact_ids: list of UUIDs -> ensure_artifact_node() (Migration 007)
          - start_capability_ids: list of UUIDs -> ensure_capability_node() (Migration 007)
          - start_memory_cell_ids: list of UUIDs -> ensure_memory_cell_node() (Migration 007)
          - start_model_ids: list of text -> ensure_model_node() (Migration 008)
          - start_policy_ids: list of text -> ensure_policy_node() (Migration 008)
          - start_service_ids: list of text -> ensure_service_node() (Migration 008)
          - start_skill_ids: list of text -> ensure_skill_node() (Migration 008)
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

        # HGNN mappings - Core entities (Migration 007)
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

        # Facts system (Migration 009)
        f_ids = params.get("start_fact_ids") or []
        if f_ids:
            fids = [str(x) for x in f_ids]
            fids_nodes = self._ensure_fact_nodes(fids)
            node_ids.extend(fids_nodes)
            debug["sources"]["start_fact_ids"] = len(fids)

        # Resource entities (Migration 007)
        art_ids = params.get("start_artifact_ids") or []
        cap_ids = params.get("start_capability_ids") or []
        mem_ids = params.get("start_memory_cell_ids") or []

        if art_ids:
            artids = [str(x) for x in art_ids]
            artids_nodes = self._ensure_artifact_nodes(artids)
            node_ids.extend(artids_nodes)
            debug["sources"]["start_artifact_ids"] = len(artids)

        if cap_ids:
            capids = [str(x) for x in cap_ids]
            capids_nodes = self._ensure_capability_nodes(capids)
            node_ids.extend(capids_nodes)
            debug["sources"]["start_capability_ids"] = len(capids)

        if mem_ids:
            memids = [str(x) for x in mem_ids]
            memids_nodes = self._ensure_memory_cell_nodes(memids)
            node_ids.extend(memids_nodes)
            debug["sources"]["start_memory_cell_ids"] = len(memids)

        # Agent layer extensions (Migration 008)
        mod_ids = params.get("start_model_ids") or []
        pol_ids = params.get("start_policy_ids") or []
        srv_ids = params.get("start_service_ids") or []
        skl_ids = params.get("start_skill_ids") or []

        if mod_ids:
            modids = [str(x) for x in mod_ids]
            modids_nodes = self._ensure_model_nodes(modids)
            node_ids.extend(modids_nodes)
            debug["sources"]["start_model_ids"] = len(modids)

        if pol_ids:
            polids = [str(x) for x in pol_ids]
            polids_nodes = self._ensure_policy_nodes(polids)
            node_ids.extend(polids_nodes)
            debug["sources"]["start_policy_ids"] = len(polids)

        if srv_ids:
            srvid = [str(x) for x in srv_ids]
            srvid_nodes = self._ensure_service_nodes(srvid)
            node_ids.extend(srvid_nodes)
            debug["sources"]["start_service_ids"] = len(srvid)

        if skl_ids:
            sklids = [str(x) for x in skl_ids]
            sklids_nodes = self._ensure_skill_nodes(sklids)
            node_ids.extend(sklids_nodes)
            debug["sources"]["start_skill_ids"] = len(sklids)

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

    def _fetch_task_contents(self, task_uuids: List[str]) -> Dict[str, str]:
        """
        Fetch the text content for a list of task UUIDs from Postgres.
        Uses the same content logic from your task_embeddings_stale view.
        """
        if not task_uuids:
            return {}
        
        # This query builds the text content exactly as your migration does
        q = text("""
        SELECT
            t.id::text,
            left(
                concat_ws(
                    '\n',
                    NULLIF(btrim(t.description), ''),
                    NULLIF(btrim(t.type), ''),
                    NULLIF(btrim(jsonb_pretty(t.params)), '')
                ),
                16000 -- Max chars, from your migration
            ) AS content
        FROM tasks t
        WHERE t.id::text = ANY(:task_uuids)
        """)
        
        contents = {}
        with self.engine.begin() as conn:
            rows = conn.execute(q, {"task_uuids": task_uuids}).mappings().all()
            for row in rows:
                contents[row["id"]] = row["content"]
        
        logger.debug("Fetched content for %d/%d tasks", len(contents), len(task_uuids))
        return contents

    def _compute_content_sha256(self, content: str) -> str:
        """Computes sha256 hash of content, matching the migration logic."""
        try:
            # Truncate to 16000 chars (from migration)
            truncated_content = content[:16000]
            # Digest requires bytes
            content_bytes = truncated_content.encode('utf-8')
            return hashlib.sha256(content_bytes).hexdigest()
        except Exception as e:
            logger.warning("Failed to compute sha256: %s", e)
            return None

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
        # Prevent starting multiple run loops
        if self._run_thread is not None and self._run_thread.is_alive():
            logger.warning("⚠️ GraphDispatcher '%s' run loop already running, skipping start", self.name)
            return
        
        logger.info("🚀 GraphDispatcher '%s' starting run loop (poll=%.1fs)", self.name, poll_interval)
        try:
            self._run_thread = threading.Thread(target=self._run_loop, args=(poll_interval,), daemon=True)
            self._run_thread.start()
            logger.info("✅ GraphDispatcher '%s' run loop thread started (thread_id=%s)", self.name, self._run_thread.ident)
        except Exception as e:
            logger.error("❌ GraphDispatcher '%s' failed to start run loop thread: %s", self.name, e, exc_info=True)
            raise

    def _run_loop(self, poll_interval: float = TASK_POLL_INTERVAL_S):
        loop_count = 0
        
        # Log thread info for debugging
        import threading
        thread_id = threading.current_thread().ident
        thread_name = threading.current_thread().name
        logger.info("🔄 GraphDispatcher '%s' run loop STARTED (poll=%.1fs, thread_id=%s, thread_name=%s)", 
                   self.name, poll_interval, thread_id, thread_name)
        
        while self._running:
            try:
                loop_count += 1
                task = self._claim_next_task()
                if not task:
                    time.sleep(poll_interval)
                    continue
                
                # Log when we claim a task
                task_id = str(task.get("id", "unknown")) if task else "unknown"
                task_type = task.get("type", "unknown") if task else "unknown"
                logger.info("🎯 GraphDispatcher '%s' claimed task %s (type=%s)", self.name, task_id, task_type)
                self._process(task)
            except Exception as e:
                logger.exception("❌ GraphDispatcher '%s' run loop error: %s", self.name, e)
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
            if row:
                result = dict(row)
                # Ensure UUID is stringified for consistent logging
                if "id" in result:
                    result["id"] = str(result["id"])
                task_id = result.get("id", "unknown")
                task_type = result.get("type", "unknown")
                logger.debug("✅ GraphDispatcher '%s' claimed task %s (type=%s) from database", self.name, task_id, task_type)
                return result
            else:
                # No tasks available - this is normal, so we don't log it to avoid spam
                return None
        except Exception as e:
            logger.error("❌ GraphDispatcher '%s' claim_next_task failed: %s", self.name, e, exc_info=True)
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
        # Ensure UUID is converted to string for consistent logging
        tid_str = str(tid) if tid else "unknown"
        ttype = task["type"]
        self._metrics["tasks_claimed"] += 1
        self._metrics["last_task_id"] = tid
        t0 = time.time()

        logger.info("🔄 Processing task id=%s type=%s", tid_str, ttype)

        # start a heartbeat ticker for long work
        hb_ev = self._start_heartbeat(tid_str)

        try:
            params = json.loads(task["params"])
            logger.debug("📋 Task %s params parsed: %s", tid_str, json.dumps(params, default=str)[:200])
        except Exception as e:
            logger.error("❌ Task %s failed to parse params: %s", tid_str, e)
            self._stop_heartbeat(tid_str)
            self._complete(tid, error=f"Invalid task params: {e}")
            return

        try:
            # --- NIM TASK EMBEDDER LOGIC ---
            if ttype == "nim_task_embed":
                logger.info("🚀 Task %s: nim_task_embed operation", tid_str)
                
                # 1. Get task UUIDs from params
                task_uuids = [str(uid) for uid in params.get("start_task_ids", [])]
                if not task_uuids:
                    raise ValueError("No 'start_task_ids' provided for nim_task_embed")

                # 2. Get text content for these tasks (from Postgres)
                content_map = self._fetch_task_contents(task_uuids)  # {uuid: text}
                
                # 3. Build the map for the NIM embedder: {node_id: text}
                text_map = {}
                node_id_to_uuid = {}
                for uuid, text in content_map.items():
                    # This ensures the node exists in graph_node_map and gets its int ID
                    node_id_list = self._ensure_task_nodes([uuid])
                    if node_id_list:
                        node_id = node_id_list[0]
                        text_map[node_id] = text
                        node_id_to_uuid[node_id] = uuid
                    else:
                        logger.warning("Could not resolve node_id for task_uuid: %s", uuid)
                
                if not text_map:
                    raise ValueError("No content or node_ids found for any provided task_uuids")

                # 4. Call NIM embedder
                logger.debug("🔢 Task %s: calling NIM for %d nodes", tid_str, len(text_map))
                # emb_map format: {node_id: [vector]}
                emb_map = ray.get(self.nim_embedder.embed_texts.remote(text_map), timeout=EMBED_TIMEOUT_S)
                logger.debug("✅ Task %s: NIM returned %d embeddings", tid_str, len(emb_map))

                # 5. Build hash map for upsert, matching your migration logic
                content_hash_map = {
                    nid: self._compute_content_sha256(text_map[nid]) 
                    for nid in emb_map.keys()
                }

                # 6. Upsert embeddings into Postgres
                logger.debug("💾 Task %s: upserting %d NIM embeddings", tid_str, len(emb_map))
                n = ray.get(upsert_embeddings.remote(
                    emb_map, 
                    content_hash_map=content_hash_map,
                    model_map={nid: NIM_MODEL for nid in emb_map.keys()},
                    # Use the "task.primary" label from your migration
                    label_map={nid: "task.primary" for nid in emb_map.keys()}
                ), timeout=UPSERT_TIMEOUT_S)
                
                result = {
                    "embedded": n, 
                    "model": NIM_MODEL, 
                    "embedding_count": len(emb_map),
                    "task_count": len(task_uuids)
                }
                logger.info("✅ Task %s: nim_task_embed completed (embedded=%d) in %.2fs", tid_str, n, time.time() - t0)
                self._stop_heartbeat(tid_str)
                self._complete(tid, result=result)
                return

            if ttype in ("graph_embed", "graph_embed_v2"):
                logger.debug("🎯 Task %s: graph_embed operation (k from params)", tid_str)
                # resolve node ids (legacy: start_ids; v2: map UUID/text ids)
                node_ids, debug = self._resolve_start_node_ids(params)
                k = int(params.get("k", 2))
                logger.debug("🔍 Task %s: resolved %d node_ids, k=%d, debug=%s", tid_str, len(node_ids), k, debug)
                if not node_ids:
                    raise ValueError("No start nodes resolved")

                # chunking support
                if EMBED_BATCH_CHUNK and len(node_ids) > EMBED_BATCH_CHUNK:
                    logger.debug("📦 Task %s: using chunked embedding (chunk_size=%d, total=%d)", tid_str, EMBED_BATCH_CHUNK, len(node_ids))
                    all_maps: Dict[int, List[float]] = {}
                    for i in range(0, len(node_ids), EMBED_BATCH_CHUNK):
                        chunk = node_ids[i:i+EMBED_BATCH_CHUNK]
                        logger.debug("📦 Task %s: processing chunk %d-%d (%d nodes)", tid_str, i, min(i+EMBED_BATCH_CHUNK, len(node_ids)), len(chunk))
                        emb_map = ray.get(self.embedder.compute_embeddings.remote(chunk, k), timeout=EMBED_TIMEOUT_S)
                        all_maps.update(emb_map or {})
                    emb_map = all_maps
                    logger.debug("✅ Task %s: completed chunked embedding, %d total embeddings", tid_str, len(emb_map))
                else:
                    logger.debug("🔢 Task %s: computing embeddings for %d nodes", tid_str, len(node_ids))
                    emb_map = ray.get(self.embedder.compute_embeddings.remote(node_ids, k), timeout=EMBED_TIMEOUT_S)
                    if not emb_map:
                        logger.warning("⚠️ Task %s: compute_embeddings returned empty result for node_ids=%s", tid_str, node_ids[:20])
                    logger.debug("✅ Task %s: embeddings computed, %d embeddings", tid_str, len(emb_map or {}))

                logger.debug("💾 Task %s: upserting %d embeddings", tid_str, len(emb_map or {}))
                n = ray.get(upsert_embeddings.remote(emb_map), timeout=UPSERT_TIMEOUT_S)
                logger.debug("💾 Task %s: upserted %d embeddings", tid_str, n)

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
                
                # Add a helpful diagnostic when no embeddings are returned
                if not emb_map and node_ids:
                    logger.error("❌ Task %s: compute_embeddings returned empty result for node_ids=%s. This usually means the nodes don't exist in Neo4j or the graph loader is misconfigured.", tid_str, node_ids[:20])
                
                logger.info("✅ Task %s: graph_embed completed (embedded=%d, nodes=%d, k=%d) in %.2fs", tid_str, n, len(node_ids), k, time.time() - t0)
                self._stop_heartbeat(tid_str)
                self._complete(tid, result=result)
                return

            if ttype in ("graph_rag_query", "graph_rag_query_v2"):
                import numpy as np

                logger.info("🔍 Task %s: graph_rag_query operation", tid_str)
                node_ids, debug = self._resolve_start_node_ids(params)
                k = int(params.get("k", 2))
                topk = int(params.get("topk", 10))
                logger.debug("🔍 Task %s: resolved %d node_ids, k=%d, topk=%d, debug=%s", tid_str, len(node_ids), k, topk, debug)
                if not node_ids:
                    raise ValueError("No start nodes resolved")

                # ensure embeddings exist for seeds
                logger.debug("🔢 Task %s: computing seed embeddings for %d nodes", tid_str, len(node_ids))
                emb_map = ray.get(self.embedder.compute_embeddings.remote(node_ids, k), timeout=EMBED_TIMEOUT_S)
                if not emb_map:
                    logger.warning("⚠️ Task %s: compute_embeddings returned empty result for node_ids=%s", tid_str, node_ids[:20])
                logger.debug("💾 Task %s: ensuring seed embeddings are persisted", tid_str)
                ray.get(upsert_embeddings.remote(emb_map), timeout=UPSERT_TIMEOUT_S)

                vecs = list(emb_map.values())
                centroid = np.asarray(vecs, dtype="float32").mean(0).tolist() if vecs else None
                logger.debug("📊 Task %s: computed centroid from %d vectors", tid_str, len(vecs))
                
                # Add a helpful diagnostic when no embeddings are returned
                if not vecs and node_ids:
                    logger.error("❌ Task %s: compute_embeddings returned empty result for node_ids=%s. This usually means the nodes don't exist in Neo4j or the graph loader is misconfigured.", tid_str, node_ids[:20])

                hits: List[Dict[str, Any]] = []
                if centroid:
                    centroid_json = json.dumps(centroid)
                    centroid_vec_literal = "[" + ",".join(f"{x:.6f}" for x in centroid) + "]"
                    logger.debug("🔎 Task %s: querying graph_embeddings for topk=%d neighbors", tid_str, topk)
                    try:
                        with self.engine.begin() as conn:
                            rows = conn.execute(
                                text("""
                                  SELECT node_id, emb <-> (CAST(:c AS jsonb)::vector) AS dist
                                    FROM graph_embeddings
                                ORDER BY emb <-> (CAST(:c AS jsonb)::vector)
                                   LIMIT :k
                                """),
                                {"c": centroid_json, "k": topk},
                            ).mappings().all()
                            hits = [{"node_id": r["node_id"], "score": float(r["dist"])} for r in rows]
                        logger.debug("✅ Task %s: found %d neighbors (jsonb method)", tid_str, len(hits))
                    except Exception as e:
                        logger.debug("⚠️ Task %s: jsonb method failed, trying literal method: %s", tid_str, e)
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
                        logger.debug("✅ Task %s: found %d neighbors (literal method)", tid_str, len(hits))
                else:
                    logger.warning("⚠️ Task %s: centroid is None, no hits will be returned", tid_str)

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
                logger.info("✅ Task %s: graph_rag_query completed (hits=%d, seeds=%d, topk=%d) in %.2fs", tid_str, len(hits), len(emb_map or {}), topk, time.time() - t0)
                self._stop_heartbeat(tid_str)
                self._complete(tid, result=result)
                return

            if ttype in ("graph_fact_embed", "graph_fact_query"):
                logger.debug("📝 Task %s: fact operation type=%s", tid_str, ttype)
                # Facts system support (Migration 009)
                node_ids, debug = self._resolve_start_node_ids(params)
                k = int(params.get("k", 2))
                logger.debug("🔍 Task %s: resolved %d fact node_ids, k=%d, debug=%s", tid_str, len(node_ids), k, debug)
                if not node_ids:
                    raise ValueError("No start nodes resolved for facts operation")

                if ttype == "graph_fact_embed":
                    logger.debug("🎯 Task %s: graph_fact_embed operation", tid_str)
                    # Embed facts (similar to graph_embed)
                    if EMBED_BATCH_CHUNK and len(node_ids) > EMBED_BATCH_CHUNK:
                        logger.debug("📦 Task %s: using chunked fact embedding (chunk_size=%d, total=%d)", tid_str, EMBED_BATCH_CHUNK, len(node_ids))
                        all_maps: Dict[int, List[float]] = {}
                        for i in range(0, len(node_ids), EMBED_BATCH_CHUNK):
                            chunk = node_ids[i:i+EMBED_BATCH_CHUNK]
                            logger.debug("📦 Task %s: processing fact chunk %d-%d (%d nodes)", tid_str, i, min(i+EMBED_BATCH_CHUNK, len(node_ids)), len(chunk))
                            emb_map = ray.get(self.embedder.compute_embeddings.remote(chunk, k), timeout=EMBED_TIMEOUT_S)
                            all_maps.update(emb_map or {})
                        emb_map = all_maps
                        logger.debug("✅ Task %s: completed chunked fact embedding, %d total embeddings", tid_str, len(emb_map))
                    else:
                        logger.debug("🔢 Task %s: computing fact embeddings for %d nodes", tid_str, len(node_ids))
                        emb_map = ray.get(self.embedder.compute_embeddings.remote(node_ids, k), timeout=EMBED_TIMEOUT_S)
                        if not emb_map:
                            logger.warning("⚠️ Task %s: compute_embeddings returned empty result for fact node_ids=%s", tid_str, node_ids[:20])
                        logger.debug("✅ Task %s: fact embeddings computed, %d embeddings", tid_str, len(emb_map or {}))

                    logger.debug("💾 Task %s: upserting %d fact embeddings", tid_str, len(emb_map or {}))
                    n = ray.get(upsert_embeddings.remote(emb_map), timeout=UPSERT_TIMEOUT_S)
                    logger.debug("💾 Task %s: upserted %d fact embeddings", tid_str, n)

                    meta_nodes = self._fetch_node_meta(list(emb_map.keys()))
                    result = {
                        "embedded": n,
                        "k": k,
                        "start_node_count": len(node_ids),
                        "embedding_count": len(emb_map or {}),
                        "start_debug": debug,
                        "node_meta": meta_nodes[:64],
                        "operation_type": "fact_embed"
                    }
                    
                    # Add a helpful diagnostic when no embeddings are returned
                    if not emb_map and node_ids:
                        logger.error("❌ Task %s: compute_embeddings returned empty result for fact node_ids=%s. This usually means the nodes don't exist in Neo4j or the graph loader is misconfigured.", tid_str, node_ids[:20])
                    
                    logger.info("✅ Task %s: graph_fact_embed completed (embedded=%d, nodes=%d, k=%d) in %.2fs", tid_str, n, len(node_ids), k, time.time() - t0)
                    self._stop_heartbeat(tid_str)
                    self._complete(tid, result=result)
                    return

                elif ttype == "graph_fact_query":
                    logger.debug("🔍 Task %s: graph_fact_query operation", tid_str)
                    # Query facts (similar to graph_rag_query)
                    import numpy as np

                    # ensure embeddings exist for seeds
                    logger.debug("🔢 Task %s: computing fact seed embeddings for %d nodes", tid_str, len(node_ids))
                    emb_map = ray.get(self.embedder.compute_embeddings.remote(node_ids, k), timeout=EMBED_TIMEOUT_S)
                    if not emb_map:
                        logger.warning("⚠️ Task %s: compute_embeddings returned empty result for fact node_ids=%s", tid_str, node_ids[:20])
                    logger.debug("💾 Task %s: ensuring fact seed embeddings are persisted", tid_str)
                    ray.get(upsert_embeddings.remote(emb_map), timeout=UPSERT_TIMEOUT_S)

                    vecs = list(emb_map.values())
                    centroid = np.asarray(vecs, dtype="float32").mean(0).tolist() if vecs else None
                    logger.debug("📊 Task %s: computed fact centroid from %d vectors", tid_str, len(vecs))
                    
                    # Add a helpful diagnostic when no embeddings are returned
                    if not vecs and node_ids:
                        logger.error("❌ Task %s: compute_embeddings returned empty result for fact node_ids=%s. This usually means the nodes don't exist in Neo4j or the graph loader is misconfigured.", tid_str, node_ids[:20])

                    hits: List[Dict[str, Any]] = []
                    topk = int(params.get("topk", 10))
                    if centroid:
                        centroid_json = json.dumps(centroid)
                        centroid_vec_literal = "[" + ",".join(f"{x:.6f}" for x in centroid) + "]"
                        logger.debug("🔎 Task %s: querying graph_embeddings for topk=%d fact neighbors", tid_str, topk)
                        try:
                            with self.engine.begin() as conn:
                                rows = conn.execute(
                                    text("""
                                      SELECT node_id, emb <-> (CAST(:c AS jsonb)::vector) AS dist
                                        FROM graph_embeddings
                                    ORDER BY emb <-> (CAST(:c AS jsonb)::vector)
                                       LIMIT :k
                                    """),
                                    {"c": centroid_json, "k": topk},
                                ).mappings().all()
                                hits = [{"node_id": r["node_id"], "score": float(r["dist"])} for r in rows]
                            logger.debug("✅ Task %s: found %d fact neighbors (jsonb method)", tid_str, len(hits))
                        except Exception as e:
                            logger.debug("⚠️ Task %s: jsonb method failed for facts, trying literal method: %s", tid_str, e)
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
                            logger.debug("✅ Task %s: found %d fact neighbors (literal method)", tid_str, len(hits))
                    else:
                        logger.warning("⚠️ Task %s: fact centroid is None, no hits will be returned", tid_str)

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
                        "operation_type": "fact_query"
                    }
                    logger.info("✅ Task %s: graph_fact_query completed (hits=%d, seeds=%d, topk=%d) in %.2fs", tid_str, len(hits), len(emb_map or {}), topk, time.time() - t0)
                    self._stop_heartbeat(tid_str)
                    self._complete(tid, result=result)
                    return

            if ttype == "graph_sync_nodes":
                logger.debug("🔄 Task %s: graph_sync_nodes operation", tid_str)
                # ensure every existing task has a node in graph_node_map
                with self.engine.begin() as conn:
                    # optional: versioned function name; fall back if not present
                    try:
                        logger.debug("📝 Task %s: calling backfill_task_nodes()", tid_str)
                        r = conn.execute(text("SELECT backfill_task_nodes() AS updated")).mappings().first()
                        updated = int(r["updated"]) if r and r.get("updated") is not None else None
                        logger.debug("✅ Task %s: backfill_task_nodes() completed, updated=%s", tid_str, updated)
                    except Exception as e:
                        # tolerate absence
                        logger.debug("⚠️ Task %s: backfill_task_nodes() failed or not present: %s", tid_str, e)
                        updated = None
                logger.info("✅ Task %s: graph_sync_nodes completed (updated=%s) in %.2fs", tid_str, updated, time.time() - t0)
                self._stop_heartbeat(tid_str)
                self._complete(tid, result={"backfill_task_nodes": updated})
                return

            # Unknown type
            logger.error("❌ Task %s: unsupported task type: %s (supported: %s)", tid_str, ttype, list(GRAPH_TASK_TYPES))
            self._stop_heartbeat(tid_str)
            self._complete(
                tid,
                result={
                    "error": f"Unsupported task type: {ttype}",
                    "supported_types": list(GRAPH_TASK_TYPES),
                },
            )

        except Exception as e:
            elapsed_ms = round((time.time() - t0) * 1000.0, 2)
            logger.exception("❌ Task %s failed after %.2fms: %s", tid_str, elapsed_ms, e)
            self._stop_heartbeat(tid_str)
            self._complete(tid, error=str(e), retry_after=30)
        finally:
            elapsed_ms = round((time.time() - t0) * 1000.0, 2)
            self._metrics["last_complete_ms"] = elapsed_ms
            logger.debug("⏱️ Task %s: total processing time %.2fms", tid_str, elapsed_ms)

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
