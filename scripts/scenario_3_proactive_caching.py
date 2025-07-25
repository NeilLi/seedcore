import ray
import time
import os
import json
from src.seedcore.agents.ray_actor import RayAgent
from src.seedcore.agents.observer_agent import ObserverAgent
from src.seedcore.utils.ray_utils import init_ray

UUID_FILE_PATH = os.path.join(os.path.dirname(__file__), 'fact_uuids.json')
try:
    with open(UUID_FILE_PATH, 'r') as f:
        FACT_TO_FIND = json.load(f)["fact_Y"]
except (FileNotFoundError, KeyError):
    print(f"ERROR: Could not load fact_Y UUID from {UUID_FILE_PATH}. Please run populate_mlt.py first.")
    exit(1)

NUM_WORKER_AGENTS = 5
NUM_REQUESTS_PER_AGENT = 3

def run_scenario():
    print("--- Running Scenario 3: Pattern Recognition and Proactive Caching ---")
    init_ray()

    # 1. Create a pool of worker agents and one observer agent
    workers = [RayAgent.remote(agent_id=f"Worker-{i}") for i in range(NUM_WORKER_AGENTS)]
    observer = ObserverAgent.remote()
    print(f"✅ Created {len(workers)} worker agents and 1 observer agent.")

    # 2. Start the observer's monitoring loop in the background.
    observer.start_monitoring_loop.remote(interval_seconds=5)
    print("✅ Observer agent monitoring loop started.")

    # --- PHASE 1: Generate Cache Misses ---
    print("\n--- Phase 1: Generating cache misses from all workers ---")
    phase1_tasks = []
    for worker in workers:
        for _ in range(NUM_REQUESTS_PER_AGENT):
            phase1_tasks.append(worker.find_knowledge.remote(FACT_TO_FIND))
    
    ray.get(phase1_tasks) # Wait for all requests to complete
    print("✅ Phase 1 complete. All workers have requested the fact, generating misses.")

    # --- Wait for the observer to act ---
    print("\n--- Waiting for 6 seconds to allow the Observer to detect the pattern and act... ---")
    time.sleep(6)

    # --- PHASE 2: Expect Cache Hits ---
    print("\n--- Phase 2: Requesting the same fact, expecting cache hits ---")
    phase2_tasks = []
    for worker in workers:
        phase2_tasks.append(worker.find_knowledge.remote(FACT_TO_FIND))
        
    ray.get(phase2_tasks) # Wait for all requests to complete
    print("✅ Phase 2 complete.")
    print("\nValidation: Check the logs. The first phase should show 'Mw MISS' from workers.")
    print("The observer should log 'Hot item detected' and 'Proactively caching'.")
    print("The second phase should show 'Mw cache hit' from workers.")
    
    print("\n--- Scenario Complete ---")

if __name__ == "__main__":
    run_scenario() 