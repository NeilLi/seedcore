import ray
import time
import os
import asyncio
import json
from src.seedcore.agents.ray_actor import RayAgent
from src.seedcore.agents.observer_agent import ObserverAgent
from src.seedcore.utils.ray_utils import init_ray

# --- MODIFIED: Load the correct UUID from the artifacts directory ---
UUID_FILE_PATH = '/data/fact_uuids.json'  # Mounted volume from docker-compose
try:
    with open(UUID_FILE_PATH, 'r') as f:
        FACT_TO_FIND = json.load(f)["fact_Y"]
except (FileNotFoundError, KeyError):
    print(f"ERROR: Could not load fact_Y UUID from {UUID_FILE_PATH}.")
    print("This usually means the db-seed service hasn't run yet.")
    print("Please ensure you've run 'docker-compose up -d --build' to seed the database.")
    exit(1)

NUM_WORKER_AGENTS = 5
NUM_REQUESTS_PER_AGENT = 3

async def run_scenario():
    print("--- Running Scenario 3: Pattern Recognition and Proactive Caching ---")
    init_ray()

    # 1. Create a pool of worker agents and one observer agent
    workers = [RayAgent.remote(agent_id=f"Worker-{i}") for i in range(NUM_WORKER_AGENTS)]
    
    # Try to get existing observer or create new one with fixed name
    try:
        observer = ray.get_actor("observer", namespace="seedcore")
        print("✅ Using existing observer agent.")
    except ValueError:
        # Create new observer with fixed name (no timestamp)
        observer = ObserverAgent.options(name="observer", namespace="seedcore", lifetime="detached").remote()
        print("✅ Created new observer agent.")
    
    print(f"✅ Created {len(workers)} worker agents and 1 observer agent.")
    
    # Kick the async bootstrap *once* and wait a second
    await observer.ready.remote()
    await asyncio.sleep(1)
    print("✅ Observer agent ready (monitoring loop starts automatically).")

    # --- PHASE 1: Generate Cache Misses ---
    print("\n--- Phase 1: Generating cache misses from all workers ---")
    phase1_tasks = []
    for worker in workers:
        for _ in range(NUM_REQUESTS_PER_AGENT):
            phase1_tasks.append(worker.find_knowledge.remote(FACT_TO_FIND))
    
    # Use asyncio.gather instead of ray.get for non-blocking execution
    await asyncio.gather(*phase1_tasks)
    print("✅ Phase 1 complete. All workers have requested the fact, generating misses.")
    
    # --- Wait for the observer to act ---
    print("\n--- Waiting for 6 seconds to allow the Observer to detect the pattern and act... ---")
    await asyncio.sleep(6)

    # --- PHASE 2: Expect Cache Hits ---
    print("\n--- Phase 2: Requesting the same fact, expecting cache hits ---")
    phase2_tasks = []
    for worker in workers:
        phase2_tasks.append(worker.find_knowledge.remote(FACT_TO_FIND))
        
    # Use asyncio.gather instead of ray.get for non-blocking execution
    await asyncio.gather(*phase2_tasks)
    print("✅ Phase 2 complete.")
    print("\nValidation: Check the logs. The first phase should show 'Mw MISS' from workers.")
    print("The observer should log 'Hot item detected' and 'Proactively caching'.")
    print("The second phase should show 'Mw cache hit' from workers.")
    
    print("\n--- Scenario Complete ---")

if __name__ == "__main__":
    asyncio.run(run_scenario()) 