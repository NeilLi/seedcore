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
logger = logging.getLogger(__name__)

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
        self.dsn = dsn or PG_DSN
        self.name = name
        self.engine = sa.create_engine(self.dsn, future=True)
        
        # Initialize the GraphEmbedder actor with cached model
        self.embedder = GraphEmbedder.options(name=f"{name}_embedder", lifetime="detached").remote(checkpoint_path)
        logger.info("GraphDispatcher '%s' ready with GraphEmbedder actor.", self.name)

    def ping(self) -> str:
        """Simple ping for basic responsiveness check."""
        return "pong"
    
    def heartbeat(self) -> Dict[str, Any]:
        """Enhanced heartbeat with detailed health information."""
        try:
            # Basic health check - GraphDispatcher uses SQLAlchemy engine
            engine_ok = self.engine is not None
            
            health_status = "healthy"
            if not engine_ok:
                health_status = "engine_issue"
            
            return {
                "status": health_status,
                "timestamp": time.time(),
                "engine_ok": engine_ok,
                "name": self.name,
            }
        except Exception as e:
            return {
                "status": "error",
                "timestamp": time.time(),
                "error": str(e),
            }

    # === Task loop (optional; you can also call methods directly) ===
    def run(self, poll_interval: float = 1.0):
        logger.info("GraphDispatcher loop started.")
        while True:
            try:
                task = self._claim_next_task()
                if not task:
                    time.sleep(poll_interval)
                    continue
                self._process(task)
            except Exception as e:
                logger.exception("Run loop error: %s", e)
                time.sleep(2.0)

    # === Core ===
    def _claim_next_task(self) -> Optional[Dict[str, Any]]:
        q = """
        UPDATE tasks
        SET status='running', locked_by=:name, locked_at=NOW()
        WHERE id = (
          SELECT id FROM tasks
          WHERE status IN ('queued','retry')
            AND type IN ('graph_embed','graph_rag_query')
          ORDER BY created_at ASC
          LIMIT 1
        )
        RETURNING id, type, params::text;
        """
        with self.engine.begin() as conn:
            row = conn.execute(text(q), {"name": self.name}).mappings().first()
        return dict(row) if row else None

    def _complete(self, task_id, result=None, error=None, retry_after=None):
        if error:
            new_status = "retry" if retry_after else "failed"
            q = """
            UPDATE tasks
            SET status=:st, error=:err, attempts=attempts+1,
                run_after=NOW() + (:retry * INTERVAL '1 second')
            WHERE id=:id
            """
            params = {"st": new_status, "err": str(error), "retry": retry_after or 0, "id": task_id}
        else:
            q = "UPDATE tasks SET status='completed', result=:res WHERE id=:id"
            params = {"res": json.dumps(result or {}), "id": task_id}
        with self.engine.begin() as conn:
            conn.execute(text(q), params)

    def _process(self, task: Dict[str, Any]):
        tid = task["id"]
        ttype = task["type"]
        params = json.loads(task["params"])
        try:
            if ttype == "graph_embed":
                start_ids: List[int] = params.get("start_ids") or []
                k: int = int(params.get("k", 2))
                emb_map = ray.get(self.embedder.compute_embeddings.remote(start_ids, k), timeout=600)
                n = ray.get(upsert_embeddings.remote(emb_map), timeout=600)
                self._complete(tid, result={"embedded": n})
                logger.info("graph_embed task %s completed: %d nodes", tid, n)

            elif ttype == "graph_rag_query":
                # basic ANN over pgvector
                start_ids: List[int] = params.get("start_ids") or []
                k: int = int(params.get("k", 2))
                topk: int = int(params.get("topk", 10))

                # ensure embeddings exist for the seed neighborhood
                emb_map = ray.get(self.embedder.compute_embeddings.remote(start_ids, k), timeout=600)
                ray.get(upsert_embeddings.remote(emb_map), timeout=600)

                # query nearest neighbors (l2) across graph_embeddings
                # (Use a centroid over the embedded neighborhood for a quick query)
                import numpy as np
                vecs = list(emb_map.values())
                centroid = np.asarray(vecs, dtype="float32").mean(0).tolist() if vecs else None

                hits = []
                if centroid:
                    with self.engine.begin() as conn:
                        sql = text("""
                          SELECT node_id, emb <-> (:centroid::jsonb::vector) AS dist
                          FROM graph_embeddings
                          ORDER BY emb <-> (:centroid::jsonb::vector)
                          LIMIT :k
                        """)
                        rows = conn.execute(sql, {"centroid": json.dumps(centroid), "k": topk}).mappings().all()
                        hits = [{"node_id": r["node_id"], "score": float(r["dist"])} for r in rows]

                # materialize context payload
                context = {"neighbors": hits, "seed_count": len(emb_map)}
                self._complete(tid, result=context)
                logger.info("graph_rag_query task %s completed: %d hits", tid, len(hits))

            else:
                self._complete(tid, error=f"Unsupported task type: {ttype}")

        except Exception as e:
            logger.exception("Task %s failed: %s", tid, e)
            self._complete(tid, error=str(e), retry_after=30)

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
