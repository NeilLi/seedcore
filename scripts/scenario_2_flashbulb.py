import ray
import time
import os
from src.seedcore.agents.ray_actor import RayAgent
from src.seedcore.utils.ray_utils import ensure_ray_initialized

def run_scenario():
    """
    Executes Scenario 2: Critical Failure and Flashbulb Incident.
    """
    print("--- Running Scenario 2: Critical Failure and Flashbulb Incident ---")
    ensure_ray_initialized()

    # 1. Create an agent
    agent = RayAgent.remote(agent_id="Agent-Critical-Ops")
    
    # 2. Define a high-stakes task
    high_stakes_task = {
        "name": "NuclearCoreCoolantSystemCheck",
        "risk": 0.9, # High risk means failure is very salient
        "reward": 1000
    }
    
    print(f"\nAssigning high-stakes task '{high_stakes_task['name']}' to {ray.get(agent.get_id.remote())}...")
    
    # 3. Execute the task
    result_ref = agent.execute_high_stakes_task.remote(high_stakes_task)
    result = ray.get(result_ref)
    
    print("\n--- Task Execution Complete ---")
    print(f"Result: {result}")
    
    if result.get("incident_logged"):
        print("\n✅ VALIDATION SUCCEEDED: A high-salience incident was correctly identified and logged.")
        print("Check the 'seedcore-api' container logs for confirmation of the write to MySQL.")
    else:
        print("\n⚠️ VALIDATION NOTE: The incident was not logged because its salience score was below the threshold.")

    print("\n--- Scenario Complete ---")

if __name__ == "__main__":
    run_scenario() 