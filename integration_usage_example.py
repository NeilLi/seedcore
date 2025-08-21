#!/usr/bin/env python3
"""
Usage example for RayAgentCognitiveIntegration

This demonstrates how to properly use the integration class in your Ray agents.
The key insight is that this class must run INSIDE Ray actors/tasks, not as standalone processes.
"""

from seedcore.agents import RayAgentCognitiveIntegration, CognitiveCoreError

# EXAMPLE 1: Using in a Ray Actor
@ray.remote
class MyAgent:
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        # The integration is instantiated inside the actor where it has full cluster access
        self.cognitive = RayAgentCognitiveIntegration()
    
    async def analyze_failure(self, incident_data: dict):
        """Analyze a failure using the cognitive core."""
        try:
            result = await self.cognitive.failure_analysis(
                agent_id=self.agent_id,
                incident_context=incident_data
            )
            return {"success": True, "analysis": result}
        except CognitiveCoreError as e:
            return {"success": False, "error": str(e)}
    
    async def make_decision(self, context: dict):
        """Make a decision using the cognitive core."""
        try:
            result = await self.cognitive.decide(
                agent_id=self.agent_id,
                decision_context=context
            )
            return {"success": True, "decision": result}
        except CognitiveCoreError as e:
            return {"success": False, "error": str(e)}

# EXAMPLE 2: Using in a Ray Task
@ray.remote
def agent_task(agent_id: str, task_data: dict):
    """A Ray task that uses the cognitive integration."""
    # Create the integration inside the task
    cognitive = RayAgentCognitiveIntegration()
    
    try:
        # Check if cognitive core is ready
        if not await cognitive.ensure_ready():
            return {"error": "Cognitive core not available"}
        
        # Use the cognitive core
        result = await cognitive.plan(
            agent_id=agent_id,
            task_description=task_data.get("description", ""),
            agent_capabilities=task_data.get("capabilities", {}),
            available_resources=task_data.get("resources", {})
        )
        
        return {"success": True, "plan": result}
        
    except CognitiveCoreError as e:
        return {"error": str(e)}

# EXAMPLE 3: Integration with existing Ray infrastructure
class AgentManager:
    """Example of how to integrate with existing Ray infrastructure."""
    
    def __init__(self):
        self.agents = {}
    
    def create_agent(self, agent_id: str):
        """Create a new agent actor."""
        agent = MyAgent.remote(agent_id)
        self.agents[agent_id] = agent
        return agent
    
    async def run_agent_task(self, agent_id: str, task_type: str, data: dict):
        """Run a task on a specific agent."""
        if agent_id not in self.agents:
            return {"error": f"Agent {agent_id} not found"}
        
        agent = self.agents[agent_id]
        
        if task_type == "failure_analysis":
            return await agent.analyze_failure.remote(data)
        elif task_type == "decision":
            return await agent.make_decision.remote(data)
        else:
            return {"error": f"Unknown task type: {task_type}"}

# USAGE NOTES:
# 1. This integration class MUST run inside Ray actors/tasks
# 2. It cannot be tested from kubectl exec due to Ray's internal service access restrictions
# 3. The class automatically handles connection to the Ray Serve cognitive core
# 4. All methods return proper results or raise CognitiveCoreError with clear messages
# 5. The integration is designed to be lightweight and efficient for in-cluster use

if __name__ == "__main__":
    print("This is a usage example for RayAgentCognitiveIntegration.")
    print("To use this integration:")
    print("1. Import it in your Ray actors/tasks")
    print("2. Instantiate it within the Ray context")
    print("3. Call its methods asynchronously")
    print("4. Handle CognitiveCoreError exceptions appropriately")
    print("\nThe integration cannot be tested from kubectl exec due to Ray's architecture.")
    print("It must run within Ray-managed processes to access internal services.")
