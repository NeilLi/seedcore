from __future__ import annotations
import os
import json
from typing import Dict, List, Tuple, Optional

import torch
import ray
import sqlalchemy as sa
from sqlalchemy import text

from .loader import GraphLoader
from .models import SAGE

PG_DSN = os.getenv("SEEDCORE_PG_DSN", os.getenv("PG_DSN", "postgresql://postgres:postgres@postgresql:5432/seedcore"))

# ====== Tunables ======
GRAPH_IN_FEATS        = int(os.getenv("GRAPH_IN_FEATS", "128"))     # match your feature dim
GRAPH_H_FEATS         = int(os.getenv("GRAPH_H_FEATS", "128"))      # output/embedding dim; matches VECTOR(128)
GRAPH_LAYERS          = int(os.getenv("GRAPH_LAYERS", "2"))
EMBED_BATCH_SIZE      = int(os.getenv("GRAPH_EMBED_BATCH_SIZE", "0"))  # 0 = no micro-batching inside the model
UPSERT_CHUNK_SIZE     = int(os.getenv("GRAPH_UPSERT_CHUNK_SIZE", "200"))  # executemany batch
DB_ECHO               = os.getenv("GRAPH_DB_ECHO", "false").lower() in ("1", "true", "yes")

# ====== Ray Actor: GraphEmbedder ======
@ray.remote(num_cpus=0.5)
class GraphEmbedder:
    """
    Stateful Ray actor that holds a cached GraphSAGE model in memory.
    Backward compatible: compute_embeddings(start_ids, k) -> {node_id: embedding}.
    """

    def __init__(self, checkpoint_path: Optional[str] = None):
        self.loader = GraphLoader()  # should already read from graph_edges/graph_node_map
        self.model: Optional[SAGE] = None
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._emb_dim = GRAPH_H_FEATS
        self._init_model(checkpoint_path)

    def _init_model(self, checkpoint_path: Optional[str]):
        self.model = SAGE(in_feats=GRAPH_IN_FEATS, h_feats=GRAPH_H_FEATS, layers=GRAPH_LAYERS).to(self.device)
        if checkpoint_path and os.path.exists(checkpoint_path):
            state = torch.load(checkpoint_path, map_location=self.device)
            self.model.load_state_dict(state, strict=False)
        self.model.eval()
        print(f"[GraphEmbedder] Model initialized on {self.device} "
              f"(in={GRAPH_IN_FEATS}, h={GRAPH_H_FEATS}, layers={GRAPH_LAYERS})")

    def warmup(self) -> Dict[str, int]:
        """
        Optional: touch a tiny synthetic graph to ensure kernels are JITed and memory’s primed.
        """
        try:
            # Let the loader give us a trivial 0-hop if it supports it; otherwise no-op
            g, idx_map, X = self.loader.load_k_hop(start_ids=[], k=0)
            if g is not None and g.num_nodes() > 0:
                with torch.no_grad():
                    _ = self.model(g, X.to(self.device))
            return {"status": 1}
        except Exception:
            return {"status": 0}

    def embedding_dim(self) -> int:
        """Expose current embedding dimension (helps the upserter validate)."""
        return int(self._emb_dim)

    def compute_embeddings(self, start_ids: List[int], k: int = 2) -> Dict[int, List[float]]:
        """
        Compute embeddings for the k-hop neighborhood around the given node_ids.
        Return: {node_id: [float, ..., len=GRAPH_H_FEATS]}
        """
        g, idx_map, X = self.loader.load_k_hop(start_ids=start_ids, k=k)
        if g is None or g.num_nodes() == 0:
            return {}

        with torch.no_grad():
            Z = self.model(g, X.to(self.device))  # shape: [num_nodes, GRAPH_H_FEATS]
            Z = Z.to("cpu")

        inv = {v: k for k, v in idx_map.items()}
        # NOTE: keep Python lists for portability / JSON-ability
        return {inv[i]: Z[i].tolist() for i in range(Z.shape[0])}

    def ping(self) -> str:
        return "pong"

    def close(self):
        """Cleanup any held resources."""
        try:
            self.loader.close()
        except Exception:
            pass
        try:
            del self.model
        except Exception:
            pass
        if torch.cuda.is_available():
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass


# ====== Upsert task (separate Ray task to allow parallel DB writes) ======
@ray.remote(num_cpus=0.2)
def upsert_embeddings(
    emb_map: Dict[int, List[float]],
    label_map: Optional[Dict[int, Optional[str]]] = None,
    props_map: Optional[Dict[int, Optional[dict]]] = None,
    expected_dim: Optional[int] = GRAPH_H_FEATS,
) -> int:
    """
    Upsert node embeddings into pgvector-backed table graph_embeddings(node_id BIGINT PRIMARY KEY, emb VECTOR(128), ...)
    Uses jsonb::vector cast for safety; executemany in chunks.
    Accepts optional label/props if you later want to backfill metadata.
    """
    if not emb_map:
        return 0

    # quick dimension sanity
    if expected_dim:
        for nid, v in emb_map.items():
            if len(v) != expected_dim:
                raise ValueError(f"Embedding for node {nid} has dim={len(v)} != expected_dim={expected_dim}")

    engine = sa.create_engine(PG_DSN, future=True, echo=DB_ECHO)

    # Build param rows once; we’ll executemany in chunks
    rows = []
    for nid, vec in emb_map.items():
        rows.append({
            "nid": int(nid),
            "vec": json.dumps(vec),  # will cast via ::jsonb::vector in SQL
            "label": (label_map or {}).get(nid),
            "props": json.dumps((props_map or {}).get(nid)) if (props_map and nid in props_map) else None,
        })

    # SQL with optional label/props; if None, keep existing (COALESCE logic on update)
    # NOTE: we do not set created_at/updated_at here explicitly; trigger updates updated_at.
    sql = text("""
        INSERT INTO graph_embeddings (node_id, emb, label, props)
        VALUES (:nid, (:vec)::jsonb::vector, :label, COALESCE(:props::jsonb, props))
        ON CONFLICT (node_id) DO UPDATE
            SET emb = EXCLUDED.emb,
                label = COALESCE(EXCLUDED.label, graph_embeddings.label),
                props = COALESCE(EXCLUDED.props, graph_embeddings.props),
                updated_at = NOW()
    """)

    total = 0
    try:
        with engine.begin() as conn:
            if UPSERT_CHUNK_SIZE and UPSERT_CHUNK_SIZE > 0:
                for i in range(0, len(rows), UPSERT_CHUNK_SIZE):
                    chunk = rows[i:i + UPSERT_CHUNK_SIZE]
                    conn.execute(sql, chunk)  # executemany
                    total += len(chunk)
            else:
                conn.execute(sql, rows)  # executemany in one go
                total = len(rows)
    finally:
        engine.dispose()

    return total
