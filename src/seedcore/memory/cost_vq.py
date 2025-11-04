# Copyright 2024 SeedCore Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
CostVQ estimator: proxy cost for compression vs fidelity trade (Section 7, 3.x.4).

This module provides the high-level async function `calculate_cost_vq`
to orchestrate metric gathering and cost calculation.
"""

import asyncio
import logging
from typing import Dict, Any, Optional

# --- Import the manager clients ---
from .mw_manager import MwManager
from .holon_fabric import HolonFabric

logger = logging.getLogger(__name__)

# --- Default Cost Weights ---
# These can be tuned externally and passed in
DEFAULT_WEIGHTS = {
    'w_b': 1.0,  # Weight for storage cost (bytes)
    'w_r': 1.0,  # Weight for information quality (reconstruction loss)
    'w_s': 0.5   # Weight for data freshness (staleness)
}

# --- Low-level math function (your original stub) ---

def _compute_cost_math(bytes_cost: float, recon_loss: float, staleness: float,
                       w_b: float, w_r: float, w_s: float) -> float:
    """
    Applies the weighted sum for the final cost.
    (This is the original stub's logic).
    """
    return (w_b * bytes_cost) + (w_r * recon_loss) + (w_s * staleness)

# --- Legacy sync function for backward compatibility ---

def cost_vq(bytes_used: int, recon_loss: float, stale_s: float,
            w_b=1.0, w_r=1.0, w_s=0.5) -> float:
    """
    Legacy synchronous function for backward compatibility.
    
    This is the original stub function. Use calculate_cost_vq() for the
    full async implementation that gathers metrics from distributed services.
    """
    # Normalize bytes_used to match the async version's bytes_cost calculation
    bytes_cost = bytes_used / (1024**3)  # Normalize to GB
    return _compute_cost_math(bytes_cost, recon_loss, stale_s, w_b, w_r, w_s)

# --- High-level Async Estimator ---

async def calculate_cost_vq(
    mw_manager: MwManager,
    fabric: HolonFabric,
    compression_knob: float,
    weights: Optional[Dict[str, float]] = None
) -> Dict[str, Any]:
    """
    Calculates the full CostVQ by querying distributed services asynchronously.
    
    Args:
        mw_manager: The client for the working memory (Mw) cache cluster.
        fabric: The client for the long-term memory (Mlt) fabric.
        compression_knob: The current compression setting (0.0=max compress, 1.0=min compress).
        weights: Optional dictionary to override default cost weights.

    Returns:
        A dictionary containing the final cost_vq and all its components.
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS
    
    w_b = weights.get('w_b', DEFAULT_WEIGHTS['w_b'])
    w_r = weights.get('w_r', DEFAULT_WEIGHTS['w_r'])
    w_s = weights.get('w_s', DEFAULT_WEIGHTS['w_s'])
    
    try:
        # 1. Fetch metrics from all services in parallel
        mw_stats_task = mw_manager.get_cluster_stats()
        mlt_stats_task = fabric.get_stats()
        mw_stats, mlt_stats = await asyncio.gather(mw_stats_task, mlt_stats_task)

        # 2. Calculate individual cost components
        
        # BYTES COST: Normalize total bytes used (e.g., cost is 1.0 per GB)
        bytes_used_mw = mw_stats.get('bytes_used', 0)
        bytes_used_mlt = mlt_stats.get('bytes_used', 0)
        total_bytes = bytes_used_mw + bytes_used_mlt
        bytes_cost = total_bytes / (1024**3)  # Normalize to GB

        # RECONSTRUCTION LOSS: Inversely proportional to the compression knob.
        # knob=1.0 (low compress) -> recon_loss=0.0
        # knob=0.0 (high compress) -> recon_loss=1.0
        recon_loss = 1.0 - compression_knob

        # STALENESS: Based on cluster-wide cache hit rate.
        # Low hit rate -> high staleness
        total_hits = mw_stats.get('hit_count', 0)
        total_items_mw = mw_stats.get('total_items', 0)
        total_items_mlt = mlt_stats.get('total_holons', 0)
        total_data_points = total_items_mw + total_items_mlt
        
        if total_data_points > 0:
            hit_rate = total_hits / total_data_points
            staleness = 1.0 - hit_rate  # 1.0 = 100% stale (0% hits)
        else:
            hit_rate = 1.0  # No data, so 100% "hits" (no misses)
            staleness = 0.0

        # 3. Compute final weighted cost
        cost_vq_value = _compute_cost_math(
            bytes_cost, recon_loss, staleness, w_b, w_r, w_s
        )

        return {
            'cost_vq': cost_vq_value,
            'components': {
                'bytes_cost': bytes_cost,
                'recon_loss': recon_loss,
                'staleness': staleness,
            },
            'raw_metrics': {
                'total_bytes': total_bytes,
                'hit_rate': hit_rate,
                'total_hits': total_hits,
                'total_items': total_data_points,
                'compression_knob': compression_knob,
            },
            'weights': {'w_b': w_b, 'w_r': w_r, 'w_s': w_s}
        }

    except Exception as e:
        logger.error(f"Failed to calculate CostVQ: {e}", exc_info=True)
        return {
            'cost_vq': float('inf'), # Return infinite cost on error to signal failure
            'error': str(e)
        }
