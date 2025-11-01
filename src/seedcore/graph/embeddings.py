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

from __future__ import annotations

import os
import json
import time
import logging
import sys
from typing import Dict, List, Optional

import ray
from ray.util import log_once
import requests
import sqlalchemy as sa
from sqlalchemy import text

# --- [ SOLUTION ] ---
# Move logger setup BEFORE importing libraries that might hijack logging (DGL, torch, GraphLoader)

from seedcore.logging_setup import ensure_serve_logger

def get_seedcore_logger(name: str, level="DEBUG"):
    logger = ensure_serve_logger(name, level=level)
    
    # HACK: Remove the faulty `if not logger.handlers:` check.
    # This ensures your stdout handler is ALWAYS added, even if
    # a library (like torch) has already added a stderr handler.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        "%H:%M:%S"))
    logger.addHandler(handler)
        
    logger.propagate = True
    if log_once(f"logger-init-{name}"):
        logger.info(f"[Logger Initialized] {name}")
    return logger

# Create the logger instance *before* the bad imports.
logger = get_seedcore_logger("seedcore.graph.embeddings")

# Now it is safe to import libraries that hijack logging.
from .loader import GraphLoader
from .gnn_models import SAGE

# --- [ END SOLUTION ] ---

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
        # Log actor creation with Ray actor info
        try:
            actor_id = ray.get_runtime_context().get_actor_id()
            actor_name = ray.get_runtime_context().get_actor_name()
            logger.info(f"🚀 GraphEmbedder actor created: ID={actor_id}, Name={actor_name}")
        except Exception as e:
            logger.debug("Could not get Ray actor context: %s", e)
        
        self.loader = GraphLoader()
        self.model = None
        self.in_feats = None
        logger.info("✅ GraphEmbedder initialized with GraphLoader")

    def _ensure_model(self, in_feats: int):
        if self.model is None or self.in_feats != in_feats:
            self.model = SAGE(in_feats=in_feats, h_feats=128, layers=2)
            self.in_feats = in_feats

    def ping(self) -> str:
        return "pong"

    def compute_embeddings(self, node_ids: List[int], k: int = 2) -> Dict[int, List[float]]:
        if not node_ids:
            logger.warning("GraphEmbedder.compute_embeddings: empty node_ids list")
            return {}

        logger.debug("GraphEmbedder.compute_embeddings: requesting embeddings for %d nodes (k=%d)", len(node_ids), k)
        
        try:
            g, idx_map, X = self.loader.load_k_hop(node_ids, k=k)
            logger.debug("GraphEmbedder.compute_embeddings: loaded graph with %d nodes, features shape=%s", 
                        getattr(g, 'num_nodes', lambda: 0)(), X.shape if X is not None else None)
        except ImportError as e:
            logger.error("DGL not available for GraphEmbedder: %s", e)
            return {}
        except Exception as e:
            logger.error("Failed to load k-hop graph: %s", e, exc_info=True)
            return {}

        if g is None:
            logger.warning("GraphEmbedder.compute_embeddings: graph is None")
            return {}
        
        num_nodes = getattr(g, 'num_nodes', lambda: 0)()
        if num_nodes == 0:
            logger.warning("GraphEmbedder.compute_embeddings: empty graph (num_nodes=0) for node_ids=%s", node_ids[:10])
            return {}
        
        if X is None or X.numel() == 0:
            logger.warning("GraphEmbedder.compute_embeddings: empty features tensor (X.shape=%s)", X.shape if X is not None else None)
            return {}

        logger.debug("GraphEmbedder.compute_embeddings: ensuring model with in_feats=%d", X.shape[1])
        self._ensure_model(X.shape[1])

        try:
            import torch
            with torch.no_grad():
                H = self.model(g, X)
                logger.debug("GraphEmbedder.compute_embeddings: SAGE forward produced H.shape=%s", H.shape)
        except Exception as e:
            logger.error("SAGE forward failed: %s", e, exc_info=True)
            return {}

        # invert idx_map to original node ids
        inv_map = {v: k for k, v in idx_map.items()}
        result = {int(inv_map[i]): H[i].tolist() for i in range(H.shape[0])}
        logger.debug("GraphEmbedder.compute_embeddings: returning %d embeddings", len(result))
        return result

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
        # Log actor creation with Ray actor info
        try:
            actor_id = ray.get_runtime_context().get_actor_id()
            actor_name = ray.get_runtime_context().get_actor_name()
            logger.info(f"🚀 NimRetrievalEmbedder actor created: ID={actor_id}, Name={actor_name}")
        except Exception as e:
            logger.debug("Could not get Ray actor context: %s", e)
        
        # Validate NIM configuration
        logger.info(f"🔍 NimRetrievalEmbedder config check: NIM_BASE_URL='{NIM_BASE_URL}', NIM_MODEL='{NIM_MODEL}'")
        
        self.model = NIM_MODEL
        self.url = EMBED_URL
        self.headers = HEADERS
        self.session = requests.Session()
        
        # Validate URL is not empty/malformed
        if not self.url or not self.url.startswith("http"):
            logger.error(f"❌ NimRetrievalEmbedder: Invalid EMBED_URL='{self.url}' (NIM_BASE_URL='{NIM_BASE_URL}'). Check NIM_RETRIEVAL_BASE_URL environment variable.")
            raise ValueError(f"Invalid NIM_RETRIEVAL_BASE_URL: '{NIM_BASE_URL}' results in malformed URL '{self.url}'")
        
        logger.info(f"✅ NimRetrievalEmbedder initialized: model={self.model}, url={self.url}")

    def ping(self) -> str:
        """Health check for NIM Retrieval service."""
        try:
            health_url = self.url.replace("/embeddings", "/health")
            logger.debug("NimRetrievalEmbedder.ping: checking health at %s", health_url)
            r = self.session.get(health_url, timeout=5)
            result = "ok" if r.status_code == 200 else f"fail:{r.status_code}"
            logger.debug("NimRetrievalEmbedder.ping: health check result: %s", result)
            return result
        except Exception as e:
            logger.warning("NimRetrievalEmbedder.ping: health check failed: %s", e)
            return f"error:{e}"

    def embed_texts(self, items: Dict[int, str]) -> Dict[int, List[float]]:
        """
        Send text batches to NIM Retrieval model for embedding.
        Input: {node_id: text}
        Output: {node_id: [float vector]}
        """
        if not items:
            logger.debug("NimRetrievalEmbedder.embed_texts: empty items list")
            return {}

        logger.debug("NimRetrievalEmbedder.embed_texts: requesting embeddings for %d nodes", len(items))
        t0 = time.time()
        
        payload = {
            "model": self.model,
            "input": list(items.values()),
            "input_type": "passage"  # Required for NVIDIA NIM asymmetric models like nv-embedqa-e5-v5
        }

        try:
            logger.debug("NimRetrievalEmbedder.embed_texts: calling NIM service at %s", self.url)
            resp = self.session.post(self.url, headers=self.headers, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            elapsed_ms = (time.time() - t0) * 1000

            if "data" not in data:
                logger.error("NimRetrievalEmbedder.embed_texts: invalid response from NIM (no 'data' key): %s", data)
                return {}

            vectors = [d["embedding"] for d in data["data"]]
            if len(vectors) != len(items):
                logger.warning("NimRetrievalEmbedder.embed_texts: vector count mismatch (%d received vs %d requested)", 
                              len(vectors), len(items))
            
            result = {nid: vec for nid, vec in zip(items.keys(), vectors)}
            logger.debug("NimRetrievalEmbedder.embed_texts: completed %d embeddings in %.2fms", 
                        len(result), elapsed_ms)
            return result

        except Exception as e:
            elapsed_ms = (time.time() - t0) * 1000
            logger.error("NimRetrievalEmbedder.embed_texts: request failed after %.2fms: %s", elapsed_ms, e, exc_info=True)
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
        # Convert list to JSON array string for pgvector CAST(:vec AS vector)
        vec_str = json.dumps(vec)
        rows.append({
            "nid": int(nid),
            "vec": vec_str,
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
            CAST(:vec AS vector),
            CASE WHEN :props IS NULL THEN NULL ELSE CAST(:props AS jsonb) END,
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
