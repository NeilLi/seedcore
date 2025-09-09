from __future__ import annotations
import os
import json
import time
import logging
from typing import Any, Dict, List, Optional

import ray
import sqlalchemy as sa
from sqlalchemy import text

from seedcore.graph.embeddings import GraphEmbedder, upsert_embeddings

PG_DSN = os.getenv("SEEDCORE_PG_DSN", os.getenv("PG_DSN", "postgresql://postgres:postgres@postgresql:5432/seedcore"))
RAY_NAMESPACE = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))
logger = logging.getLogger(__name__)

# ---- tunables / env knobs ----
EMBED_TIMEOUT_S       = float(os.getenv("GRAPH_EMBED_TIMEOUT_S", "600"))
UPSERT_TIMEOUT_S      = float(os.getenv("GRAPH_UPSERT_TIMEOUT_S", "600"))
HEARTBEAT_PING_S      = float(os.getenv("GRAPH_HEARTBEAT_PING_S", "5"))
DB_POOL_SIZE          = int(os.getenv("GRAPH_DB_POOL_SIZE", "5"))
DB_MAX_OVERFLOW       = int(os.getenv("GRAPH_DB_MAX_OVERFLOW", "5"))
DB_POOL_RECYCLE_S     = int(os.getenv("GRAPH_DB_POOL_RECYCLE_S", "600"))
DB_ECHO               = os.getenv("GRAPH_DB_ECHO", "false").lower() in ("1","true","yes")
TASK_POLL_INTERVAL_S  = float(os.getenv("GRAPH_TASK_POLL_INTERVAL_S", "1.0"))
EMBED_BATCH_CHUNK     = int(os.getenv("GRAPH_EMBED_BATCH_CHUNK", "0"))  # 0 = disabled
# RUN_AFTER_ENABLED removed - always use run_after filter for safety
LOG_DSN               = os.getenv("GRAPH_LOG_DSN", "masked").lower()    # "plain" to print full DSN (not recommended)
STRICT_JSON_RESULT    = os.getenv("GRAPH_STRICT_JSON_RESULT", "true").lower() in ("1","true","yes")

# Recommended database indexes for optimal performance:
# CREATE INDEX CONCURRENTLY idx_tasks_status_type_created ON tasks (status, type, created_at);
# CREATE INDEX CONCURRENTLY idx_tasks_status_run_after ON tasks (status, run_after) WHERE run_after IS NOT NULL;
# CREATE INDEX CONCURRENTLY idx_tasks_type_status ON tasks (type, status) WHERE type IN ('graph_embed', 'graph_rag_query');

def _redact_dsn(dsn: str) -> str:
    if LOG_DSN == "plain":
        return dsn
    try:
        # naive mask of password segment ...://user:pass@host/...
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
      - graph_embed: compute and store embeddings for a k-hop neighborhood
        params: {"start_ids":[int,...], "k":2}
      - graph_rag_query: neighborhood + vector search to augment context
        params: {"start_ids":[int,...], "k":2, "topk": 10}
    """

    def __init__(self, dsn: Optional[str] = None, name: str = "seedcore_graph_dispatcher", checkpoint_path: Optional[str] = None):
        logger.info("🚀 GraphDispatcher '%s' starting initialization...", name)
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
        
        # Phase 1: Database engine setup
        logger.info("📊 GraphDispatcher '%s' phase 1: Setting up database engine with DSN: %s",
                    self.name, _redact_dsn(self.dsn))
        try:
            # robust pool + pre_ping to kill dead connections
            self.engine = sa.create_engine(
                self.dsn,
                future=True,
                pool_size=DB_POOL_SIZE,
                max_overflow=DB_MAX_OVERFLOW,
                pool_pre_ping=True,
                pool_recycle=DB_POOL_RECYCLE_S,
                echo=DB_ECHO,
            )
            logger.info("✅ GraphDispatcher '%s' database engine created successfully", self.name)
        except Exception as e:
            logger.error("❌ GraphDispatcher '%s' failed to create database engine: %s", self.name, e)
            raise
        
        # Phase 2: Test database connectivity
        logger.info("🔗 GraphDispatcher '%s' phase 2: Testing database connectivity", self.name)
        try:
            with self.engine.begin() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("✅ GraphDispatcher '%s' database connectivity test passed", self.name)
        except Exception as e:
            logger.error("❌ GraphDispatcher '%s' database connectivity test failed: %s", self.name, e)
            raise
        
        # Phase 3: GraphEmbedder actor setup
        embedder_name = self._embedder_name
        logger.info("🤖 GraphDispatcher '%s' phase 3: Setting up GraphEmbedder actor '%s'", self.name, embedder_name)
        
        try:
            self.embedder = ray.get_actor(embedder_name, namespace=RAY_NAMESPACE)
            logger.info("✅ GraphDispatcher '%s' reusing existing GraphEmbedder: %s", self.name, embedder_name)
        except ValueError:
            # Actor doesn't exist, create a new one
            logger.info("🆕 GraphDispatcher '%s' creating new GraphEmbedder: %s", self.name, embedder_name)
            try:
                self.embedder = GraphEmbedder.options(
                    name=embedder_name,
                    lifetime="detached",
                    namespace=RAY_NAMESPACE
                ).remote(checkpoint_path)
                logger.info("✅ GraphDispatcher '%s' created new GraphEmbedder: %s", self.name, embedder_name)
            except Exception as e:
                logger.error("❌ GraphDispatcher '%s' failed to create GraphEmbedder: %s", self.name, e)
                raise
        
        # Phase 4: Test GraphEmbedder responsiveness
        logger.info("🧪 GraphDispatcher '%s' phase 4: Testing GraphEmbedder responsiveness", self.name)
        try:
            # Test if the embedder is responsive
            test_result = ray.get(self.embedder.ping.remote(), timeout=10)
            if test_result == "pong":
                logger.info("✅ GraphDispatcher '%s' GraphEmbedder ping test passed", self.name)
            else:
                logger.warning("⚠️ GraphDispatcher '%s' GraphEmbedder ping returned unexpected result: %s", self.name, test_result)
        except AttributeError as e:
            if "'ActorHandle' object has no attribute 'ping'" in str(e):
                logger.warning("⚠️ GraphDispatcher '%s' GraphEmbedder doesn't have ping method - this is expected for older versions", self.name)
            else:
                logger.error("❌ GraphDispatcher '%s' GraphEmbedder ping test failed (AttributeError): %s", self.name, e)
        except Exception as e:
            logger.error("❌ GraphDispatcher '%s' GraphEmbedder ping test failed: %s", self.name, e)
            # Don't raise here - GraphEmbedder might be slow to start but could recover
        
        init_time = time.time() - start_time
        logger.info("🎉 GraphDispatcher '%s' initialization completed in %.2f seconds", self.name, init_time)
        
        # Mark as ready for health checks
        self._startup_complete = True
        self._startup_time = init_time

    def get_startup_status(self) -> Dict[str, Any]:
        """Get detailed startup status information."""
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
        """Simple ping for basic responsiveness check."""
        ping_start = time.time()
        logger.debug("🏓 GraphDispatcher '%s' ping() called at %.3f", self.name, ping_start)
        
        try:
            # Check if startup is complete
            if not getattr(self, '_startup_complete', False):
                logger.warning("⚠️ GraphDispatcher '%s' ping: startup not complete yet", self.name)
                return "pong"  # Still return pong to indicate actor is alive
            
            # Quick health check - verify we can access our components
            if not hasattr(self, 'engine') or self.engine is None:
                logger.warning("⚠️ GraphDispatcher '%s' ping: engine not available", self.name)
                return "pong"  # Still return pong to indicate actor is alive
            
            if not hasattr(self, 'embedder') or self.embedder is None:
                logger.warning("⚠️ GraphDispatcher '%s' ping: embedder not available", self.name)
                return "pong"  # Still return pong to indicate actor is alive
            
            # Test database connection quickly
            try:
                with self.engine.begin() as conn:
                    conn.execute(text("SELECT 1"))
                logger.debug("✅ GraphDispatcher '%s' ping: database connection OK", self.name)
            except Exception as e:
                logger.warning("⚠️ GraphDispatcher '%s' ping: database connection issue: %s", self.name, e)
                # Don't fail ping for DB issues - actor is still alive
            
            ping_duration = time.time() - ping_start
            logger.debug("🏓 GraphDispatcher '%s' ping() completed in %.3f seconds", self.name, ping_duration)
            
            return "pong"
        except Exception as e:
            logger.error("❌ GraphDispatcher '%s' ping() failed: %s", self.name, e)
            # Still return pong to indicate actor is alive, even if there are issues
            return "pong"

    def get_metrics(self) -> Dict[str, Any]:
        """Lightweight counters for observability."""
        return dict(self._metrics, timestamp=time.time())

    def set_log_level(self, level: str = "INFO") -> bool:
        try:
            logger.setLevel(getattr(logging, level.upper(), logging.INFO))
            return True
        except Exception:
            return False
    
    def heartbeat(self) -> Dict[str, Any]:
        """Enhanced heartbeat with detailed health information."""
        heartbeat_start = time.time()
        logger.debug("💓 GraphDispatcher '%s' heartbeat() called", self.name)
        
        try:
            # Comprehensive health checks
            health_checks = {
                "engine_available": False,
                "engine_connected": False,
                "embedder_available": False,
                "embedder_responsive": False,
                "database_query_ok": False,
            }
            
            # Check engine availability
            if hasattr(self, 'engine') and self.engine is not None:
                health_checks["engine_available"] = True
                
                # Test database connection
                try:
                    with self.engine.begin() as conn:
                        result = conn.execute(text("SELECT 1 as test")).scalar()
                        if result == 1:
                            health_checks["engine_connected"] = True
                            health_checks["database_query_ok"] = True
                except Exception as e:
                    logger.warning("⚠️ GraphDispatcher '%s' heartbeat: database connection failed: %s", self.name, e)
            
            # Check embedder availability
            if hasattr(self, 'embedder') and self.embedder is not None:
                health_checks["embedder_available"] = True
                
                # Test embedder responsiveness (with timeout)
                try:
                    embedder_ping = ray.get(self.embedder.ping.remote(), timeout=5)
                    if embedder_ping == "pong":
                        health_checks["embedder_responsive"] = True
                except AttributeError as e:
                    if "'ActorHandle' object has no attribute 'ping'" in str(e):
                        logger.debug("GraphDispatcher '%s' heartbeat: GraphEmbedder doesn't have ping method", self.name)
                        # Consider embedder available but not testable via ping
                        health_checks["embedder_responsive"] = True
                    else:
                        logger.warning("⚠️ GraphDispatcher '%s' heartbeat: embedder ping failed (AttributeError): %s", self.name, e)
                except Exception as e:
                    logger.warning("⚠️ GraphDispatcher '%s' heartbeat: embedder ping failed: %s", self.name, e)
            
            # Determine overall health status
            critical_issues = []
            if not health_checks["engine_available"]:
                critical_issues.append("engine_missing")
            if not health_checks["engine_connected"]:
                critical_issues.append("engine_disconnected")
            if not health_checks["embedder_available"]:
                critical_issues.append("embedder_missing")
            
            if critical_issues:
                health_status = f"unhealthy_{'_'.join(critical_issues)}"
            elif not health_checks["embedder_responsive"]:
                health_status = "degraded_embedder_unresponsive"
            elif not health_checks["database_query_ok"]:
                health_status = "degraded_database_issues"
            else:
                health_status = "healthy"
            
            heartbeat_duration = time.time() - heartbeat_start
            logger.debug("💓 GraphDispatcher '%s' heartbeat completed in %.3f seconds", self.name, heartbeat_duration)
            
            return {
                "status": health_status,
                "timestamp": time.time(),
                "heartbeat_duration_ms": round(heartbeat_duration * 1000, 2),
                "name": self.name,
                "health_checks": health_checks,
                "critical_issues": critical_issues,
            }
        except Exception as e:
            logger.error("❌ GraphDispatcher '%s' heartbeat failed: %s", self.name, e)
            return {
                "status": "error",
                "timestamp": time.time(),
                "error": str(e),
                "name": self.name,
            }

    # === Task loop (optional; you can also call methods directly) ===
    def run(self, poll_interval: float = TASK_POLL_INTERVAL_S):
        """Start the run loop in a background thread."""
        logger.info("🚀 GraphDispatcher '%s' starting run loop with poll_interval=%.1f", self.name, poll_interval)
        
        # Start the run loop in a background thread
        import threading
        self._run_thread = threading.Thread(target=self._run_loop, args=(poll_interval,), daemon=True)
        self._run_thread.start()
        
    def _run_loop(self, poll_interval: float = TASK_POLL_INTERVAL_S):
        """Internal run loop that runs in a background thread."""
        logger.info("🚀 GraphDispatcher '%s' run loop started with poll_interval=%.1f", self.name, poll_interval)
        loop_count = 0
        last_task_time = time.time()
        
        while self._running:
            try:
                loop_count += 1
                current_time = time.time()
                
                # Log periodic status
                if loop_count % 100 == 0:  # Every 100 iterations
                    uptime = current_time - last_task_time
                    logger.info("🔄 GraphDispatcher '%s' run loop iteration %d, uptime: %.1fs", self.name, loop_count, uptime)
                
                task = self._claim_next_task()
                if not task:
                    time.sleep(poll_interval)
                    continue
                
                last_task_time = current_time
                self._process(task)
                
            except Exception as e:
                logger.exception("❌ GraphDispatcher '%s' run loop error at iteration %d: %s", self.name, loop_count, e)
                time.sleep(2.0)

    def stop(self) -> bool:
        """Request the run loop to stop."""
        self._running = False
        return True

    # === Core ===
    def _claim_next_task(self) -> Optional[Dict[str, Any]]:
        q = """
        UPDATE tasks
        SET status='running',
            locked_by=:name,
            locked_at=NOW()
        WHERE id = (
          SELECT id FROM tasks
          WHERE status IN ('queued','retry')
            AND type IN ('graph_embed','graph_rag_query')
            AND (run_after IS NULL OR run_after <= NOW())
          ORDER BY created_at ASC
          LIMIT 1
        )
        RETURNING id, type, params::text;
        """
        try:
            sql = text(q)
            with self.engine.begin() as conn:
                row = conn.execute(sql, {"name": self.name}).mappings().first()
            return dict(row) if row else None
        except Exception as e:
            logger.error("❌ GraphDispatcher '%s' failed to claim next task: %s", self.name, e)
            # Don't raise - let the run loop continue and retry
            return None

    def _complete(self, task_id, result=None, error=None, retry_after=None):
        try:
            if error:
                new_status = "retry" if retry_after else "failed"
                q = """
                UPDATE tasks
                SET status=:st, error=:err, attempts=attempts+1,
                    run_after=NOW() + (:retry * INTERVAL '1 second')
                WHERE id=:id
                """
                params = {"st": new_status, "err": str(error), "retry": retry_after or 0, "id": task_id}
                logger.info("📝 GraphDispatcher '%s' completing task %s with status: %s", self.name, task_id, new_status)
            else:
                # Ensure we always have a structured result, never None or empty
                structured_result = result if result is not None else {"status": "completed", "message": "Task completed successfully"}
                if STRICT_JSON_RESULT:
                    # guard against non-JSON-serializable values
                    try:
                        json.dumps(structured_result)
                    except Exception:
                        structured_result = {"status": "completed", "note": "Non-JSON result was sanitized"}
                q = "UPDATE tasks SET status='completed', result=:res WHERE id=:id"
                params = {"res": json.dumps(structured_result), "id": task_id}
                logger.info("✅ GraphDispatcher '%s' completing task %s successfully", self.name, task_id)
            
            with self.engine.begin() as conn:
                conn.execute(text(q), params)
            self._metrics["tasks_completed"] += 0 if error else 1
            if error:
                self._metrics["tasks_failed"] += 1
        except Exception as e:
            logger.error("❌ GraphDispatcher '%s' failed to complete task %s: %s", self.name, task_id, e)
            # Don't raise - this is a completion operation

    def _process(self, task: Dict[str, Any]):
        tid = task["id"]
        ttype = task["type"]
        logger.info("🔄 GraphDispatcher '%s' processing task %s of type %s", self.name, tid, ttype)
        self._metrics["tasks_claimed"] += 1
        self._metrics["last_task_id"] = tid
        t0 = time.time()
        
        try:
            params = json.loads(task["params"])
        except Exception as e:
            logger.error("❌ GraphDispatcher '%s' failed to parse task %s params: %s", self.name, tid, e)
            self._complete(tid, error=f"Invalid task params: {e}")
            return
        
        try:
            if ttype == "graph_embed":
                start_ids: List[int] = params.get("start_ids") or []
                k: int = int(params.get("k", 2))
                if not isinstance(start_ids, list):
                    raise ValueError("start_ids must be a list of node ids")

                # optional chunking to avoid mega-queries
                if EMBED_BATCH_CHUNK and len(start_ids) > EMBED_BATCH_CHUNK:
                    all_maps: Dict[int, List[float]] = {}
                    for i in range(0, len(start_ids), EMBED_BATCH_CHUNK):
                        chunk = start_ids[i:i+EMBED_BATCH_CHUNK]
                        emb_map = ray.get(self.embedder.compute_embeddings.remote(chunk, k), timeout=EMBED_TIMEOUT_S)
                        all_maps.update(emb_map or {})
                    emb_map = all_maps
                else:
                    emb_map = ray.get(self.embedder.compute_embeddings.remote(start_ids, k), timeout=EMBED_TIMEOUT_S)

                n = ray.get(upsert_embeddings.remote(emb_map), timeout=UPSERT_TIMEOUT_S)
                # Always write structured result
                result = {"embedded": n, "start_ids": start_ids, "k": k, "embedding_count": len(emb_map)}
                self._complete(tid, result=result)
                logger.info("graph_embed task %s completed: %d nodes", tid, n)

            elif ttype == "graph_rag_query":
                # basic ANN over pgvector
                start_ids: List[int] = params.get("start_ids") or []
                k: int = int(params.get("k", 2))
                topk: int = int(params.get("topk", 10))

                # ensure embeddings exist for the seed neighborhood
                emb_map = ray.get(self.embedder.compute_embeddings.remote(start_ids, k), timeout=EMBED_TIMEOUT_S)
                ray.get(upsert_embeddings.remote(emb_map), timeout=UPSERT_TIMEOUT_S)

                # query nearest neighbors (l2) across graph_embeddings
                # (Use a centroid over the embedded neighborhood for a quick query)
                import numpy as np
                vecs = list(emb_map.values())
                centroid = np.asarray(vecs, dtype="float32").mean(0).tolist() if vecs else None

                hits = []
                if centroid:
                    # try JSONB::vector cast first (project-specific), then fallback to text::vector
                    centroid_json = json.dumps(centroid)
                    centroid_vec_literal = "[" + ",".join(f"{x:.6f}" for x in centroid) + "]"
                    try:
                        with self.engine.begin() as conn:
                            sql = text("""
                              SELECT node_id, emb <-> (:centroid::jsonb::vector) AS dist
                              FROM graph_embeddings
                              ORDER BY emb <-> (:centroid::jsonb::vector)
                              LIMIT :k
                            """)
                            rows = conn.execute(sql, {"centroid": centroid_json, "k": topk}).mappings().all()
                            hits = [{"node_id": r["node_id"], "score": float(r["dist"])} for r in rows]
                    except Exception as cast_err:
                        logger.debug("JSONB::vector cast failed, falling back to text::vector: %s", cast_err)
                        with self.engine.begin() as conn:
                            sql = text("""
                              SELECT node_id, emb <-> (:centroid)::vector AS dist
                              FROM graph_embeddings
                              ORDER BY emb <-> (:centroid)::vector
                              LIMIT :k
                            """)
                            rows = conn.execute(sql, {"centroid": centroid_vec_literal, "k": topk}).mappings().all()
                            hits = [{"node_id": r["node_id"], "score": float(r["dist"])} for r in rows]

                # Always write structured result with fallbacks
                context = {
                    "neighbors": hits or [], 
                    "seed_count": len(emb_map) if emb_map else 0,
                    "start_ids": start_ids,
                    "k": k,
                    "topk": topk,
                    "centroid_computed": centroid is not None,
                    "embedding_count": len(emb_map) if emb_map else 0
                }
                self._complete(tid, result=context)
                logger.info("graph_rag_query task %s completed: %d hits", tid, len(hits))

            else:
                # Always write structured result even for unsupported task types
                result = {
                    "error": f"Unsupported task type: {ttype}",
                    "supported_types": ["graph_embed", "graph_rag_query"],
                    "task_type": ttype,
                    "params": params
                }
                self._complete(tid, result=result)
                logger.warning("Unsupported task type %s for task %s", ttype, tid)

        except Exception as e:
            logger.exception("Task %s failed: %s", tid, e)
            self._complete(tid, error=str(e), retry_after=30)
        finally:
            self._metrics["last_complete_ms"] = round((time.time() - t0) * 1000.0, 2)

    def cleanup(self):
        """Cleanup resources including the GraphEmbedder actor."""
        try:
            if hasattr(self, 'embedder'):
                ray.get(self.embedder.close.remote(), timeout=30)
                logger.info("GraphEmbedder actor cleaned up successfully.")
        except Exception as e:
            logger.warning("Failed to cleanup GraphEmbedder actor: %s", e)
        
        try:
            if hasattr(self, 'engine'):
                self.engine.dispose()
                logger.info("Database engine disposed successfully.")
        except Exception as e:
            logger.warning("Failed to dispose database engine: %s", e)
