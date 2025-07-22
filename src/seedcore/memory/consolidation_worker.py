import ray
import numpy as np
import random
from typing import Dict, Any
from .holon_fabric import HolonFabric
from .backends.pgvector_backend import Holon
import asyncio
import uuid

def sample_by_age(mw: dict, batch: int) -> list:
    """Priority sample from Mw based on age"""
    items = list(mw.items())
    sampled = []
    for _ in range(min(batch, len(items))):
        if items:
            item = random.choice(items)
            items.remove(item)
            sampled.append({
                "src_uuid": item[0],
                "blob": item[1]
            })
    return sampled

def vq_vae_compress(blob: np.ndarray, τ: float) -> tuple:
    """Simple VQ-VAE compression simulation"""
    # Simple compression by reducing dimensionality
    if isinstance(blob, np.ndarray):
        original_shape = blob.shape
        compressed_size = max(1, int(np.prod(original_shape) * τ))
        
        # Flatten and compress
        flattened = blob.flatten()
        if len(flattened) > compressed_size:
            indices = np.linspace(0, len(flattened)-1, compressed_size, dtype=int)
            z = flattened[indices]
        else:
            z = flattened
        
        # Pad or truncate to 768 dimensions
        if len(z) < 768:
            z = np.pad(z, (0, 768 - len(z)), mode='constant')
        else:
            z = z[:768]
        
        # Simulate reconstruction
        recon = np.zeros_like(blob)
        loss = np.mean((blob - recon) ** 2)
        
        return z, recon, loss
    else:
        # If blob is not an array, create a random embedding
        z = np.random.randn(768).astype(np.float32) * τ
        recon = np.zeros_like(z)
        loss = 0.1
        return z, recon, loss

async def consolidate_batch(fabric: HolonFabric, mw: dict,
                               τ: float, batch: int = 128):
    # 1) priority sample Mw
    items = sample_by_age(mw, batch)
    num_written = 0
    for x in items:
        z, recon, loss = vq_vae_compress(x["blob"], τ)
        meta = {"recon": recon.tolist() if hasattr(recon, 'tolist') else recon}
        h = Holon(uuid=str(uuid.uuid4()), embedding=z, meta=meta)
        await fabric.insert_holon(h)
        fabric.graph.upsert_edge(
            src_uuid=h.uuid, rel="DERIVED_FROM", dst_uuid=x["src_uuid"]
        )
        num_written += 1
    return num_written

import ray
@ray.remote
def consolidation_worker(fabric: HolonFabric, mw: dict,
                               τ: float, batch: int = 128):
    # Ray sees a *sync* function, we run the async body inside it
    return asyncio.run(consolidate_batch(fabric, mw, τ, batch)) 