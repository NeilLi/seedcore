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
Energy API Router - Real-time energy gradient telemetry endpoint.
Implements the /energy/gradient endpoint described in the energy validation blueprint.
"""

import time
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from collections import deque
import numpy as np

from ...energy.api import _ledger
from ...energy.calculator import energy_gradient_payload
from ...memory.adaptive_loop import get_memory_system

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/energy", tags=["energy"])

# Global energy history tracking
energy_history = {
    "pair": deque(maxlen=1000),
    "hyper": deque(maxlen=1000),
    "entropy": deque(maxlen=1000),
    "reg": deque(maxlen=1000),
    "mem": deque(maxlen=1000),
    "total": deque(maxlen=1000)
}

def calculate_slope(values: deque, window: int = 100) -> float:
    """Calculate slope of recent values using linear regression."""
    if len(values) < window:
        return 0.0
    
    recent_values = list(values)[-window:]
    x = np.arange(len(recent_values))
    
    if len(recent_values) < 2:
        return 0.0
    
    try:
        slope, _ = np.polyfit(x, recent_values, 1)
        return float(slope)
    except (ValueError, np.linalg.LinAlgError):
        return 0.0

def update_energy_history():
    """Update energy history with current values."""
    current_energy = _ledger.read_energy()
    
    for term in energy_history:
        if term in current_energy:
            energy_history[term].append(current_energy[term])

@router.get("/gradient")
def get_energy_gradient():
    """
    Exposes a JSON breakdown of the energy budget in real time.
    This payload is specified in the COA design blueprint.
    """
    try:
        # Update energy history
        update_energy_history()
        
        # Get current energy values
        current_energy = _ledger.read_energy()
        
        # Calculate slope from history
        window_size = 100
        recent_energy = _ledger.get_recent_energy(window=window_size)
        total_history = recent_energy.get("total", [])
        slope = 0.0
        if len(total_history) > 1:
            # Simplified slope calculation; use np.polyfit for production
            slope = (total_history[-1] - total_history[0]) / len(total_history)

        # Calculate last delta (difference from previous total)
        last_delta = 0.0
        if len(energy_history["total"]) >= 2:
            last_delta = energy_history["total"][-1] - energy_history["total"][-2]

        return {
            "ts": int(time.time()),
            "E_terms": { # Current total values for each term
                "pair": current_energy.get("pair", 0),
                "hyper": current_energy.get("hyper", 0),
                "entropy": current_energy.get("entropy", 0),
                "reg": current_energy.get("reg", 0),
                "mem": current_energy.get("mem", 0),
                "total": current_energy.get("total", 0)
            },
            "deltaE_last": last_delta,
            "window": {
                "W": window_size,
                "slope": slope
            },
            "mem_pressure": { # Get these stats from your memory module
                "Mw": 0.62, # Example value - should be replaced with actual memory stats
                "Mlt": 0.41 # Example value - should be replaced with actual memory stats
            }
        }
        
    except Exception as e:
        logger.error(f"Error in energy gradient endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Energy gradient calculation failed: {str(e)}")

@router.get("/current")
async def get_current_energy() -> Dict[str, float]:
    """
    Get current energy values without slopes or history.
    
    Returns:
        Current energy terms and total.
    """
    try:
        return _ledger.read_energy()
    except Exception as e:
        logger.error(f"Error getting current energy: {e}")
        raise HTTPException(status_code=500, detail=f"Energy calculation failed: {str(e)}")

@router.get("/history/{term}")
async def get_energy_history(term: str, limit: int = 100) -> Dict[str, Any]:
    """
    Get energy history for a specific term.
    
    Args:
        term: Energy term to get history for (pair, hyper, entropy, reg, mem, total)
        limit: Maximum number of history points to return
    
    Returns:
        History data for the specified term.
    """
    if term not in energy_history:
        raise HTTPException(status_code=400, detail=f"Invalid energy term: {term}")
    
    try:
        history_list = list(energy_history[term])
        if limit > 0:
            history_list = history_list[-limit:]
        
        return {
            "term": term,
            "history": history_list,
            "count": len(history_list),
            "slope": calculate_slope(energy_history[term])
        }
    except Exception as e:
        logger.error(f"Error getting energy history for {term}: {e}")
        raise HTTPException(status_code=500, detail=f"History retrieval failed: {str(e)}")

@router.get("/stats")
async def get_energy_stats() -> Dict[str, Any]:
    """
    Get energy statistics and validation metrics.
    
    Returns:
        Energy statistics including slopes, ratios, and validation metrics.
    """
    try:
        current_energy = _ledger.read_energy()
        total = current_energy.get('total', 0)
        
        # Calculate ratios
        ratios = {}
        if total != 0:
            for term in ['pair', 'hyper', 'entropy', 'reg', 'mem']:
                if term in current_energy:
                    ratios[f"{term}_ratio"] = abs(current_energy[term] / total)
        
        # Calculate slopes
        slopes = {}
        for term in ["pair", "hyper", "entropy", "reg", "mem"]:
            if term in energy_history:
                slopes[f"{term}_slope"] = calculate_slope(energy_history[term])
        
        # Validation metrics
        validation_metrics = {
            "reg_dominance": ratios.get('reg_ratio', 0) > 0.25,  # Should be < 25%
            "total_energy_positive": total > 0,
            "pair_energy_negative": current_energy.get('pair', 0) < 0,  # Should be negative
            "entropy_energy_negative": current_energy.get('entropy', 0) < 0,  # Should be negative
        }
        
        return {
            "current_values": current_energy,
            "ratios": ratios,
            "slopes": slopes,
            "validation": validation_metrics,
            "history_lengths": {
                term: len(history) for term, history in energy_history.items()
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting energy stats: {e}")
        raise HTTPException(status_code=500, detail=f"Stats calculation failed: {str(e)}")

@router.post("/reset")
async def reset_energy_ledger() -> Dict[str, str]:
    """
    Reset the energy ledger and history.
    
    Returns:
        Confirmation message.
    """
    try:
        _ledger.reset()
        
        # Clear history
        for history in energy_history.values():
            history.clear()
        
        logger.info("Energy ledger and history reset")
        return {"message": "Energy ledger and history reset successfully"}
        
    except Exception as e:
        logger.error(f"Error resetting energy ledger: {e}")
        raise HTTPException(status_code=500, detail=f"Reset failed: {str(e)}") 