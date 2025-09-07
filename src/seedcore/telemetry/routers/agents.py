from fastapi import APIRouter
import time
import logging
from typing import Dict
from ...utils.ray_utils import ensure_ray_initialized

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/state")
def get_agents_state() -> Dict:
    """Returns the current state of all agents in the simulation with real data."""
    try:
        from ...agents import tier0_manager
        import ray
        
        # Ensure Ray connection (idempotent)
        if not ray.is_initialized():
            ensure_ray_initialized()
        
        all_agents = []

        # Only report Tier 0 agents for consistency
        agent_ids = tier0_manager.list_agents()

        for agent_id in agent_ids:
            try:
                agent = tier0_manager.get_agent(agent_id)
                if agent:
                    heartbeat = ray.get(agent.get_heartbeat.remote())
                    summary = ray.get(agent.get_summary_stats.remote())

                    all_agents.append({
                        "id": agent_id,
                        "type": "tier0_ray_agent",
                        "capability": heartbeat.get('capability_score', 0.5),
                        "mem_util": heartbeat.get('mem_util', 0.0),
                        "role_probs": heartbeat.get('role_probs', {}),
                        "state_embedding": ray.get(agent.get_state_embedding.remote()).tolist(),
                        "memory_writes": summary.get('memory_writes', 0),
                        "memory_hits_on_writes": summary.get('memory_hits_on_writes', 0),
                        "salient_events_logged": summary.get('salient_events_logged', 0),
                        "total_compression_gain": summary.get('total_compression_gain', 0.0),
                        "tasks_processed": summary.get('tasks_processed', 0),
                        "success_rate": summary.get('success_rate', 0.0),
                        "avg_quality": summary.get('avg_quality', 0.0),
                        "peer_interactions": summary.get('peer_interactions_count', 0),
                        "last_heartbeat": heartbeat.get('last_heartbeat', time.time()),
                        "energy_state": heartbeat.get('energy_state', {}),
                        "created_at": heartbeat.get('created_at', time.time())
                    })
            except Exception as e:
                logger.warning(f"Failed to get state for Tier0 agent {agent_id}: {e}")
                all_agents.append({
                    "id": agent_id,
                    "type": "tier0_ray_agent",
                    "error": str(e),
                    "status": "unavailable"
                })
        
        return {
            "agents": all_agents,
            "summary": {
                "total_agents": len(all_agents),
                "tier0_agents": len([a for a in all_agents if a.get('type') == 'tier0_ray_agent']),
                "legacy_agents": 0,
                "active_agents": len([a for a in all_agents if a.get('last_heartbeat', 0) > time.time() - 300]),
                "timestamp": time.time()
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting agents state: {e}")
        return {
            "error": str(e),
            "agents": [],
            "summary": {
                "total_agents": 0,
                "tier0_agents": 0,
                "legacy_agents": 0,
                "active_agents": 0,
                "timestamp": time.time()
            }
        }

# Backward-compat alias, hidden from schema
@router.get("/agents/state", include_in_schema=False)
def get_agents_state_legacy_alias() -> Dict:
    return get_agents_state()

# Tier0 specific endpoint
@router.get("/tier0/agents/state")
def get_tier0_agents_state() -> Dict:
    """Returns the current state of all Tier0 agents in the simulation with real data."""
    return get_agents_state()
