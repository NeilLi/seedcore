from fastapi import APIRouter
import time
import logging
from ...utils.ray_utils import ensure_ray_initialized

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/status")
def system_status():
    """Returns the current status of the persistent system with real data."""
    try:
        from ...energy.calculator import energy_gradient_payload, EnergyLedger
        from ...tier0.tier0_manager import Tier0MemoryManager
        import ray
        
        # Initialize Ray if not already done
        if not ray.is_initialized():
            ensure_ray_initialized()
        
        # Get Tier0 manager for real agent data
        tier0_manager = Tier0MemoryManager()
        agent_ids = tier0_manager.list_agents()
        
        # Get real energy state
        try:
            energy_state = energy_gradient_payload(EnergyLedger())
        except Exception:
            energy_state = {"error": "Energy calculation failed"}
        
        # Get real agent statistics
        agent_stats = []
        if agent_ids:
            for agent_id in agent_ids[:10]:  # Limit to first 10 agents
                try:
                    agent = tier0_manager.get_agent(agent_id)
                    if agent:
                        heartbeat = ray.get(agent.get_heartbeat.remote())
                        agent_stats.append({
                            "agent_id": agent_id,
                            "capability_score": heartbeat.get('capability_score', 0.5),
                            "mem_util": heartbeat.get('mem_util', 0.0),
                            "tasks_processed": heartbeat.get('tasks_processed', 0),
                            "success_rate": heartbeat.get('success_rate', 0.0),
                            "role_probs": heartbeat.get('role_probs', {}),
                            "last_heartbeat": heartbeat.get('last_heartbeat', time.time())
                        })
                except Exception as e:
                    logger.warning(f"Failed to get stats for agent {agent_id}: {e}")
        
        return {
            "system_info": {
                "timestamp": time.time(),
                "version": "1.0.0",
                "status": "operational"
            },
            "agents": {
                "tier0_agents": len(agent_ids),
                "total_agents": len(agent_ids),
                "agent_details": agent_stats
            },
            "energy_system": {
                "energy_state": energy_state
            },
            "performance_metrics": {
                "active_agents": len([a for a in agent_stats if a.get('last_heartbeat', 0) > time.time() - 300])  # Active in last 5 minutes
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        return {
            "error": str(e),
            "timestamp": time.time(),
            "status": "error",
            "agents": {"total_agents": 0},
            "energy_system": {"energy_state": {"error": "Calculation failed"}},
            "performance_metrics": {}
        }
