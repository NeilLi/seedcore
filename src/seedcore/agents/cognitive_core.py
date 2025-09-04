"""
DSPy Cognitive Core for SeedCore Agents.

This module provides the cognitive reasoning capabilities for agents using DSPy,
integrating with the SeedCore architecture for memory, energy, and lifecycle management.
"""

import dspy
import json
import logging
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass
from enum import Enum

# Import the new centralized result schema
from ..models.result_schema import (
    create_cognitive_result, create_error_result, TaskResult
)

logger = logging.getLogger("cognitiveseedcore.CognitiveCore")


class CognitiveTaskType(Enum):
    """Types of cognitive tasks that agents can perform."""
    FAILURE_ANALYSIS = "failure_analysis"
    TASK_PLANNING = "task_planning"
    DECISION_MAKING = "decision_making"
    PROBLEM_SOLVING = "problem_solving"
    MEMORY_SYNTHESIS = "memory_synthesis"
    CAPABILITY_ASSESSMENT = "capability_assessment"


@dataclass
class CognitiveContext:
    """Context information for cognitive tasks."""
    agent_id: str
    task_type: CognitiveTaskType
    input_data: Dict[str, Any]
    memory_context: Optional[Dict[str, Any]] = None
    energy_context: Optional[Dict[str, Any]] = None
    lifecycle_context: Optional[Dict[str, Any]] = None


# =============================================================================
# DSPy Signatures for Different Cognitive Tasks
# =============================================================================

class AnalyzeFailureSignature(dspy.Signature):
    """Analyze agent failures and propose solutions."""
    incident_context = dspy.InputField(
        desc="A JSON string containing the agent's state, failed task, and error context."
    )
    thought = dspy.OutputField(
        desc="Reasoned analysis of root cause and contributing factors."
    )
    proposed_solution = dspy.OutputField(
        desc="Actionable plan to prevent recurrence and improve agent performance."
    )
    confidence_score = dspy.OutputField(
        desc="Confidence in the analysis (0.0 to 1.0)."
    )


class TaskPlanningSignature(dspy.Signature):
    """Plan complex tasks with multiple steps."""
    task_description = dspy.InputField(
        desc="Description of the task to be planned."
    )
    agent_capabilities = dspy.InputField(
        desc="JSON string describing the agent's current capabilities and limitations."
    )
    available_resources = dspy.InputField(
        desc="JSON string describing available resources and constraints."
    )
    step_by_step_plan = dspy.OutputField(
        desc="Detailed step-by-step plan to accomplish the task."
    )
    estimated_complexity = dspy.OutputField(
        desc="Estimated complexity score (1-10) and reasoning."
    )
    risk_assessment = dspy.OutputField(
        desc="Assessment of potential risks and mitigation strategies."
    )


class DecisionMakingSignature(dspy.Signature):
    """Make decisions based on available information and context."""
    decision_context = dspy.InputField(
        desc="JSON string containing the decision context, options, and constraints."
    )
    historical_data = dspy.InputField(
        desc="JSON string containing relevant historical data and patterns."
    )
    reasoning = dspy.OutputField(
        desc="Detailed reasoning process for the decision."
    )
    decision = dspy.OutputField(
        desc="The chosen decision with justification."
    )
    confidence = dspy.OutputField(
        desc="Confidence level in the decision (0.0 to 1.0)."
    )
    alternative_options = dspy.OutputField(
        desc="Alternative options considered and why they were not chosen."
    )


class ProblemSolvingSignature(dspy.Signature):
    """Solve complex problems using systematic reasoning."""
    problem_statement = dspy.InputField(
        desc="Clear statement of the problem to be solved."
    )
    constraints = dspy.InputField(
        desc="JSON string describing constraints and limitations."
    )
    available_tools = dspy.InputField(
        desc="JSON string describing available tools and capabilities."
    )
    solution_approach = dspy.OutputField(
        desc="Systematic approach to solving the problem."
    )
    solution_steps = dspy.OutputField(
        desc="Detailed steps to implement the solution."
    )
    success_metrics = dspy.OutputField(
        desc="Metrics to measure solution success."
    )


class MemorySynthesisSignature(dspy.Signature):
    """Synthesize information from multiple memory sources."""
    memory_fragments = dspy.InputField(
        desc="JSON string containing multiple memory fragments to synthesize."
    )
    synthesis_goal = dspy.InputField(
        desc="Goal of the memory synthesis (e.g., pattern recognition, insight generation)."
    )
    synthesized_insight = dspy.OutputField(
        desc="Synthesized insight or pattern from the memory fragments."
    )
    confidence_level = dspy.OutputField(
        desc="Confidence in the synthesis (0.0 to 1.0)."
    )
    related_patterns = dspy.OutputField(
        desc="Related patterns or insights that emerged during synthesis."
    )


class CapabilityAssessmentSignature(dspy.Signature):
    """Assess agent capabilities and suggest improvements."""
    agent_performance_data = dspy.InputField(
        desc="JSON string containing agent performance metrics and history."
    )
    current_capabilities = dspy.InputField(
        desc="JSON string describing current agent capabilities."
    )
    target_capabilities = dspy.InputField(
        desc="JSON string describing desired target capabilities."
    )
    capability_gaps = dspy.OutputField(
        desc="Identified gaps between current and target capabilities."
    )
    improvement_plan = dspy.OutputField(
        desc="Detailed plan to improve agent capabilities."
    )
    priority_recommendations = dspy.OutputField(
        desc="Priority recommendations for capability development."
    )


# =============================================================================
# Cognitive Core Module
# =============================================================================

class CognitiveCore(dspy.Module):
    """
    Main cognitive core that orchestrates different types of reasoning tasks.
    
    This module integrates with SeedCore's memory, energy, and lifecycle systems
    to provide intelligent reasoning capabilities for agents.
    """
    
    def __init__(self, llm_provider: str = "openai", model: str = "gpt-4o"):
        super().__init__()
        self.llm_provider = llm_provider
        self.model = model
        
        # Initialize specialized cognitive modules
        self.failure_analyzer = dspy.ChainOfThought(AnalyzeFailureSignature)
        self.task_planner = dspy.ChainOfThought(TaskPlanningSignature)
        self.decision_maker = dspy.ChainOfThought(DecisionMakingSignature)
        self.problem_solver = dspy.ChainOfThought(ProblemSolvingSignature)
        self.memory_synthesizer = dspy.ChainOfThought(MemorySynthesisSignature)
        self.capability_assessor = dspy.ChainOfThought(CapabilityAssessmentSignature)
        
        # Task mapping
        self.task_handlers = {
            CognitiveTaskType.FAILURE_ANALYSIS: self.failure_analyzer,
            CognitiveTaskType.TASK_PLANNING: self.task_planner,
            CognitiveTaskType.DECISION_MAKING: self.decision_maker,
            CognitiveTaskType.PROBLEM_SOLVING: self.problem_solver,
            CognitiveTaskType.MEMORY_SYNTHESIS: self.memory_synthesizer,
            CognitiveTaskType.CAPABILITY_ASSESSMENT: self.capability_assessor,
        }
        
        logger.info(f"Initialized CognitiveCore with {llm_provider} and model {model}")
    
    def forward(self, context: CognitiveContext) -> Dict[str, Any]:
        """
        Process a cognitive task based on the provided context.
        
        Args:
            context: CognitiveContext containing task information and data
            
        Returns:
            Dictionary containing the cognitive task results
        """
        try:
            # Get the appropriate handler for the task type
            handler = self.task_handlers.get(context.task_type)
            if not handler:
                raise ValueError(f"Unsupported task type: {context.task_type}")
            
            # Prepare input data based on task type
            input_data = self._prepare_input_data(context)
            
            # Execute the cognitive task
            result = handler(**input_data)
            
            # Process and format the result
            processed_result = self._format_result(result, context)
            
            # Add metadata
            processed_result.update({
                "task_type": context.task_type.value,
                "agent_id": context.agent_id,
                "success": True,
                "model_used": self.model,
                "provider": self.llm_provider
            })
            
            logger.info(f"Completed cognitive task {context.task_type.value} for agent {context.agent_id}")
            return processed_result
            
        except Exception as e:
            # Handle both enum and string task types
            task_type_str = context.task_type.value if hasattr(context.task_type, 'value') else str(context.task_type)
            logger.error(f"Error in cognitive task {task_type_str}: {e}")
            return {
                "task_type": task_type_str,
                "agent_id": context.agent_id,
                "success": False,
                "error": str(e),
                "model_used": self.model,
                "provider": self.llm_provider
            }
    
    def _prepare_input_data(self, context: CognitiveContext) -> Dict[str, Any]:
        """Prepare input data for the specific task type."""
        if context.task_type == CognitiveTaskType.FAILURE_ANALYSIS:
            return {
                "incident_context": json.dumps(context.input_data)
            }
        elif context.task_type == CognitiveTaskType.TASK_PLANNING:
            return {
                "task_description": context.input_data.get("task_description", ""),
                "agent_capabilities": json.dumps(context.input_data.get("agent_capabilities", {})),
                "available_resources": json.dumps(context.input_data.get("available_resources", {}))
            }
        elif context.task_type == CognitiveTaskType.DECISION_MAKING:
            return {
                "decision_context": json.dumps(context.input_data.get("decision_context", {})),
                "historical_data": json.dumps(context.input_data.get("historical_data", {}))
            }
        elif context.task_type == CognitiveTaskType.PROBLEM_SOLVING:
            return {
                "problem_statement": context.input_data.get("problem_statement", ""),
                "constraints": json.dumps(context.input_data.get("constraints", {})),
                "available_tools": json.dumps(context.input_data.get("available_tools", {}))
            }
        elif context.task_type == CognitiveTaskType.MEMORY_SYNTHESIS:
            return {
                "memory_fragments": json.dumps(context.input_data.get("memory_fragments", [])),
                "synthesis_goal": context.input_data.get("synthesis_goal", "")
            }
        elif context.task_type == CognitiveTaskType.CAPABILITY_ASSESSMENT:
            return {
                "agent_performance_data": json.dumps(context.input_data.get("performance_data", {})),
                "current_capabilities": json.dumps(context.input_data.get("current_capabilities", {})),
                "target_capabilities": json.dumps(context.input_data.get("target_capabilities", {}))
            }
        else:
            raise ValueError(f"Unsupported task type: {context.task_type}")
    
    def _format_result(self, result: Any, context: CognitiveContext) -> Dict[str, Any]:
        """Format the result based on task type using the new centralized schema."""
        task_type = context.task_type
        
        try:
            if task_type == CognitiveTaskType.FAILURE_ANALYSIS:
                return create_cognitive_result(
                    agent_id=context.agent_id,
                    task_type=task_type.value,
                    result={
                        "thought": result.thought,
                        "proposed_solution": result.proposed_solution,
                        "confidence_score": self._safe_float_convert(result.confidence_score)
                    },
                    confidence_score=self._safe_float_convert(result.confidence_score)
                ).model_dump()
            elif task_type == CognitiveTaskType.TASK_PLANNING:
                return create_cognitive_result(
                    agent_id=context.agent_id,
                    task_type=task_type.value,
                    result={
                        "step_by_step_plan": result.step_by_step_plan,
                        "estimated_complexity": result.estimated_complexity,
                        "risk_assessment": result.risk_assessment
                    }
                ).model_dump()
            elif task_type == CognitiveTaskType.DECISION_MAKING:
                return create_cognitive_result(
                    agent_id=context.agent_id,
                    task_type=task_type.value,
                    result={
                        "reasoning": result.reasoning,
                        "decision": result.decision,
                        "confidence": self._safe_float_convert(result.confidence),
                        "alternative_options": result.alternative_options
                    },
                    confidence_score=self._safe_float_convert(result.confidence)
                ).model_dump()
            elif task_type == CognitiveTaskType.PROBLEM_SOLVING:
                return create_cognitive_result(
                    agent_id=context.agent_id,
                    task_type=task_type.value,
                    result={
                        "solution_approach": result.solution_approach,
                        "solution_steps": result.solution_steps,
                        "success_metrics": result.success_metrics
                    }
                ).model_dump()
            elif task_type == CognitiveTaskType.MEMORY_SYNTHESIS:
                return create_cognitive_result(
                    agent_id=context.agent_id,
                    task_type=task_type.value,
                    result={
                        "synthesized_insight": result.synthesized_insight,
                        "confidence_level": self._safe_float_convert(result.confidence_level),
                        "related_patterns": result.related_patterns
                    },
                    confidence_score=self._safe_float_convert(result.confidence_level)
                ).model_dump()
            elif task_type == CognitiveTaskType.CAPABILITY_ASSESSMENT:
                return create_cognitive_result(
                    agent_id=context.agent_id,
                    task_type=task_type.value,
                    result={
                        "capability_gaps": result.capability_gaps,
                        "improvement_plan": result.improvement_plan,
                        "priority_recommendations": result.priority_recommendations
                    }
                ).model_dump()
            else:
                # Return structured result using the new schema
                return create_cognitive_result(
                    agent_id=context.agent_id,
                    task_type=task_type.value,
                    result={
                        "type": "cognitive_result",
                        "result": str(result),
                        "original_type": str(type(result))
                    }
                ).model_dump()
        except Exception as e:
            # Return error result using the new schema
            return create_error_result(
                error=f"Failed to format cognitive result: {str(e)}",
                error_type="formatting_error",
                original_type=str(type(result))
            ).model_dump()
    
    def _safe_float_convert(self, value) -> float:
        """Safely convert a value to float, handling various input types."""
        try:
            if isinstance(value, str):
                return float(value)
            elif isinstance(value, (int, float)):
                return float(value)
            else:
                # If we can't convert, return 1.0 as default
                return 1.0
        except (ValueError, TypeError):
            return 1.0


# =============================================================================
# Global Cognitive Core Instance
# =============================================================================

COGNITIVE_CORE_INSTANCE: Optional[CognitiveCore] = None


def initialize_cognitive_core(llm_provider: str = "openai", model: str = "gpt-4o") -> CognitiveCore:
    """Initialize the global cognitive core instance."""
    global COGNITIVE_CORE_INSTANCE
    
    if COGNITIVE_CORE_INSTANCE is None:
        try:
            # Configure DSPy with the LLM
            if llm_provider == "openai":
                llm = dspy.OpenAI(model=model, max_tokens=1024)
            else:
                # Add support for other providers as needed
                raise ValueError(f"Unsupported LLM provider: {llm_provider}")
            
            dspy.settings.configure(lm=llm)
            COGNITIVE_CORE_INSTANCE = CognitiveCore(llm_provider, model)
            logger.info(f"Initialized global cognitive core with {llm_provider} and {model}")
            
        except Exception as e:
            logger.error(f"Failed to initialize cognitive core: {e}")
            raise
    
    return COGNITIVE_CORE_INSTANCE


def get_cognitive_core() -> Optional[CognitiveCore]:
    """Get the global cognitive core instance."""
    return COGNITIVE_CORE_INSTANCE


def reset_cognitive_core():
    """Reset the global cognitive core instance (useful for testing)."""
    global COGNITIVE_CORE_INSTANCE
    COGNITIVE_CORE_INSTANCE = None 