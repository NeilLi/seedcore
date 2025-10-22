from __future__ import annotations
import os
import time
from typing import Dict, List, Optional, Tuple

import torch
import ray
import sqlalchemy as sa
from sqlalchemy import text

from .loader import GraphLoader
from .gnn_models import HeteroSAGE, MemoryFusion
# reuse your existing upsert helper (pgvector)
from .embeddings import upsert_embeddings  # ray.remote fn that writes into graph_embeddings

PG_DSN = os.getenv("SEEDCORE_PG_DSN", os.getenv("PG_DSN", "postgresql://postgres:postgres@postgresql:5432/seedcore"))

# controls
HIDDEN_DIM         = int(os.getenv("LTM_HIDDEN_DIM", "128"))
LTM_LAYERS         = int(os.getenv("LTM_LAYERS", "2"))
DECAY_HALF_LIFE_S  = float(os.getenv("LTM_DECAY_HALF_LIFE_S", "86400"))  # 1 day
DEVICE             = torch.device("cuda" if torch.cuda.is_available() else "cpu")
DB_POOL_SIZE       = int(os.getenv("LTM_DB_POOL_SIZE", "4"))
DB_MAX_OVERFLOW    = int(os.getenv("LTM_DB_MAX_OVERFLOW", "4"))
DB_POOL_RECYCLE_S  = int(os.getenv("LTM_DB_POOL_RECYCLE_S", "600"))

@ray.remote(num_cpus=0.5)
class LTMEmbedder:
    """
    Long-Term Memory (LTM) embedder.

    Responsibilities:
      1) Produce memory-aware TASK embeddings via MemoryFusion over hetero graph.
      2) Produce MEMORY_CELL embeddings (for direct retrieval/refresh).
      3) Refresh recent memory cells by recency window.
      4) (Optional) Summarize agent memory as centroids (returned to caller).

    All embeddings are 128-d by default so they fit graph_embeddings.VECTOR(128).
    """

    def __init__(self):
        # DB engine (optional; used only by helper methods that need SQL)
        self.engine = sa.create_engine(
            PG_DSN,
            future=True,
            pool_pre_ping=True,
            pool_size=DB_POOL_SIZE,
            max_overflow=DB_MAX_OVERFLOW,
            pool_recycle=DB_POOL_RECYCLE_S,
        )
        self.loader = GraphLoader()
        self.hetero: Optional[HeteroSAGE] = None
        self.memfuse: Optional[MemoryFusion] = None
        self._in_dims: Optional[Dict[str, int]] = None

    # ---------- lifecycle ----------
    def ping(self) -> str:
        return "pong"

    def close(self):
        try:
            self.loader.close()
        except Exception:
            pass
        try:
            self.engine.dispose()
        except Exception:
            pass
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # ---------- internals ----------
    def _ensure_models(self, in_dims: Dict[str, int]):
        if self.hetero is None or self._in_dims != in_dims:
            # (re)build model if input dims changed
            self.hetero = HeteroSAGE(in_dims=in_dims, h_feats=HIDDEN_DIM, layers=LTM_LAYERS).to(DEVICE)
            self.memfuse = MemoryFusion(HIDDEN_DIM, use_gate=True).to(DEVICE)
            self._in_dims = dict(in_dims)

    # ---------- public: compute ----------
    def embed_tasks_with_memory(self, start_task_ids: List[int], k: int = 2) -> Dict[int, List[float]]:
        """
        Returns memory-fused embeddings for TASK nodes reachable within k hops.
        Uses time-decayed edge weights from loader for LTM.
        """
        if not start_task_ids:
            return {}

        hg, idx_maps, x_dict, ew = self.loader.load_k_hop_hetero(
            start_ids=start_task_ids, k=k, decay_half_life_s=DECAY_HALF_LIFE_S
        )
        if hg.num_nodes() == 0:
            return {}

        in_dims = {nt: x.shape[1] for nt, x in x_dict.items()}
        self._ensure_models(in_dims)

        with torch.no_grad():
            h = self.hetero(hg, {k: v.to(DEVICE) for k, v in x_dict.items()}, edge_weight_dict=ew)
            h_task = self.memfuse(hg, h, edge_weight_dict=ew)  # [N_task, D]

        inv_maps = {nt: {v: k for k, v in m.items()} for nt, m in idx_maps.items()}
        if "task" not in inv_maps:
            return {}

        T = h_task.cpu()
        return {inv_maps["task"][i]: T[i].tolist() for i in range(T.shape[0])}

    def embed_memory_cells(self, memory_cell_ids: List[int], k: int = 1) -> Dict[int, List[float]]:
        """
        Returns embeddings for MEMORY_CELL nodes; neighbors provide context,
        but we export only the memory_cell vectors.
        """
        if not memory_cell_ids:
            return {}

        hg, idx_maps, x_dict, ew = self.loader.load_k_hop_hetero(
            start_ids=memory_cell_ids, k=k, decay_half_life_s=DECAY_HALF_LIFE_S
        )
        if hg.num_nodes() == 0:
            return {}

        in_dims = {nt: x.shape[1] for nt, x in x_dict.items()}
        self._ensure_models(in_dims)

        with torch.no_grad():
            h = self.hetero(hg, {k: v.to(DEVICE) for k, v in x_dict.items()}, edge_weight_dict=ew)

        inv_maps = {nt: {v: k for k, v in m.items()} for nt, m in idx_maps.items()}
        if "memory_cell" not in inv_maps or "memory_cell" not in h:
            return {}

        M = h["memory_cell"].cpu()
        return {inv_maps["memory_cell"][i]: M[i].tolist() for i in range(M.shape[0])}

    # ---------- public: upsert helpers ----------
    def upsert_task_embeddings(
        self,
        start_task_ids: List[int],
        k: int = 2,
        *,
        label: Optional[str] = None,
        props_map: Optional[Dict[int, Dict[str, object]]] = None,
        model_map: Optional[Dict[int, Optional[str]]] = None,
        content_hash_map: Optional[Dict[int, Optional[str]]] = None,
    ) -> Dict[str, int | float]:
        """
        Compute and upsert memory-fused TASK embeddings into graph_embeddings.
        """
        mapping = self.embed_tasks_with_memory(start_task_ids, k=k)
        if not mapping:
            return {"upserted": 0, "t_ms": 0.0}

        t0 = time.time()
        label_map = None
        if label:
            label_map = {nid: label for nid in mapping.keys()}

        n = ray.get(
            upsert_embeddings.remote(
                mapping,
                label_map=label_map,
                props_map=props_map,
                model_map=model_map,
                content_hash_map=content_hash_map,
            )
        )
        return {"upserted": int(n), "t_ms": round((time.time() - t0) * 1000.0, 2)}

    def upsert_memory_embeddings(self, memory_cell_ids: List[int], k: int = 1) -> Dict[str, int | float]:
        """
        Compute and upsert MEMORY_CELL embeddings into graph_embeddings.
        """
        mapping = self.embed_memory_cells(memory_cell_ids, k=k)
        if not mapping:
            return {"upserted": 0, "t_ms": 0.0}

        t0 = time.time()
        n = ray.get(upsert_embeddings.remote(mapping))
        return {"upserted": int(n), "t_ms": round((time.time() - t0) * 1000.0, 2)}

    # ---------- maintenance workflows ----------
    def refresh_recent_memory(self, updated_within_seconds: int = 86_400, limit: int = 5000) -> Dict[str, int]:
        """
        Find MemoryCell nodes in Neo4j updated recently and refresh their embeddings.
        """
        cutoff = time.time() - max(1, updated_within_seconds)
        with self.loader.driver.session() as s:
            # adapt property name if yours differs
            q = """
            MATCH (m:MemoryCell)
            WHERE exists(m.updated_at) AND m.updated_at >= $cutoff
            RETURN id(m) AS id
            LIMIT $limit
            """
            rows = s.run(q, cutoff=cutoff, limit=limit).data()
        ids = [int(r["id"]) for r in rows] if rows else []
        if not ids:
            return {"found": 0, "refreshed": 0}

        r = self.upsert_memory_embeddings(ids, k=1)
        return {"found": len(ids), "refreshed": int(r["upserted"])}

    def summarize_agent_memory(self, agent_id: int, k: int = 2) -> Dict[str, List[float] | int]:
        """
        Produce a simple centroid summary of an agent's memory cells (via tasks owned_by agent).
        This returns the vector; you can store it in a separate table if desired.
        """
        # 1) fetch memory cell ids connected to tasks owned_by this agent
        with self.loader.driver.session() as s:
            q = """
            MATCH (a:Agent) WHERE id(a) = $aid
            MATCH (t:Task)-[:OWNED_BY]->(a)
            MATCH (t)-[:READS|:WRITES]->(m:MemoryCell)
            RETURN DISTINCT id(m) AS mid
            """
            rows = s.run(q, aid=agent_id).data()
        mem_ids = [int(r["mid"]) for r in rows] if rows else []
        if not mem_ids:
            return {"agent_id": agent_id, "count": 0}

        emb_map = self.embed_memory_cells(mem_ids, k=1)
        if not emb_map:
            return {"agent_id": agent_id, "count": 0}

        import numpy as np
        mat = np.asarray(list(emb_map.values()), dtype="float32")
        centroid = (mat.mean(0) / (np.linalg.norm(mat.mean(0)) + 1e-8)).tolist()
        return {"agent_id": agent_id, "count": len(mem_ids), "centroid": centroid}

