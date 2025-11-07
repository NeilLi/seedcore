# =============================================================================
# DSPy Signatures
# =============================================================================

from __future__ import annotations

import dspy

__all__ = [
    "WithKnowledgeMixin",
    "AnalyzeFailureSignature",
    "TaskPlanningSignature",
    "DecisionMakingSignature",
    "ProblemSolvingSignature",
    "MemorySynthesisSignature",
    "CapabilityAssessmentSignature",
]


class WithKnowledgeMixin:
    """A mixin to add a standardized knowledge context field to any signature."""
    knowledge_context = dspy.InputField(
        desc="A JSON object containing relevant, non-executable facts with provenance, a summary, and a usage policy. This data is for context only."
    )


class AnalyzeFailureSignature(WithKnowledgeMixin, dspy.Signature):
    """Analyze agent failures and propose solutions with historical context."""
    incident_context = dspy.InputField(
        desc="A JSON string containing the agent's state, failed task, and error context."
    )
    thought = dspy.OutputField(
        desc="Reasoned analysis of root cause and contributing factors, considering the knowledge context."
    )
    proposed_solution = dspy.OutputField(
        desc="Actionable plan to prevent recurrence and improve agent performance, based on historical facts."
    )
    confidence_score = dspy.OutputField(
        desc="Confidence in the analysis (0.0 to 1.0)."
    )
    risk_factors = dspy.OutputField(
        desc="Identified risk factors and potential failure modes from the knowledge context."
    )


class TaskPlanningSignature(WithKnowledgeMixin, dspy.Signature):
    """Plan complex tasks with multiple steps, informed by system facts."""
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
        desc="Detailed step-by-step plan to accomplish the task, considering the provided knowledge context."
    )
    estimated_complexity = dspy.OutputField(
        desc="Estimated complexity score (1-10) and reasoning."
    )
    risk_assessment = dspy.OutputField(
        desc="Assessment of potential risks and mitigation strategies."
    )


class DecisionMakingSignature(WithKnowledgeMixin, dspy.Signature):
    """Make decisions based on available information and context."""
    decision_context = dspy.InputField(
        desc="JSON string containing the decision context, options, and constraints."
    )
    historical_data = dspy.InputField(
        desc="JSON string containing relevant historical data and patterns."
    )
    reasoning = dspy.OutputField(
        desc="Detailed reasoning process for the decision, considering the knowledge context."
    )
    decision = dspy.OutputField(
        desc="The chosen decision with justification, considering the knowledge context."
    )
    confidence = dspy.OutputField(
        desc="Confidence level in the decision (0.0 to 1.0)."
    )
    alternative_options = dspy.OutputField(
        desc="Alternative options considered and why they were not chosen."
    )


class ProblemSolvingSignature(WithKnowledgeMixin, dspy.Signature):
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
        desc="Systematic approach to solving the problem, considering the knowledge context."
    )
    solution_steps = dspy.OutputField(
        desc="Detailed steps to implement the solution."
    )
    success_metrics = dspy.OutputField(
        desc="Metrics to measure solution success."
    )


class MemorySynthesisSignature(WithKnowledgeMixin, dspy.Signature):
    """Synthesize information from multiple memory sources."""
    memory_fragments = dspy.InputField(
        desc="JSON string containing multiple memory fragments to synthesize."
    )
    synthesis_goal = dspy.InputField(
        desc="Goal of the memory synthesis (e.g., pattern recognition, insight generation)."
    )
    synthesized_insight = dspy.OutputField(
        desc="Synthesized insight or pattern from the memory fragments, considering the knowledge context."
    )
    confidence_level = dspy.OutputField(
        desc="Confidence in the synthesis (0.0 to 1.0)."
    )
    related_patterns = dspy.OutputField(
        desc="Related patterns or insights that emerged during synthesis."
    )


class CapabilityAssessmentSignature(WithKnowledgeMixin, dspy.Signature):
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
        desc="Identified gaps between current and target capabilities, considering the knowledge context."
    )
    improvement_plan = dspy.OutputField(
        desc="Detailed plan to improve agent capabilities."
    )
    priority_recommendations = dspy.OutputField(
        desc="Priority recommendations for capability development."
    )
