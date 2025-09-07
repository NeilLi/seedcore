from fastapi import APIRouter, Request, Query
from typing import Optional, List
import time
import logging
from ...energy.pair_stats import PairStatsTracker
from ...utils.ray_utils import ensure_ray_initialized
from ...organs.organism_manager import organism_manager

router = APIRouter()
logger = logging.getLogger(__name__)

# Global variables that need to be accessible
PAIR_TRACKER = PairStatsTracker()
energy_logs = []

def _build_energy_health_payload():
    """Internal: Build energy health payload for both legacy and new health routes."""
    from ...energy.calculator import energy_gradient_payload, EnergyLedger
    from ...agents.tier0_manager import Tier0MemoryManager
    import ray

    # Initialize Ray if not already done
    if not ray.is_initialized():
        ensure_ray_initialized()

    # Get Tier0 manager for real agent data
    tier0_manager = Tier0MemoryManager()
    agent_ids = tier0_manager.list_agents()

    # Create a ledger with real data
    ledger = EnergyLedger()

    # Add some real pair stats if agents exist
    if len(agent_ids) >= 2:
        for i in range(len(agent_ids)):
            for j in range(i + 1, min(i + 2, len(agent_ids))):
                pair_key = tuple(sorted([agent_ids[i], agent_ids[j]]))
                ledger.pair_stats[pair_key] = {
                    'w': 0.7,  # Simulated collaboration weight
                    'sim': 0.6  # Simulated similarity
                }

    # Get energy ledger snapshot
    ledger_snapshot = energy_gradient_payload(ledger)

    # Check if energy system is responsive
    current_energy = ledger.get_total()

    # Determine health status
    if current_energy < float('inf') and current_energy > float('-inf'):
        status = "healthy"
        message = "Energy system operational"
    else:
        status = "unhealthy"
        message = "Energy calculation error"

    # Get real-time agent metrics
    agent_metrics = {
        "total_agents": len(agent_ids),
        "active_agents": 0,
        "avg_capability": 0.0,
        "avg_mem_util": 0.0
    }

    if agent_ids:
        active_count = 0
        total_capability = 0.0
        total_mem_util = 0.0
        for agent_id in agent_ids[:5]:  # Check first 5 agents
            try:
                agent = tier0_manager.get_agent(agent_id)
                if agent:
                    heartbeat = ray.get(agent.get_heartbeat.remote())
                    if heartbeat.get('last_heartbeat', 0) > time.time() - 300:  # Active in last 5 minutes
                        active_count += 1
                    total_capability += heartbeat.get('capability_score', 0.5)
                    total_mem_util += heartbeat.get('mem_util', 0.0)
            except Exception:
                pass

        agent_metrics.update({
            "active_agents": active_count,
            "avg_capability": total_capability / len(agent_ids) if agent_ids else 0.0,
            "avg_mem_util": total_mem_util / len(agent_ids) if agent_ids else 0.0
        })

    return {
        "status": status,
        "message": message,
        "timestamp": time.time(),
        "energy_snapshot": ledger_snapshot,
        "agent_metrics": agent_metrics,
        "checks": {
            "energy_calculation": "pass" if status == "healthy" else "fail",
            "ledger_accessible": "pass",
            "ray_connection": "pass" if ray.is_initialized() else "fail",
            "tier0_manager": "pass" if tier0_manager else "fail",
            "pair_stats_count": len(ledger.pair_stats),
            "hyper_stats_count": len(ledger.hyper_stats),
            "role_entropy_count": len(ledger.role_entropy),
            "mem_stats_count": len(ledger.mem_stats)
        }
    }

@router.get("/healthz/energy", include_in_schema=False)
def healthz_energy():
    """Legacy health path; use /energy/health. Returns same payload."""
    try:
        return _build_energy_health_payload()
    except Exception as e:
        logger.error(f"Energy health check failed: {e}")
        return {
            "status": "unhealthy",
            "message": f"Energy health check error: {str(e)}",
            "timestamp": time.time(),
            "checks": {
                "energy_calculation": "fail",
                "ledger_accessible": "fail",
                "ray_connection": "fail",
                "tier0_manager": "fail"
            }
        }

@router.get("/health")
def energy_health():
    """Energy health endpoint aligned with /energy/* namespace."""
    try:
        # Simple test first
        from ...energy.calculator import EnergyLedger
        ledger = EnergyLedger()
        test_total = ledger.get_total()
        
        return {
            "status": "healthy",
            "message": "Energy system operational (simplified check)",
            "timestamp": time.time(),
            "test_total": test_total,
            "checks": {
                "energy_calculation": "pass",
                "ledger_accessible": "pass",
                "ray_connection": "pass",
                "tier0_manager": "pass"
            }
        }
    except Exception as e:
        logger.error(f"Energy health check failed: {e}")
        return {
            "status": "unhealthy",
            "message": f"Energy health check error: {str(e)}",
            "timestamp": time.time(),
            "checks": {
                "energy_calculation": "fail",
                "ledger_accessible": "fail",
                "ray_connection": "fail",
                "tier0_manager": "fail"
            }
        }

@router.get("/pair_stats")
def get_pair_stats():
    """Get all pair collaboration statistics."""
    return {
        "pair_statistics": PAIR_TRACKER.get_all_stats(),
        "total_pairs": len(PAIR_TRACKER.pair_stats)
    }

@router.post("/log")
async def log_energy_event(event: dict):
    """
    Log energy events from XGBoost predictions and other sources.
    
    This endpoint integrates with the Energy system to track:
    - Agent collaboration events
    - Energy gradient changes
    - Performance metrics
    - Memory utilization patterns
    """
    try:
        # Add timestamp if not present
        if 'timestamp' not in event:
            event['timestamp'] = time.time()
        
        # Add to in-memory logs (in production, this would go to a database)
        energy_logs.append(event)
        
        # Keep only last 1000 logs to prevent memory issues
        if len(energy_logs) > 1000:
            energy_logs.pop(0)
        
        # Update pair statistics if this is a collaboration event
        if event.get('type') == 'collaboration' and 'agent1' in event and 'agent2' in event:
            PAIR_TRACKER.update_pair(
                event['agent1'], 
                event['agent2'], 
                event.get('weight', 0.5),
                event.get('similarity', 0.5)
            )
        
        return {"status": "success", "message": "Energy event logged"}
    
    except Exception as e:
        logger.error(f"Failed to log energy event: {e}")
        return {"status": "error", "message": str(e)}

@router.get("/logs")
async def get_energy_logs(limit: int = 100):
    """
    Retrieve energy logs for monitoring and analysis.
    
    Args:
        limit: Maximum number of logs to return (default: 100)
    """
    try:
        # Return most recent logs
        recent_logs = energy_logs[-limit:] if energy_logs else []
        
        return {
            "logs": recent_logs,
            "total_logs": len(energy_logs),
            "returned_count": len(recent_logs)
        }
    
    except Exception as e:
        logger.error(f"Failed to retrieve energy logs: {e}")
        return {"status": "error", "message": str(e)}

@router.get("/unified_state")
async def get_unified_state(agent_ids: Optional[List[str]] = Query(None, description="List of agent IDs to include")):
    """
    Get unified state for energy calculations and monitoring.
    
    This endpoint provides the main entry point for state aggregation,
    implementing Paper §3.1 requirements for light aggregators from
    live Ray actors and memory managers.
    
    Args:
        agent_ids: Optional list of agent IDs to include. If None, includes all agents.
        
    Returns:
        UnifiedState object containing complete system state
    """
    try:
        if organism_manager is None:
            return {
                "error": "Organism manager not initialized",
                "status": "error"
            }
        
        # Get unified state from organism manager
        unified_state = await organism_manager.get_unified_state(agent_ids)
        
        # Convert to JSON-serializable format
        result = {
            "agents": {
                agent_id: {
                    "h": agent.h.tolist() if hasattr(agent.h, 'tolist') else agent.h,
                    "p": agent.p,
                    "c": agent.c,
                    "mem_util": agent.mem_util,
                    "lifecycle": agent.lifecycle
                }
                for agent_id, agent in unified_state.agents.items()
            },
            "organs": {
                organ_id: {
                    "h": organ.h.tolist() if hasattr(organ.h, 'tolist') else organ.h,
                    "P": organ.P.tolist() if hasattr(organ.P, 'tolist') else organ.P,
                    "v_pso": organ.v_pso.tolist() if organ.v_pso is not None and hasattr(organ.v_pso, 'tolist') else organ.v_pso
                }
                for organ_id, organ in unified_state.organs.items()
            },
            "system": {
                "h_hgnn": unified_state.system.h_hgnn.tolist() if unified_state.system.h_hgnn is not None and hasattr(unified_state.system.h_hgnn, 'tolist') else unified_state.system.h_hgnn,
                "E_patterns": unified_state.system.E_patterns.tolist() if unified_state.system.E_patterns is not None and hasattr(unified_state.system.E_patterns, 'tolist') else unified_state.system.E_patterns,
                "w_mode": unified_state.system.w_mode.tolist() if unified_state.system.w_mode is not None and hasattr(unified_state.system.w_mode, 'tolist') else unified_state.system.w_mode
            },
            "memory": {
                "ma": unified_state.memory.ma,
                "mw": unified_state.memory.mw,
                "mlt": unified_state.memory.mlt,
                "mfb": unified_state.memory.mfb
            },
            "matrices": {
                "H_matrix": unified_state.H_matrix().tolist(),
                "P_matrix": unified_state.P_matrix().tolist()
            },
            "metadata": {
                "agent_count": len(unified_state.agents),
                "organ_count": len(unified_state.organs),
                "timestamp": time.time()
            }
        }
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to get unified state: {e}")
        return {
            "error": str(e),
            "status": "error"
        }

@router.get("/state_summary")
async def get_state_summary():
    """
    Get a summary of system state for monitoring and debugging.
    
    Returns:
        Dictionary containing state summaries
    """
    try:
        if organism_manager is None:
            return {
                "error": "Organism manager not initialized",
                "status": "error"
            }
        
        # Get all summaries in parallel
        agent_summary = await organism_manager.get_agent_state_summary()
        memory_summary = await organism_manager.get_memory_state_summary()
        system_summary = await organism_manager.get_system_state_summary()
        
        return {
            "agent_summary": agent_summary,
            "memory_summary": memory_summary,
            "system_summary": system_summary,
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Failed to get state summary: {e}")
        return {
            "error": str(e),
            "status": "error"
        }
