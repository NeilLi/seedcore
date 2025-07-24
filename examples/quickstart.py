# Copyright 2024 SeedCore Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# examples/quickstart.py

# --- Import the necessary components ---
from seedcore.control.fast_loop import fast_loop_select_agent
from seedcore.organs.base import Organ
from seedcore.agents.base import Agent
from seedcore.energy.api import read_energy
import os

def main():
    """
    Simulates a single action in the SeedCore system to demonstrate
    an energy change.
    """
    print("--- SeedCore Quickstart Simulation ---")

    # 1. Check the energy BEFORE the action
    print("\n[Initial State]")
    initial_energy = read_energy()
    print(f"Energy before running loop: {initial_energy}")

    # 2. Set up the necessary components for the simulation
    print("\n[Simulation Setup]")
    organ = Organ(organ_id="cognitive_organ_1")
    agent = Agent(agent_id="scout_agent_alpha")
    organ.register(agent)
    print(f"Created organ '{organ.organ_id}' and registered agent '{agent.agent_id}'")

    # 3. Run the control loop to simulate an action
    # This is the "WRITER" step that updates the energy ledger.
    print("\n[Action: Running Fast Loop]")
    # We need to add the 'add_pair_delta' method to the ledger first.
    # We'll assume a dummy task for now.
    selected_agent = fast_loop_select_agent(organ, task="analyze_data")
    print(f"Fast loop selected agent: {selected_agent.agent_id}")


    # 4. Check the energy AFTER the action
    print("\n[Final State]")
    final_energy = read_energy()
    print(f"Energy after running loop: {final_energy}")

    print("\n--- Simulation Complete ---")
    # Get API endpoint from environment variable
    API_BASE_URL = os.getenv('SEEDCORE_API_URL', 'http://localhost:8000')
    print(f"Check the API endpoint at {API_BASE_URL}/energy/gradient to see the updated value.")


if __name__ == '__main__':
    main()
