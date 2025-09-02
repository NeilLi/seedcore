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
import uuid
import time
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from fastapi import HTTPException

from ..agents.cognitive_core import (
    CognitiveCore, 
    CognitiveContext, 
    CognitiveTaskType,
    initialize_cognitive_core,
    get_cognitive_core
)

# Import the new centralized result schema
from ..models.result_schema import (
    create_escalated_result, create_error_result, create_cognitive_result,
    TaskStep, TaskResult, ResultKind
)

logger = logging.getLogger(__name__)


class PlanRequest(BaseModel):
    """Request model for HGNN problem solving and task decomposition."""
    agent_id: str = Field(..., description="ID of the agent making the request")
    problem_statement: str = Field(..., description="Problem statement for the cognitive service")
    task_id: str = Field(..., description="Unique task identifier")
    type: str = Field(..., description="Task type (general_query, graph_rag, etc.)")
    description: str = Field(..., description="Task description")
    constraints: Dict[str, Any] = Field(default_factory=dict, description="Task constraints (latency, budget, etc.)")
    context: Dict[str, Any] = Field(default_factory=dict, description="Task context including drift_score, features, history")
    available_organs: List[str] = Field(..., description="List of available organ IDs")
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Correlation ID for tracing")


class PlanResponse(BaseModel):
    """Response model for HGNN problem solving and task decomposition."""
    success: bool = Field(..., description="Whether the planning was successful")
    solution_steps: List[Dict[str, Any]] = Field(default_factory=list, description="List of solution steps with organ_id and task")
    explanations: Optional[str] = Field(None, description="Optional explanation of the plan")
    error: Optional[str] = Field(None, description="Error message if planning failed")
    
    def to_task_result(self) -> TaskResult:
        """Convert to the new centralized TaskResult format."""
        if self.success:
            # Convert solution_steps to TaskStep objects
            task_steps = []
            for step in self.solution_steps:
                if isinstance(step, dict):
                    task_steps.append(TaskStep(
                        organ_id=step.get("organ_id", "unknown"),
                        success=True,
                        task=step.get("task", {}),
                        result=step.get("result"),
                        metadata=step
                    ))
                else:
                    task_steps.append(TaskStep(
                        organ_id="unknown",
                        success=False,
                        error=f"Invalid step format: {step}"
                    ))
            
            return create_escalated_result(
                solution_steps=task_steps,
                plan_source="cognitive_core",
                explanations=self.explanations
            )
        else:
            return create_error_result(
                error=self.error or "Planning failed",
                error_type="planning_failure"
            )


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
    - HGNN-based task decomposition (NEW)
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
    
    async def solve_problem(self, **payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main entry point for HGNN problem solving and task decomposition.
        
        Args:
            **payload: PlanRequest fields as keyword arguments
            
        Returns:
            PlanResponse as dictionary, now compatible with new schema
        """
        try:
            # Validate the request
            request = PlanRequest(**payload)
            logger.info(f"Solving problem for task {request.task_id} (type: {request.type})")
            
            # Extract key information
            task_type = request.type
            description = request.description
            constraints = request.constraints
            context = request.context
            available_organs = request.available_organs
            drift_score = context.get("drift_score", 0.0)
            
            # Use cognitive core for reasoning
            if self.cognitive_core:
                # Create cognitive context for planning
                cognitive_context = CognitiveContext(
                    agent_id=request.agent_id,
                    task_type=CognitiveTaskType.TASK_PLANNING,
                    input_data={
                        "task_description": description,
                        "task_type": task_type,
                        "constraints": constraints,
                        "available_organs": available_organs,
                        "drift_score": drift_score,
                        "context": context
                    }
                )
                
                # Get planning result from cognitive core
                result = self.cognitive_core(cognitive_context)
                logger.info(f"[CognitiveServe] Raw cognitive core result: {result}")
                
                # Extract solution steps from the result
                solution_steps = result.get("solution_steps", [])
                logger.info(f"[CognitiveServe] Raw solution_steps: {solution_steps} (type: {type(solution_steps)})")
                
                # Parse solution_steps if it's a string
                if isinstance(solution_steps, str):
                    try:
                        import json
                        solution_steps = json.loads(solution_steps)
                        logger.info(f"[CognitiveServe] Parsed solution_steps: {solution_steps}")
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning(f"[CognitiveServe] Failed to parse solution_steps as JSON: {e}")
                        solution_steps = []
                
                if not solution_steps or not isinstance(solution_steps, list):
                    logger.warning(f"[CognitiveServe] Invalid solution_steps, using fallback plan")
                    # Fallback: create a simple plan based on available organs
                    solution_steps = self._create_fallback_plan(request)
                
                plan_response = PlanResponse(
                    success=True,
                    solution_steps=solution_steps,
                                    explanations=result.get("explanations", "Generated by HGNN reasoning engine"),
                error=None
                )
                
                # Convert to new schema format
                return plan_response.to_task_result().model_dump()
            else:
                # Fallback when cognitive core is not available
                solution_steps = self._create_fallback_plan(request)
                plan_response = PlanResponse(
                    success=True,
                    solution_steps=solution_steps,
                                    explanations="Fallback plan generated due to cognitive core unavailability",
                error=None
                )
                
                # Convert to new schema format
                return plan_response.to_task_result().model_dump()
                
        except Exception as e:
            logger.error(f"Error in solve_problem: {e}")
            error_result = create_error_result(
                error=str(e),
                error_type="solve_problem_error"
            )
            return error_result.model_dump()
    
    def _create_fallback_plan(self, request: PlanRequest) -> List[Dict[str, Any]]:
        """Create a fallback plan when cognitive reasoning is unavailable."""
        available_organs = request.available_organs
        
        if not available_organs:
            return []
        
        # Simple round-robin or priority-based routing
        if "retrieval" in available_organs:
            # Start with retrieval for most tasks
            return [
                {
                    "organ_id": "retrieval",
                    "task": {
                        "op": "search",
                        "args": {"query": request.description, "limit": 10}
                    }
                }
            ]
        elif "graph" in available_organs:
            # Use graph organ for graph-related tasks
            return [
                {
                    "organ_id": "graph",
                    "task": {
                        "op": "query",
                        "args": {"query": request.description}
                    }
                }
            ]
        else:
            # Use first available organ
            return [
                {
                    "organ_id": available_organs[0],
                    "task": {
                        "op": "execute",
                        "args": {"input": request.description}
                    }
                }
            ]

    async def __call__(self, request: CognitiveRequest) -> CognitiveResponse:
        """
        Main entry point for cognitive reasoning requests.
        
        Args:
            request: CognitiveRequest containing task information
            
        Returns:
            CognitiveResponse with reasoning results, now using new schema
        """
        try:
            # Validate task type
            try:
                task_type = CognitiveTaskType(request.task_type)
            except ValueError:
                error_result = create_error_result(
                    error=f"Invalid task type: {request.task_type}",
                    error_type="invalid_task_type"
                )
                return CognitiveResponse(
                    success=False,
                    agent_id=request.agent_id,
                    task_type=request.task_type,
                    result=error_result.model_dump(),
                    error=f"Invalid task type: {request.task_type}"
                )
            
            # Process the request using cognitive core
            if self.cognitive_core:
                # Create cognitive context
                cognitive_context = CognitiveContext(
                    agent_id=request.agent_id,
                    task_type=task_type,
                    input_data=request.input_data
                )
                
                # Get result from cognitive core
                result = self.cognitive_core(cognitive_context)
                
                # The result is already in the new schema format from cognitive core
                return CognitiveResponse(
                    success=True,
                    agent_id=request.agent_id,
                    task_type=request.task_type,
                    result=result,
                    error=None
                )
            else:
                # Fallback when cognitive core is not available
                error_result = create_error_result(
                    error="Cognitive core not available",
                    error_type="cognitive_core_unavailable"
                )
                return CognitiveResponse(
                    success=False,
                    agent_id=request.agent_id,
                    task_type=request.task_type,
                    result=error_result.model_dump(),
                    error="Cognitive core not available"
                )
                
        except Exception as e:
            logger.error(f"Error in cognitive reasoning: {e}")
            error_result = create_error_result(
                error=str(e),
                error_type="cognitive_reasoning_error"
            )
            return CognitiveResponse(
                success=False,
                agent_id=request.agent_id,
                task_type=request.task_type,
                result=error_result.model_dump(),
                error=str(e)
            )

    async def ping(self) -> str:
        """Health check method to verify the deployment is responsive."""
        return "pong"
    
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
    Safe client wrapper for actors to communicate with CognitiveCore Serve deployment.
    
    This client provides:
    - Automatic backoff and retry logic
    - Timeout handling
    - Safe handle acquisition
    - Fallback behavior when Serve is unavailable
    """
    
    def __init__(self, deployment_name: str = "cognitive", timeout_s: float = 8.0):
        self.deployment_name = deployment_name
        self.timeout_s = timeout_s
        self._handle = None
        self._last_health_check = 0
        self._health_check_interval = 30  # seconds

    def _get_handle(self):
        """Get or refresh the Serve handle with backoff retry."""
        if self._handle is not None:
            return self._handle
            
        backoff = 0.5
        for attempt in range(8):
            try:
                self._handle = serve.get_app_handle(self.deployment_name)
                # Test the handle with a simple ping
                test_ref = self._handle.ping.remote()
                ray.get(test_ref, timeout=2.0)
                return self._handle
            except Exception as e:
                if attempt < 7:  # Don't sleep on last attempt
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 4.0)
                logger.warning(f"Failed to acquire Serve handle for '{self.deployment_name}' (attempt {attempt + 1}): {e}")
        
        raise RuntimeError(f"Cannot acquire Serve handle for '{self.deployment_name}' after 8 attempts")

    async def solve_problem(self, **payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Solve a problem using the CognitiveCore Serve deployment.
        
        Args:
            **payload: PlanRequest fields as keyword arguments
            
        Returns:
            PlanResponse as dictionary
        """
        try:
            handle = self._get_handle()
            # Call the solve_problem method on the deployment
            ref = handle.solve_problem.remote(**payload)
            return await ray.get_async(ref, timeout=self.timeout_s)
        except Exception as e:
            logger.warning(f"CognitiveCore call failed: {e}")
            # Return a fallback response
            return {
                "success": False,
                "solution_steps": [],
                "explanations": f"Fallback due to Serve error: {e}",
                "error": str(e)
            }

    async def ping(self) -> bool:
        """Health check to verify the deployment is reachable."""
        try:
            handle = self._get_handle()
            ref = handle.ping.remote()
            await ray.get_async(ref, timeout=2.0)
            return True
        except Exception:
            return False

    def is_healthy(self) -> bool:
        """Check if the client can reach the deployment (cached)."""
        now = time.time()
        if now - self._last_health_check > self._health_check_interval:
            try:
                # Use sync version for health checks
                handle = self._get_handle()
                ref = handle.ping.remote()
                ray.get(ref, timeout=2.0)
                self._last_health_check = now
                return True
            except Exception:
                self._last_health_check = now
                return False
        return True 