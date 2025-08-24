import sys
import time

# Add project root to path, just like in the entrypoint
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

# Import the same components
from seedcore.agents.cognitive_core import (
    CognitiveContext,
    CognitiveTaskType,
    initialize_cognitive_core,
)

print("--- DEBUG SCRIPT: START ---")
print("This script will isolate the plan_task logic to find the crash.")

try:
    # 1. Initialize the core, just like the real service does
    print("\n[Step 1] Initializing cognitive core...")
    cognitive_core = initialize_cognitive_core()
    print("         ✅ Cognitive core initialized.")

    # 2. Create the exact same input data the test script would send
    print("\n[Step 2] Building input data for plan_task...")
    input_data = {
        "task_description": "Test task for validation",
        "agent_capabilities": {"capability_score": 0.5},
        "available_resources": {"tool1": "description"}
    }
    context = CognitiveContext(
        agent_id="debug-agent-001",
        task_type=CognitiveTaskType.TASK_PLANNING,
        input_data=input_data
    )
    print("         ✅ Input data created.")

    # 3. Call the core function - THIS IS THE STEP THAT IS LIKELY CRASHING
    print("\n[Step 3] Calling the cognitive core with plan_task context...")
    print("         If the script crashes now, the error is inside the core.")
    
    result = cognitive_core(context) # The crash will likely happen here

    # If we reach this point, the core logic did NOT crash.
    print("\n--- DEBUG SCRIPT: SUCCESS ---")
    print("✅ The call to the cognitive core completed without crashing.")
    print("Result:", result)

except Exception as e:
    # This will only catch Python exceptions, not a segfault, but is good practice
    print(f"\n--- DEBUG SCRIPT: PYTHON EXCEPTION CAUGHT ---")
    print(f"Error: {e}")
