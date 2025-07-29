#!/usr/bin/env python3
"""
Bootstrap module to create singleton Ray actors at cluster startup.
This ensures actors are created once and reused by all workers.
"""

import ray
from .memory.working_memory import MissTracker, SharedCache, MwStore

def bootstrap_actors():
    """Create singleton actors at cluster bootstrap."""
    # Check if we're in a worker process to avoid duplicate bootstrapping
    try:
        runtime_context = ray.get_runtime_context()
        if runtime_context.worker.mode == ray.WORKER_MODE:
            # We're in a worker process, don't bootstrap
            return None, None, None
    except Exception:
        # If we can't get runtime context, assume we're the driver
        pass
    
    print("🚀 Bootstrapping singleton Ray actors...")
    
    # Initialize Ray if not already initialized
    try:
        if not ray.is_initialized():
            ray.init(address="auto", namespace="seedcore")
    except Exception:
        # Ray might already be initialized, continue
        pass

    # Create singleton actors using robust pattern
    def create_actor_if_not_exists(actor_class, name, **options):
        """Create an actor if it doesn't exist, handle race conditions gracefully."""
        try:
            # Try to get existing actor first
            return ray.get_actor(name, namespace="seedcore")
        except ValueError:
            # Actor doesn't exist, create it
            try:
                return actor_class.options(
                    name=name,
                    namespace="seedcore",
                    lifetime="detached",
                    **options
                ).remote()
            except Exception as e:
                # Another process might have created it between our check and creation
                # Try to get it again
                try:
                    return ray.get_actor(name, namespace="seedcore")
                except ValueError:
                    # If we still can't get it, re-raise the original error
                    raise e

    # Create the singleton actors
    try:
        miss_tracker = create_actor_if_not_exists(MissTracker, "miss_tracker")
        shared_cache = create_actor_if_not_exists(SharedCache, "shared_cache")
        mw_store = create_actor_if_not_exists(MwStore, "mw")
        
        print("✅ Singleton actors created successfully:")
        print(f"   - MissTracker: {miss_tracker}")
        print(f"   - SharedCache: {shared_cache}")
        print(f"   - MwStore: {mw_store}")
        
        return miss_tracker, shared_cache, mw_store
        
    except Exception as e:
        print(f"⚠️ Warning: Could not create all actors: {e}")
        print("   Actors will be created on-demand by helper functions.")
        return None, None, None

if __name__ == "__main__":
    bootstrap_actors() 