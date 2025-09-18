#!/usr/bin/env python3
"""
Cognitive Service Client for SeedCore (Updated)

This client provides a clean interface to the deployed cognitive service
using the new base client architecture.
"""

import logging
from typing import Dict, Any, Optional, List
from .base_client import BaseServiceClient, CircuitBreaker, RetryConfig

logger = logging.getLogger(__name__)

class CognitiveServiceClient(BaseServiceClient):
    """
    Client for the deployed cognitive service that handles:
    - Problem solving
    - Decision making
    - Memory synthesis
    - Capability assessment
    - Task planning
    """
    
    def __init__(self, 
                 base_url: str = None, 
                 timeout: float = 8.0):
        # Use centralized gateway discovery
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import COG
                base_url = COG
            except Exception:
                base_url = "http://127.0.0.1:8000/cognitive"
        
        # Configure circuit breaker for cognitive service
        circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
            expected_exception=(Exception,)  # Catch all exceptions
        )
        
        # Configure retry for cognitive service
        retry_config = RetryConfig(
            max_attempts=2,
            base_delay=1.0,
            max_delay=5.0
        )
        
        super().__init__(
            service_name="cognitive_service",
            base_url=base_url,
            timeout=timeout,
            circuit_breaker=circuit_breaker,
            retry_config=retry_config
        )
    
    # Problem Solving
    async def solve_problem(self, 
                          agent_id: str,
                          problem_statement: str,
                          constraints: Dict[str, Any] = None,
                          available_tools: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Solve a problem using the cognitive service.
        
        Args:
            agent_id: Agent identifier
            problem_statement: Problem to solve
            constraints: Optional constraints
            available_tools: Available tools for solving
            
        Returns:
            Problem solving result
        """
        request_data = {
            "agent_id": agent_id,
            "problem_statement": problem_statement,
            "constraints": constraints or {},
            "available_tools": available_tools or {}
        }
        return await self.post("/solve-problem", json=request_data)
    
    # Decision Making
    async def make_decision(self, 
                          agent_id: str,
                          decision_context: Dict[str, Any],
                          historical_data: Dict[str, Any] = None,
                          knowledge_context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Make a decision using the cognitive service.
        
        Args:
            agent_id: Agent identifier
            decision_context: Context for decision
            historical_data: Historical data
            knowledge_context: Knowledge context
            
        Returns:
            Decision result
        """
        request_data = {
            "agent_id": agent_id,
            "decision_context": decision_context,
            "historical_data": historical_data or {},
            "knowledge_context": knowledge_context or {}
        }
        return await self.post("/make-decision", json=request_data)
    
    # Task Planning
    async def plan_task(self, 
                       agent_id: str,
                       task_description: str,
                       current_capabilities: Dict[str, Any] = None,
                       available_tools: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Plan a task using the cognitive service.
        
        Args:
            agent_id: Agent identifier
            task_description: Task to plan
            current_capabilities: Current capabilities
            available_tools: Available tools
            
        Returns:
            Task planning result
        """
        request_data = {
            "agent_id": agent_id,
            "task_description": task_description,
            "current_capabilities": current_capabilities or {},
            "available_tools": available_tools or {}
        }
        return await self.post("/plan-task", json=request_data)
    
    # Memory Synthesis
    async def synthesize_memory(self, 
                              agent_id: str,
                              memory_fragments: List[Dict[str, Any]],
                              synthesis_goal: str) -> Dict[str, Any]:
        """
        Synthesize memory using the cognitive service.
        
        Args:
            agent_id: Agent identifier
            memory_fragments: Memory fragments to synthesize
            synthesis_goal: Goal for synthesis
            
        Returns:
            Memory synthesis result
        """
        request_data = {
            "agent_id": agent_id,
            "memory_fragments": memory_fragments,
            "synthesis_goal": synthesis_goal
        }
        return await self.post("/synthesize-memory", json=request_data)
    
    # Capability Assessment
    async def assess_capabilities(self, 
                                agent_id: str,
                                performance_data: Dict[str, Any],
                                current_capabilities: Dict[str, Any],
                                target_capabilities: Dict[str, Any]) -> Dict[str, Any]:
        """
        Assess capabilities using the cognitive service.
        
        Args:
            agent_id: Agent identifier
            performance_data: Performance data
            current_capabilities: Current capabilities
            target_capabilities: Target capabilities
            
        Returns:
            Capability assessment result
        """
        request_data = {
            "agent_id": agent_id,
            "performance_data": performance_data,
            "current_capabilities": current_capabilities,
            "target_capabilities": target_capabilities
        }
        return await self.post("/assess-capabilities", json=request_data)
    
    # Failure Analysis
    async def reason_about_failure(self, 
                                 agent_id: str,
                                 incident_context: Dict[str, Any],
                                 knowledge_context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Reason about failure using the cognitive service.
        
        Args:
            agent_id: Agent identifier
            incident_context: Incident context
            knowledge_context: Knowledge context
            
        Returns:
            Failure analysis result
        """
        request_data = {
            "agent_id": agent_id,
            "incident_context": incident_context,
            "knowledge_context": knowledge_context or {}
        }
        return await self.post("/reason-about-failure", json=request_data)
    
    # Service Information
    async def get_service_info(self) -> Dict[str, Any]:
        """Get cognitive service information."""
        return await self.get("/info")
    
    async def is_healthy(self) -> bool:
        """Check if the cognitive service is healthy."""
        try:
            health = await self.health_check()
            return health.get("status") == "healthy"
        except Exception:
            return False
