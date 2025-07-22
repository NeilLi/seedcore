import numpy as np
import time
from seedcore.memory.holon_fabric import Holon
from seedcore.memory.backends.pgvector_backend import Holon as HolonModel
from seedcore.memory.backends.pgvector_backend import PgVectorStore
from seedcore.memory.backends.neo4j_graph import Neo4jGraph
from seedcore.memory.holon_fabric import HolonFabric
from seedcore.memory.consolidation_worker import vq_vae_compress
from seedcore.telemetry.metrics import COSTVQ, MEM_WRITES, ENERGY_SLOPE

previous_cost_vq = 0.0

async def consolidate_batch(fabric, mw: dict, tau: float, batch: int = 128, kappa: float = 0.5, redis=None) -> int:
    """
    Adaptive consolidation loop:
    - TD-priority sampling (kappa)
    - Error-gated VQ-VAE (tau)
    - Optional shadow-KV debug text (if redis provided)
    """
    global previous_cost_vq
    now = time.time()
    # TD-priority: p = kappa*TD_error + (1-kappa)*age_secs
    def priority(kv):
        td = kv[1].get('td', 0)
        age = now - kv[1]['ts']
        return -(kappa * td + (1 - kappa) * age)
    items = sorted(mw.items(), key=priority)[:batch]
    cost_vq = previous_cost_vq  # Default if no items processed
    n_written = 0
    for k, payload in items:
        blob = payload["blob"]
        z, recon, _ = vq_vae_compress(blob, tau)
        # Error-gated: only write if normalized error <= tau
        err = np.linalg.norm(blob - recon) / max(np.linalg.norm(blob), 1)
        if err > tau:
            # Optionally, could push back into Mw or increment a retry count
            continue
        bytes_raw = len(blob)
        bytes_stored = len(z) if hasattr(z, '__len__') else 0
        h = Holon(
            embedding=z,
            meta={
                "raw_bytes": bytes_raw,
                "stored_bytes": bytes_stored,
                "ts": payload["ts"],
                "err": err,
            }
        )
        await fabric.insert_holon(h)
        cost_vq = bytes_stored / bytes_raw if bytes_raw else 0.0
        COSTVQ.set(cost_vq)
        MEM_WRITES.labels(tier="Mlt").inc()
        fabric.graph.upsert_edge(
            src_uuid=h.uuid,
            rel="DERIVED_FROM",
            dst_uuid=payload.get("src_uuid", h.uuid)
        )
        mw.pop(k, None)
        n_written += 1
        # Shadow-KV debug text (optional, if redis provided)
        if redis and 'text' in payload:
            await redis.lpush('debug:holons', payload['text'][:200])
            await redis.ltrim('debug:holons', 0, 999)
    # After batch, update energy slope
    slope = previous_cost_vq - cost_vq
    ENERGY_SLOPE.set(slope)
    previous_cost_vq = cost_vq
    return n_written 