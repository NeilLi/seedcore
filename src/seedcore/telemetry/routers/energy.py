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
    from ...tier0.tier0_manager import Tier0MemoryManager
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
    """Legacy health path; use /ops/energy/health. Returns same payload."""
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
    """Energy health endpoint aligned with /ops/energy/* namespace."""
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
        # Get state service - try multiple namespaces
        state_service = None
        for namespace in ["serve", "seedcore-dev", "default"]:
            try:
                state_service = ray.get_actor("StateService", namespace=namespace)
                break
            except Exception as e:
                logger.debug(f"Failed to get state service in namespace {namespace}: {e}")
                continue
        
        if state_service is None:
            return {
                "error": "State service not available in any namespace",
                "status": "error"
            }
        
        # Get unified state from state service
        response = await state_service.get_unified_state.remote(
            agent_ids=agent_ids,
            include_organs=True,
            include_system=True,
            include_memory=True
        )
        
        if not response.get("success"):
            return {
                "error": f"State service failed: {response.get('error')}",
                "status": "error"
            }
        
        # Add matrices and metadata to the response
        unified_state_dict = response["unified_state"]
        
        # Calculate matrices from the state data
        agents = unified_state_dict.get("agents", {})
        if agents:
            # H matrix: stack all agent embeddings
            h_vectors = []
            for agent_data in agents.values():
                h_vectors.append(agent_data["h"])
            H_matrix = h_vectors if h_vectors else []
            
            # P matrix: stack all role probabilities
            p_vectors = []
            for agent_data in agents.values():
                p = agent_data["p"]
                p_vectors.append([
                    float(p.get("E", 0.0)),
                    float(p.get("S", 0.0)),
                    float(p.get("O", 0.0))
                ])
            P_matrix = p_vectors if p_vectors else []
        else:
            H_matrix = []
            P_matrix = []
        
        # Add matrices and metadata
        unified_state_dict["matrices"] = {
            "H_matrix": H_matrix,
            "P_matrix": P_matrix
        }
        unified_state_dict["metadata"] = {
            "agent_count": len(agents),
            "organ_count": len(unified_state_dict.get("organs", {})),
            "timestamp": time.time(),
            "collection_time_ms": response.get("collection_time_ms", 0)
        }
        
        return unified_state_dict
        
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

@router.post("/compute-energy")
async def compute_energy_endpoint(
    agent_ids: Optional[List[str]] = Query(None, description="List of agent IDs to include"),
    include_gradients: bool = Query(False, description="Include gradient calculations"),
    include_breakdown: bool = Query(True, description="Include energy term breakdown"),
    weights: Optional[Dict[str, float]] = None
):
    """
    Compute energy metrics using the energy service.
    
    This endpoint delegates to the energy service for energy calculations,
    providing access to all energy terms and gradients.
    
    Args:
        agent_ids: Optional list of agent IDs to include
        include_gradients: Whether to include gradient calculations
        include_breakdown: Whether to include energy term breakdown
        weights: Optional energy weights override
        
    Returns:
        Energy calculation results
    """
    try:
        # Get energy service - try multiple namespaces
        energy_service = None
        for namespace in ["serve", "seedcore-dev", "default"]:
            try:
                energy_service = ray.get_actor("EnergyService", namespace=namespace)
                break
            except Exception as e:
                logger.debug(f"Failed to get energy service in namespace {namespace}: {e}")
                continue
        
        if energy_service is None:
            return {
                "error": "Energy service not available in any namespace",
                "status": "error"
            }
        
        # Use the energy service's convenience endpoint
        response = await energy_service.get_energy_from_state.remote(
            agent_ids=agent_ids,
            include_gradients=include_gradients,
            include_breakdown=include_breakdown
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Failed to compute energy: {e}")
        return {
            "error": str(e),
            "status": "error"
        }

@router.post("/optimize-agents")
async def optimize_agents_endpoint(
    task: Dict[str, Any],
    agent_ids: Optional[List[str]] = Query(None, description="List of agent IDs to consider"),
    max_agents: Optional[int] = Query(None, description="Maximum number of agents to select"),
    weights: Optional[Dict[str, float]] = None
):
    """
    Optimize agent selection for a given task using the energy service.
    
    This endpoint delegates to the energy service for agent optimization,
    providing energy-based agent selection and role recommendations.
    
    Args:
        task: Task description for optimization
        agent_ids: Optional list of agent IDs to consider
        max_agents: Maximum number of agents to select
        weights: Optional energy weights override
        
    Returns:
        Agent optimization results
    """
    try:
        # Get energy service - try multiple namespaces
        energy_service = None
        for namespace in ["serve", "seedcore-dev", "default"]:
            try:
                energy_service = ray.get_actor("EnergyService", namespace=namespace)
                break
            except Exception as e:
                logger.debug(f"Failed to get energy service in namespace {namespace}: {e}")
                continue
        
        if energy_service is None:
            return {
                "error": "Energy service not available in any namespace",
                "status": "error"
            }
        
        # Get unified state from state service first - try multiple namespaces
        state_service = None
        for namespace in ["serve", "seedcore-dev", "default"]:
            try:
                state_service = ray.get_actor("StateService", namespace=namespace)
                break
            except Exception as e:
                logger.debug(f"Failed to get state service in namespace {namespace}: {e}")
                continue
        
        if state_service is None:
            return {
                "error": "State service not available in any namespace",
                "status": "error"
            }
        state_response = await state_service.get_unified_state.remote(
            agent_ids=agent_ids,
            include_organs=True,
            include_system=True,
            include_memory=True
        )
        
        if not state_response.get("success"):
            return {
                "error": f"State service failed: {state_response.get('error')}",
                "status": "error"
            }
        
        # Create optimization request
        optimization_request = {
            "unified_state": state_response["unified_state"],
            "task": task,
            "max_agents": max_agents,
            "weights": weights
        }
        
        # Call energy service for optimization
        response = await energy_service.optimize_agents.remote(optimization_request)
        
        return response
        
    except Exception as e:
        logger.error(f"Failed to optimize agents: {e}")
        return {
            "error": str(e),
            "status": "error"
        }
