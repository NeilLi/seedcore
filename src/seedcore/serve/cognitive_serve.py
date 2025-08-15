"""
Ray Serve deployment for SeedCore Cognitive Core.

This module provides scalable, shared inference capabilities for cognitive tasks
using Ray Serve, enabling multiple agents or external services to share a pool
of LLM "brains" for heavy workloads.
"""

import ray
from ray import serve
import json
import logging
from typing import Dict, Any, Optional
from pydantic import BaseModel

from ..agents.cognitive_core import (
    CognitiveCore, 
    CognitiveContext, 
    CognitiveTaskType,
    initialize_cognitive_core,
    get_cognitive_core
)

logger = logging.getLogger(__name__)


class CognitiveRequest(BaseModel):
    """Request model for cognitive tasks."""
    agent_id: str
    task_type: str
    input_data: Dict[str, Any]
    memory_context: Optional[Dict[str, Any]] = None
    energy_context: Optional[Dict[str, Any]] = None
    lifecycle_context: Optional[Dict[str, Any]] = None


class CognitiveResponse(BaseModel):
    """Response model for cognitive tasks."""
    success: bool
    agent_id: str
    task_type: str
    result: Dict[str, Any]
    error: Optional[str] = None


@serve.deployment(
    num_replicas=2,
    ray_actor_options={
        "num_cpus": 0.5,
        "num_gpus": 0,  # Adjust based on your GPU availability
        "memory": 2 * 1024 * 1024 * 1024,  # 2GB memory
    }
)
class CognitiveCoreServe:
    """
    Ray Serve deployment for cognitive core reasoning.
    
    This deployment provides scalable, shared inference capabilities for:
    - Failure analysis
    - Task planning
    - Decision making
    - Problem solving
    - Memory synthesis
    - Capability assessment
    """
    
    def __init__(self, llm_provider: str = "openai", model: str = "gpt-4o"):
        """Initialize the cognitive core serve deployment."""
        self.llm_provider = llm_provider
        self.model = model
        self.cognitive_core = None
        
        # Initialize the cognitive core
        try:
            self.cognitive_core = initialize_cognitive_core(llm_provider, model)
            logger.info(f"✅ CognitiveCoreServe initialized with {llm_provider} and {model}")
        except Exception as e:
            logger.error(f"❌ Failed to initialize cognitive core: {e}")
            raise
    
    async def __call__(self, request: CognitiveRequest) -> CognitiveResponse:
        """
        Main entry point for cognitive reasoning requests.
        
        Args:
            request: CognitiveRequest containing task information
            
        Returns:
            CognitiveResponse with reasoning results
        """
        try:
            # Validate task type
            try:
                task_type = CognitiveTaskType(request.task_type)
            except ValueError:
                return CognitiveResponse(
                    success=False,
                    agent_id=request.agent_id,
                    task_type=request.task_type,
                    result={},
                    error=f"Invalid task type: {request.task_type}"
                )
            
            # Create cognitive context
            context = CognitiveContext(
                agent_id=request.agent_id,
                task_type=task_type,
                input_data=request.input_data,
                memory_context=request.memory_context,
                energy_context=request.energy_context,
                lifecycle_context=request.lifecycle_context
            )
            
            # Perform cognitive reasoning
            result = self.cognitive_core(context)
            
            return CognitiveResponse(
                success=result.get("success", False),
                agent_id=request.agent_id,
                task_type=request.task_type,
                result=result
            )
            
        except Exception as e:
            logger.error(f"Error in cognitive reasoning: {e}")
            return CognitiveResponse(
                success=False,
                agent_id=request.agent_id,
                task_type=request.task_type,
                result={},
                error=str(e)
            )
    
    async def reason_about_failure(self, agent_id: str, incident_context: Dict[str, Any]) -> CognitiveResponse:
        """
        Analyze agent failures using cognitive reasoning.
        
        Args:
            agent_id: ID of the agent
            incident_context: Context of the incident
            
        Returns:
            CognitiveResponse with analysis results
        """
        request = CognitiveRequest(
            agent_id=agent_id,
            task_type=CognitiveTaskType.FAILURE_ANALYSIS.value,
            input_data=incident_context
        )
        return await self.__call__(request)
    
    async def plan_task(self, agent_id: str, task_description: str, agent_capabilities: Dict[str, Any], available_resources: Dict[str, Any]) -> CognitiveResponse:
        """
        Plan complex tasks using cognitive reasoning.
        
        Args:
            agent_id: ID of the agent
            task_description: Description of the task
            agent_capabilities: Agent capabilities
            available_resources: Available resources
            
        Returns:
            CognitiveResponse with planning results
        """
        input_data = {
            "task_description": task_description,
            "agent_capabilities": agent_capabilities,
            "available_resources": available_resources
        }
        
        request = CognitiveRequest(
            agent_id=agent_id,
            task_type=CognitiveTaskType.TASK_PLANNING.value,
            input_data=input_data
        )
        return await self.__call__(request)
    
    async def make_decision(self, agent_id: str, decision_context: Dict[str, Any], historical_data: Dict[str, Any] = None) -> CognitiveResponse:
        """
        Make decisions using cognitive reasoning.
        
        Args:
            agent_id: ID of the agent
            decision_context: Context for the decision
            historical_data: Historical data
            
        Returns:
            CognitiveResponse with decision results
        """
        input_data = {
            "decision_context": decision_context,
            "historical_data": historical_data or {}
        }
        
        request = CognitiveRequest(
            agent_id=agent_id,
            task_type=CognitiveTaskType.DECISION_MAKING.value,
            input_data=input_data
        )
        return await self.__call__(request)
    
    async def solve_problem(self, agent_id: str, problem_statement: str, constraints: Dict[str, Any], available_tools: Dict[str, Any]) -> CognitiveResponse:
        """
        Solve problems using cognitive reasoning.
        
        Args:
            agent_id: ID of the agent
            problem_statement: Statement of the problem
            constraints: Problem constraints
            available_tools: Available tools
            
        Returns:
            CognitiveResponse with solution results
        """
        input_data = {
            "problem_statement": problem_statement,
            "constraints": constraints,
            "available_tools": available_tools
        }
        
        request = CognitiveRequest(
            agent_id=agent_id,
            task_type=CognitiveTaskType.PROBLEM_SOLVING.value,
            input_data=input_data
        )
        return await self.__call__(request)
    
    async def synthesize_memory(self, agent_id: str, memory_fragments: list, synthesis_goal: str) -> CognitiveResponse:
        """
        Synthesize memory using cognitive reasoning.
        
        Args:
            agent_id: ID of the agent
            memory_fragments: Memory fragments to synthesize
            synthesis_goal: Goal of the synthesis
            
        Returns:
            CognitiveResponse with synthesis results
        """
        input_data = {
            "memory_fragments": memory_fragments,
            "synthesis_goal": synthesis_goal
        }
        
        request = CognitiveRequest(
            agent_id=agent_id,
            task_type=CognitiveTaskType.MEMORY_SYNTHESIS.value,
            input_data=input_data
        )
        return await self.__call__(request)
    
    async def assess_capabilities(self, agent_id: str, performance_data: Dict[str, Any], current_capabilities: Dict[str, Any], target_capabilities: Dict[str, Any]) -> CognitiveResponse:
        """
        Assess capabilities using cognitive reasoning.
        
        Args:
            agent_id: ID of the agent
            performance_data: Performance data
            current_capabilities: Current capabilities
            target_capabilities: Target capabilities
            
        Returns:
            CognitiveResponse with assessment results
        """
        input_data = {
            "performance_data": performance_data,
            "current_capabilities": current_capabilities,
            "target_capabilities": target_capabilities
        }
        
        request = CognitiveRequest(
            agent_id=agent_id,
            task_type=CognitiveTaskType.CAPABILITY_ASSESSMENT.value,
            input_data=input_data
        )
        return await self.__call__(request)
    
    async def health(self) -> Dict[str, Any]:
        """Health check endpoint."""
        import time
        return {
            "status": "healthy",
            "service": "cognitive_core",
            "provider": self.cognitive_core.llm_provider,
            "model": self.cognitive_core.model,
            "timestamp": time.time()
        }


# =============================================================================
# Deployment Management
# =============================================================================

def deploy_cognitive_core(
    llm_provider: str = "openai",
    model: str = "gpt-4o",
    num_replicas: int = 2,
    name: str = "cognitive_core",
    route_prefix: str = "/cognitive"
) -> str:
    """
    Deploy the cognitive core as a Ray Serve application.
    
    Args:
        llm_provider: LLM provider to use
        model: Model to use
        num_replicas: Number of replicas to deploy
        name: Name of the deployment
        route_prefix: Route prefix for the deployment (default: /cognitive)
        
    Returns:
        Deployment name
    """
    try:
        # Create deployment
        deployment = CognitiveCoreServe.options(
            num_replicas=num_replicas,
            name=name
        ).bind(llm_provider, model)
        
        # Deploy with custom route prefix to avoid conflicts
        app = serve.run(deployment, name=name, route_prefix=route_prefix)
        
        logger.info(f"✅ Cognitive core deployed as '{name}' with {num_replicas} replicas at route '{route_prefix}'")
        return name
        
    except Exception as e:
        logger.error(f"❌ Failed to deploy cognitive core: {e}")
        raise


def get_cognitive_core_client(name: str = "cognitive_core"):
    """
    Get a client for the deployed cognitive core.
    
    Args:
        name: Name of the deployment
        
    Returns:
        Ray Serve client
    """
    try:
        return serve.get_app_handle(name)
    except Exception as e:
        logger.error(f"❌ Failed to get cognitive core client: {e}")
        raise


def undeploy_cognitive_core(name: str = "cognitive_core"):
    """
    Undeploy the cognitive core.
    
    Args:
        name: Name of the deployment
    """
    try:
        serve.delete(name)
        logger.info(f"✅ Cognitive core '{name}' undeployed")
    except Exception as e:
        logger.error(f"❌ Failed to undeploy cognitive core: {e}")
        raise


# =============================================================================
# Client Utilities
# =============================================================================

class CognitiveCoreClient:
    """
    Client for interacting with the deployed cognitive core.
    """
    
    def __init__(self, deployment_name: str = "cognitive_core"):
        self.deployment_name = deployment_name
        self.client = get_cognitive_core_client(deployment_name)
    
    async def reason_about_failure(self, agent_id: str, incident_context: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze agent failures."""
        response = await self.client.reason_about_failure.remote(agent_id, incident_context)
        return response.dict()
    
    async def plan_task(self, agent_id: str, task_description: str, agent_capabilities: Dict[str, Any], available_resources: Dict[str, Any]) -> Dict[str, Any]:
        """Plan complex tasks."""
        response = await self.client.plan_task.remote(agent_id, task_description, agent_capabilities, available_resources)
        return response.dict()
    
    async def make_decision(self, agent_id: str, decision_context: Dict[str, Any], historical_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Make decisions."""
        response = await self.client.make_decision.remote(agent_id, decision_context, historical_data)
        return response.dict()
    
    async def solve_problem(self, agent_id: str, problem_statement: str, constraints: Dict[str, Any], available_tools: Dict[str, Any]) -> Dict[str, Any]:
        """Solve problems."""
        response = await self.client.solve_problem.remote(agent_id, problem_statement, constraints, available_tools)
        return response.dict()
    
    async def synthesize_memory(self, agent_id: str, memory_fragments: list, synthesis_goal: str) -> Dict[str, Any]:
        """Synthesize memory."""
        response = await self.client.synthesize_memory.remote(agent_id, memory_fragments, synthesis_goal)
        return response.dict()
    
    async def assess_capabilities(self, agent_id: str, performance_data: Dict[str, Any], current_capabilities: Dict[str, Any], target_capabilities: Dict[str, Any]) -> Dict[str, Any]:
        """Assess capabilities."""
        response = await self.client.assess_capabilities.remote(agent_id, performance_data, current_capabilities, target_capabilities)
        return response.dict() 