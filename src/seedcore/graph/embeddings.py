from __future__ import annotations
import os
import json
from typing import Dict, List, Tuple

import torch
import ray
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from .loader import GraphLoader
from .models import SAGE

PG_DSN = os.getenv("SEEDCORE_PG_DSN", os.getenv("PG_DSN", "postgresql://postgres:postgres@postgresql:5432/seedcore"))

# ---------- Ray tasks ----------

@ray.remote(num_cpus=0.5)
def compute_graph_embeddings(start_ids: List[int], k: int = 2) -> Dict[int, List[float]]:
    """
    Pull subgraph from Neo4j and compute 128-d embeddings for each node.
    Returns {neo4j_id: [float,...]}.
    """
    loader = GraphLoader()
    try:
        g, idx_map, X = loader.load_k_hop(start_ids=start_ids, k=k)
    finally:
        loader.close()

    if g.num_nodes() == 0:
        return {}

    model = SAGE(in_feats=X.shape[1], h_feats=128, layers=2)
    model.eval()
    with torch.no_grad():
        Z = model(g, X)  # [N, 128]

    # reverse map: index -> neo_id
    inv = {v: k for k, v in idx_map.items()}
    out = {inv[i]: Z[i].cpu().tolist() for i in range(Z.shape[0])}
    return out


@ray.remote(num_cpus=0.2)
def upsert_embeddings(emb_map: Dict[int, List[float]]) -> int:
    """Upsert node embeddings into pgvector table graph_embeddings."""
    if not emb_map:
        return 0
    engine = sa.create_engine(PG_DSN, future=True)
    meta = sa.MetaData()
    t = sa.Table("graph_embeddings", meta,
                 sa.Column("node_id", sa.BigInteger, primary_key=True),
                 sa.Column("label", sa.Text),
                 sa.Column("props", sa.dialects.postgresql.JSONB),
                 sa.Column("emb", sa.ARRAY(sa.Float)),   # SQLAlchemy fallback; we'll cast in SQL
                 sa.Column("created_at", sa.DateTime(timezone=True)),
                 sa.Column("updated_at", sa.DateTime(timezone=True)),
                 schema=None, autoload_with=engine)

    # Insert with vector cast ::vector
    rows = [{"node_id": nid, "emb": emb} for nid, emb in emb_map.items()]
    with engine.begin() as conn:
        # raw upsert to use vector type
        stmt = """
        INSERT INTO graph_embeddings (node_id, emb)
        VALUES %s
        ON CONFLICT (node_id) DO UPDATE SET emb = EXCLUDED.emb, updated_at = NOW();
        """
        # Build value tuples with casting to vector
        values_sql = ",".join(
            "(" + f"{r['node_id']}, '{json.dumps(r['emb'])}'::jsonb::vector" + ")"
            for r in rows
        )
        conn.exec_driver_sql(stmt % values_sql)
    engine.dispose()
    return len(rows)
