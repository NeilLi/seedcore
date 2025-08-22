#!/usr/bin/env python3
"""
Janitor actor for cleaning up dead actors from the Ray cluster.
Runs on the cluster side to access ray.util.state and perform cleanup operations.
"""

import ray
import logging

logger = logging.getLogger(__name__)

@ray.remote(name="seedcore_janitor", lifetime="detached", num_cpus=0)
class Janitor:
    """Cluster-side actor for maintenance operations."""
    
    def __init__(self):
        logger.info("🚀 SeedCore Janitor actor initialized")
    
    def list_dead_named(self, prefix: str | None = None):
        """List dead named actors, optionally filtered by prefix."""
        try:
            from ray.util.state import list_actors
            out = []
            for a in list_actors():  # returns dicts in Ray 2.33
                name = a.get("name")
                state = a.get("state")
                if name and state == "DEAD" and (not prefix or name.startswith(prefix)):
                    out.append({
                        "name": name, 
                        "actor_id": a.get("actorId") or a.get("actor_id"),
                        "state": state
                    })
            logger.info(f"Found {len(out)} dead actors with prefix '{prefix}'")
            return out
        except Exception as e:
            logger.error(f"Failed to list dead actors: {e}")
            return []
    
    def reap(self, prefix: str | None = None):
        """Remove dead actors from the cluster."""
        try:
            import ray
            dead = self.list_dead_named(prefix)
            reaped = []
            
            for item in dead:
                aid = item.get("actor_id")
                if not aid:
                    continue
                    
                try:
                    # Works on cluster side; ActorID parsing differs by Ray version
                    # ray.kill accepts an ActorID or handle; we can ignore errors if best-effort
                    ray.kill(ray.actor.ActorID.from_hex(aid))  # may vary by version; wrap in try/except
                    reaped.append(item["name"])
                    logger.info(f"Reaped dead actor: {item['name']} ({aid})")
                except Exception as e:
                    logger.debug(f"Failed to reap actor {item['name']}: {e}")
                    continue
            
            result = {"reaped": reaped, "count": len(reaped)}
            logger.info(f"Cluster cleanup completed: {result['count']} actors reaped")
            return result
            
        except Exception as e:
            logger.error(f"Failed to reap dead actors: {e}")
            return {"reaped": [], "count": 0, "error": str(e)}
    
    def ping(self):
        """Simple ping method for health checks."""
        return "ok"
    
    def status(self):
        """Get janitor status and cluster health info."""
        try:
            from ray.util.state import list_actors
            total_actors = len(list_actors())
            dead_actors = len([a for a in list_actors() if a.get("state") == "DEAD"])
            
            return {
                "status": "healthy",
                "total_actors": total_actors,
                "dead_actors": dead_actors,
                "alive_actors": total_actors - dead_actors
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }
