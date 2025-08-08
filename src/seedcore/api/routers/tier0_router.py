from typing import Dict, Any
import time
import ray
from fastapi import APIRouter

from ...agents import Tier0MemoryManager, tier0_manager


router = APIRouter()


@router.get("/tier0/agents/state")
def get_tier0_agents_state() -> Dict[str, Any]:
    try:
        # Initialize Ray if needed
        if not ray.is_initialized():
            ray.init(address="auto", ignore_reinit_error=True)

        all_agents = []

        manager = Tier0MemoryManager()
        agent_ids = manager.list_agents()

        for agent_id in agent_ids:
            try:
                agent = manager.get_agent(agent_id)
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
                # Record failure but keep the list consistent
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


# Hidden backward-compatible alias
@router.get('/agents/state', include_in_schema=False)
def get_agents_state_legacy_alias() -> Dict[str, Any]:
    return get_tier0_agents_state()


@router.post("/tier0/agents/create")
async def create_ray_agent(request: Dict[str, Any]):
    try:
        agent_id = request.get('agent_id')
        role_probs = request.get('role_probs')

        if not agent_id:
            return {"success": False, "message": "agent_id is required"}

        created_id = tier0_manager.create_agent(agent_id, role_probs)
        return {"success": True, "agent_id": created_id, "message": f"Agent {created_id} created"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/tier0/agents/create_batch")
async def create_ray_agents_batch(request: Dict[str, Any]):
    try:
        agent_configs = request.get('agent_configs', [])

        if not agent_configs:
            return {"success": False, "message": "agent_configs list is required"}

        created_ids = tier0_manager.create_agents_batch(agent_configs)
        return {"success": True, "agent_ids": created_ids, "message": f"Created {len(created_ids)} agents"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/tier0/agents")
async def list_ray_agents():
    try:
        agents = tier0_manager.list_agents()
        return {"success": True, "agents": agents, "count": len(agents)}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/tier0/agents/{agent_id}/execute")
async def execute_task_on_agent(agent_id: str, request: Dict[str, Any]):
    try:
        task_data = request.get('task_data', {})
        result = tier0_manager.execute_task_on_agent(agent_id, task_data)

        if result:
            return {"success": True, "result": result}
        else:
            return {"success": False, "message": f"Agent {agent_id} not found or task failed"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/tier0/agents/execute_random")
async def execute_task_on_random_agent(request: Dict[str, Any]):
    try:
        task_data = request.get('task_data', {})
        result = tier0_manager.execute_task_on_random_agent(task_data)

        if result:
            return {"success": True, "result": result}
        else:
            return {"success": False, "message": "No agents available"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/tier0/agents/{agent_id}/heartbeat")
async def get_agent_heartbeat(agent_id: str):
    try:
        # Force a heartbeat collection before returning
        await tier0_manager.collect_heartbeats()
        heartbeat = tier0_manager.get_agent_heartbeat(agent_id)
        if heartbeat:
            return {"success": True, "heartbeat": heartbeat}
        else:
            return {"success": False, "message": f"Heartbeat for agent {agent_id} not yet collected"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/tier0/agents/heartbeats")
async def get_all_agent_heartbeats():
    try:
        heartbeats = tier0_manager.get_all_heartbeats()
        return {"success": True, "heartbeats": heartbeats, "count": len(heartbeats)}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/tier0/summary")
async def get_tier0_summary():
    try:
        summary = tier0_manager.get_system_summary()
        return {"success": True, "summary": summary}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/tier0/agents/{agent_id}/reset")
async def reset_agent_metrics(agent_id: str):
    try:
        success = tier0_manager.reset_agent_metrics(agent_id)
        return {"success": success, "message": f"Agent {agent_id} metrics reset" if success else f"Agent {agent_id} not found"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/tier0/agents/shutdown")
async def shutdown_tier0_agents():
    try:
        tier0_manager.shutdown_agents()
        return {"success": True, "message": "All agents shut down"}
    except Exception as e:
        return {"success": False, "message": str(e)}


