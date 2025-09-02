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

# ---------- Ray Actor ----------

@ray.remote(num_cpus=0.5)
class GraphEmbedder:
    """
    Stateful Ray actor that holds a cached GraphSAGE model in memory.
    Prevents reinitializing the model on every call.
    """

    def __init__(self, checkpoint_path: str | None = None):
        self.loader = GraphLoader()
        self.model: SAGE | None = None
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._init_model(checkpoint_path)

    def _init_model(self, checkpoint_path: str | None):
        # You may want to parameterize input dims if known
        in_feats = 128  # TODO: set based on your dataset/loader
        self.model = SAGE(in_feats=in_feats, h_feats=128, layers=2).to(self.device)
        if checkpoint_path and os.path.exists(checkpoint_path):
            state = torch.load(checkpoint_path, map_location=self.device)
            self.model.load_state_dict(state)
        self.model.eval()
        print(f"[GraphEmbedder] Model initialized on {self.device}")

    def compute_embeddings(self, start_ids: List[int], k: int = 2) -> Dict[int, List[float]]:
        """Compute embeddings for k-hop neighborhood and return mapping."""
        g, idx_map, X = self.loader.load_k_hop(start_ids=start_ids, k=k)

        if g.num_nodes() == 0:
            return {}

        with torch.no_grad():
            Z = self.model(g, X.to(self.device))

        inv = {v: k for k, v in idx_map.items()}
        return {inv[i]: Z[i].cpu().tolist() for i in range(Z.shape[0])}

    def close(self):
        """Cleanup any held resources."""
        self.loader.close()
        del self.model
        torch.cuda.empty_cache()

# ---------- Separate upsert stays as task ----------


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
                 sa.Column("emb", sa.ARRAY(sa.Float)),   # Ideally replace with pgvector type
                 sa.Column("created_at", sa.DateTime(timezone=True)),
                 sa.Column("updated_at", sa.DateTime(timezone=True)),
                 schema=None, autoload_with=engine)

    rows = [{"node_id": nid, "emb": emb} for nid, emb in emb_map.items()]
    with engine.begin() as conn:
        stmt = """
        INSERT INTO graph_embeddings (node_id, emb)
        VALUES %s
        ON CONFLICT (node_id) DO UPDATE SET emb = EXCLUDED.emb, updated_at = NOW();
        """
        values_sql = ",".join(
            "(" + f"{r['node_id']}, '{json.dumps(r['emb'])}'::jsonb::vector" + ")"
            for r in rows
        )
        conn.exec_driver_sql(stmt % values_sql)
    engine.dispose()
    return len(rows)
