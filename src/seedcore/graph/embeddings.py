#!/usr/bin/env python3
"""
Ray-based NIM Retrieval Embedder.

Uses NVIDIA's NIM Retrieval model (e.g., nv-embedqa-e5-v5) deployed remotely on EKS
to compute embeddings for graph nodes, and upserts them into pgvector (graph_embeddings).

Env Vars:
  NIM_RETRIEVAL_MODEL=nvidia/nv-embedqa-e5-v5
  NIM_RETRIEVAL_PROVIDER=nim
  NIM_RETRIEVAL_BASE_URL=@http://af3a6a34f659a409584db07209d82853-1298671438.us-east-1.elb.amazonaws.com/v1
  NIM_RETRIEVAL_API_KEY=none
  SEEDCORE_PG_DSN=postgresql://postgres:postgres@postgresql:5432/seedcore
"""

import os
import json
import time
import logging
from typing import Dict, List, Optional

import ray
import requests
import sqlalchemy as sa
from sqlalchemy import text
from .loader import GraphLoader
from .gnn_models import SAGE

logger = logging.getLogger(__name__)

# ---------- Environment ----------
PG_DSN = os.getenv("SEEDCORE_PG_DSN", "postgresql://postgres:postgres@postgresql:5432/seedcore")
NIM_BASE_URL = os.getenv("NIM_RETRIEVAL_BASE_URL", "").lstrip("@")
NIM_API_KEY = os.getenv("NIM_RETRIEVAL_API_KEY", "none")
NIM_MODEL = os.getenv("NIM_RETRIEVAL_MODEL", "nvidia/nv-embedqa-e5-v5")

UPSERT_CHUNK_SIZE = int(os.getenv("GRAPH_UPSERT_CHUNK_SIZE", "200"))
DB_ECHO = os.getenv("GRAPH_DB_ECHO", "false").lower() in ("1", "true", "yes")

# Memory budget for Ray actors/tasks (default ~0.5 GiB)
# Use GiB to be explicit and avoid rounding surprises.
GRAPH_ACTOR_MEMORY_BYTES = int(os.getenv("GRAPH_ACTOR_MEMORY_BYTES", str(512 * 1024 * 1024)))

HEADERS = {"Content-Type": "application/json"}
if NIM_API_KEY and NIM_API_KEY.lower() != "none":
    HEADERS["Authorization"] = f"Bearer {NIM_API_KEY}"

EMBED_URL = f"{NIM_BASE_URL}/embeddings"
DEFAULT_LABEL = os.getenv("GRAPH_EMBEDDING_DEFAULT_LABEL", "default")


# ---------- Ray Actor: GraphEmbedder (legacy SAGE over homogeneous graph) ----------
@ray.remote(num_cpus=0.1, memory=GRAPH_ACTOR_MEMORY_BYTES)
class GraphEmbedder:
    """
    Computes node embeddings using a simple GraphSAGE model over a k-hop
    homogeneous DGL graph loaded from Neo4j. Returns L2-normalized vectors.
    """

    def __init__(self):
        self.loader = GraphLoader()
        self.model = None
        self.in_feats = None

    def _ensure_model(self, in_feats: int):
        if self.model is None or self.in_feats != in_feats:
            self.model = SAGE(in_feats=in_feats, h_feats=128, layers=2)
            self.in_feats = in_feats

    def ping(self) -> str:
        return "pong"

    def compute_embeddings(self, node_ids: List[int], k: int = 2) -> Dict[int, List[float]]:
        if not node_ids:
            return {}

        try:
            g, idx_map, X = self.loader.load_k_hop(node_ids, k=k)
        except ImportError as e:
            logger.error("DGL not available for GraphEmbedder: %s", e)
            return {}
        except Exception as e:
            logger.error("Failed to load k-hop graph: %s", e)
            return {}

        if g is None or getattr(g, 'num_nodes', lambda: 0)() == 0 or X is None or X.numel() == 0:
            return {}

        self._ensure_model(X.shape[1])

        try:
            import torch
            with torch.no_grad():
                H = self.model(g, X)
        except Exception as e:
            logger.error("SAGE forward failed: %s", e)
            return {}

        # invert idx_map to original node ids
        inv_map = {v: k for k, v in idx_map.items()}
        return {int(inv_map[i]): H[i].tolist() for i in range(H.shape[0])}

    def close(self):
        try:
            self.loader.close()
        except Exception:
            pass


# ---------- Ray Actor: NimRetrievalEmbedder ----------
@ray.remote(num_cpus=0.1, memory=GRAPH_ACTOR_MEMORY_BYTES)
class NimRetrievalEmbedder:
    """
    Ray actor that queries NIM Retrieval service to produce embeddings for text nodes.
    """

    def __init__(self):
        self.model = NIM_MODEL
        self.url = EMBED_URL
        self.headers = HEADERS
        self.session = requests.Session()
        logger.info(f"[NIM Retrieval] Using model={self.model}, url={self.url}")

    def ping(self) -> str:
        try:
            r = self.session.get(self.url.replace("/embeddings", "/health"), timeout=5)
            return "ok" if r.status_code == 200 else f"fail:{r.status_code}"
        except Exception as e:
            return f"error:{e}"

    def embed_texts(self, items: Dict[int, str]) -> Dict[int, List[float]]:
        """
        Send text batches to NIM Retrieval model for embedding.
        Input: {node_id: text}
        Output: {node_id: [float vector]}
        """
        if not items:
            return {}

        payload = {
            "model": self.model,
            "input": list(items.values())
        }

        try:
            resp = self.session.post(self.url, headers=self.headers, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            if "data" not in data:
                logger.error(f"Invalid response from NIM: {data}")
                return {}

            vectors = [d["embedding"] for d in data["data"]]
            return {nid: vec for nid, vec in zip(items.keys(), vectors)}

        except Exception as e:
            logger.error(f"NIM embedding request failed: {e}")
            return {}

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass


# ---------- Ray Task: Upsert Embeddings ----------
@ray.remote(num_cpus=0.1, memory=GRAPH_ACTOR_MEMORY_BYTES)
def upsert_embeddings(
    emb_map: Dict[int, List[float]],
    label_map: Optional[Dict[int, Optional[str]]] = None,
    props_map: Optional[Dict[int, Optional[dict]]] = None,
    model_map: Optional[Dict[int, Optional[str]]] = None,
    content_hash_map: Optional[Dict[int, Optional[str]]] = None,
) -> int:
    """
    Upsert embeddings into pgvector table `graph_embeddings`.
    """
    if not emb_map:
        return 0

    engine = sa.create_engine(PG_DSN, future=True, echo=DB_ECHO)
    rows = []
    for nid, vec in emb_map.items():
        props_value = json.dumps(props_map[nid]) if props_map and nid in props_map else None
        rows.append({
            "nid": int(nid),
            "vec": json.dumps(vec),
            "label": (label_map or {}).get(nid) or DEFAULT_LABEL,
            "props": props_value,
            "model": (model_map or {}).get(nid) or NIM_MODEL,
            "content_sha256": (content_hash_map or {}).get(nid),
        })

    sql = text("""
        INSERT INTO graph_embeddings (node_id, label, emb, props, model, content_sha256)
        VALUES (
            :nid,
            :label,
            (:vec)::jsonb::vector,
            CASE WHEN :props IS NULL THEN NULL ELSE (:props)::jsonb END,
            :model,
            :content_sha256
        )
        ON CONFLICT (node_id, label) DO UPDATE
            SET emb = EXCLUDED.emb,
                props = COALESCE(EXCLUDED.props, graph_embeddings.props),
                model = COALESCE(EXCLUDED.model, graph_embeddings.model),
                content_sha256 = COALESCE(EXCLUDED.content_sha256, graph_embeddings.content_sha256),
                updated_at = NOW()
    """)

    total = 0
    try:
        with engine.begin() as conn:
            if UPSERT_CHUNK_SIZE and UPSERT_CHUNK_SIZE > 0:
                for i in range(0, len(rows), UPSERT_CHUNK_SIZE):
                    chunk = rows[i:i + UPSERT_CHUNK_SIZE]
                    conn.execute(sql, chunk)
                    total += len(chunk)
            else:
                conn.execute(sql, rows)
                total = len(rows)
    finally:
        engine.dispose()

    return total


# ---------- Standalone Smoke Test ----------
if __name__ == "__main__":
    ray.init(ignore_reinit_error=True)
    print("Connecting to NIM Retrieval:", EMBED_URL)

    actor = NimRetrievalEmbedder.remote()
    ping_result = ray.get(actor.ping.remote())
    print("Ping result:", ping_result)

    sample_items = {
        1: "Agentic cognitive orchestration enables dynamic tool-use in complex environments.",
        2: "Ray Serve allows distributed inference at scale for graph-based AI workloads."
    }

    embeddings = ray.get(actor.embed_texts.remote(sample_items))
    print(json.dumps(embeddings, indent=2)[:400], "...")

    if embeddings:
        total = ray.get(upsert_embeddings.remote(embeddings))
        print(f"Upserted {total} rows into graph_embeddings.")
    else:
        print("No embeddings returned.")
