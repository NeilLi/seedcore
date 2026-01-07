from __future__ import annotations
import dspy  # pyright: ignore[reportMissingImports]

__all__ = [
    "WithKnowledgeMixin",
    "AnalyzeFailureSignature",
    "TaskPlanningSignature",
    "DecisionMakingSignature",
    "ProblemSolvingSignature",
    "ChatSignature",
    "MemorySynthesisSignature",
    "CapabilityAssessmentSignature",
    "HGNNReasoningSignature",
    "CausalDecompositionSignature",
]

# =============================================================================
# Mixins and Shared Fields
# =============================================================================

class WithKnowledgeMixin:
    """
    A mixin providing structured read-only knowledge context:
    {
        "holons": [...],
        "episodic_context": [...],
        "global_context": [...],
        "hgnn_embedding": [...],  # optional deep graph embedding
        "provenance": "...",
        "summary": "...",
        "usage_policy": "..."
    }
    """
    knowledge_context = dspy.InputField(
        desc="Structured read-only context from MemoryBridge (holons, episodic memory, global memory, hgnn embeddings)."
    )


# =============================================================================
# Core Cognitive Signatures
# =============================================================================

class AnalyzeFailureSignature(WithKnowledgeMixin, dspy.Signature):
    """
    Analyze agent or system failures and produce structured explanation + plan.
    """

    incident_context = dspy.InputField(
        desc=(
            "Failure metadata:\n"
            "{'agent_id': str, 'failed_task': dict, 'error': str, 'timestamp': str}"
        )
    )

    thought = dspy.OutputField(
        desc="Step-by-step reasoning. Analyze root cause, contributing factors, and use knowledge_context evidence."
    )

    solution_steps = dspy.OutputField(
        desc="List of corrective actions. Schema: [{'step': int, 'action': str, 'description': str, 'target_agent': str}]",
        prefix="```json\n"
    )

    risk_factors = dspy.OutputField(
        desc="Brief summary of high-risk or recurring failure patterns found in knowledge_context."
    )

    confidence_score = dspy.OutputField(
        desc="Float in [0,1] representing confidence in the analysis."
    )


class TaskPlanningSignature(WithKnowledgeMixin, dspy.Signature):
    """
    Decompose a high-level task into a structured multi-step execution plan.
    """

    task_description = dspy.InputField(
        desc="High-level natural language task description."
    )

    agent_capabilities = dspy.InputField(
        desc="Structured capabilities dict. {'tools': [...], 'skills': [...]}."
    )

    available_resources = dspy.InputField(
        desc="Resource dict. {'memory_cells': [...], 'available_gpus': int}."
    )

    thought = dspy.OutputField(
        desc="Chain-of-thought. Interpret task, constraints, capabilities, and knowledge_context to build the plan."
    )

    solution_steps = dspy.OutputField(
        desc="A structured step plan. [{'step': int, 'tool_to_call': str, 'params': dict, 'description': str}]",
        prefix="```json\n"
    )

    estimated_complexity = dspy.OutputField(
        desc="Complexity estimate from 1 to 10."
    )


class DecisionMakingSignature(WithKnowledgeMixin, dspy.Signature):
    """
    Evaluate options and pick the best choice.
    """

    decision_context = dspy.InputField(
        desc=(
            "Decision problem. Example:\n"
            "{'question': 'Which VM?', 'options': [{'id':'A', 'desc':'VM-Large'}, ...]}"
        )
    )

    historical_data = dspy.InputField(
        desc="Past decision outcomes. [{'past_decision': 'A', 'outcome': 'Success', 'cost': 1.2}, ...]"
    )

    thought = dspy.OutputField(
        desc="Evaluate each option using evidence from history + knowledge_context. Give reasoning."
    )

    decision = dspy.OutputField(
        desc="Selected option id (e.g., 'A')."
    )

    confidence = dspy.OutputField(
        desc="Float in [0,1] representing confidence."
    )


class ProblemSolvingSignature(WithKnowledgeMixin, dspy.Signature):
    """
    Deep reasoning handler (default for COGNITIVE pipeline).
    """

    problem_statement = dspy.InputField(
        desc="Natural language problem statement (e.g., 'Improve Q3 sales')."
    )

    constraints = dspy.InputField(
        desc="Constraints dict. Example: {'max_time_ms': 5000, 'priority': 'high'}."
    )

    available_tools = dspy.InputField(
        desc="Dict describing available tools: {'tool': {'desc':..., 'params': {...}}}."
    )

    thought = dspy.OutputField(
        desc="Concise chain-of-thought connecting context, constraints, and tools. Keep under 50 tokens for simple queries. Only elaborate for complex multi-step problems."
    )

    solution_steps = dspy.OutputField(
        desc="Structured solution plan. [{'step': int, 'tool_to_call': str, 'params': dict, 'description': str}]",
        prefix="```json\n"
    )

    success_metrics = dspy.OutputField(
        desc="1–3 metrics for evaluating solution success."
    )


# =============================================================================
# Chat Signature
# =============================================================================

class ChatSignature(WithKnowledgeMixin, dspy.Signature):
    """
    Lightweight conversational signature for agent_tunnel mode (FAST_PATH).
    """

    message = dspy.InputField(
        desc="User message."
    )

    conversation_history = dspy.InputField(
        desc="List of recent conversation turns: [{'role': 'user'|'assistant', 'content': str}, ...]."
    )

    response = dspy.OutputField(
        desc="Natural, concise conversational response."
    )

    confidence = dspy.OutputField(
        desc="Float in [0,1] representing certainty."
    )


# =============================================================================
# Memory Synthesis and Capability Assessment
# =============================================================================

class MemorySynthesisSignature(WithKnowledgeMixin, dspy.Signature):
    """
    Produce a synthesized insight from multiple memory fragments.
    """

    memory_fragments = dspy.InputField(
        desc="List of memory fragments: [{'source': str, 'content': str}, ...]."
    )

    synthesis_goal = dspy.InputField(
        desc="Goal of synthesis (e.g., 'Find failure patterns')."
    )

    thought = dspy.OutputField(
        desc="Detailed reasoning referencing knowledge_context."
    )

    synthesized_insight = dspy.OutputField(
        desc="Concise actionable insight."
    )

    confidence_level = dspy.OutputField(
        desc="Float in [0,1]."
    )


class CapabilityAssessmentSignature(WithKnowledgeMixin, dspy.Signature):
    """
    Evaluate capabilities and propose an improvement plan.
    """

    agent_performance_data = dspy.InputField(
        desc="Task history + success metrics. {'task_history': [...], 'success_rate': float}."
    )

    current_capabilities = dspy.InputField(
        desc="Dict of current skills. {'skills': [...]}."
    )

    target_capabilities = dspy.InputField(
        desc="Dict of target skills. {'skills': [...]}."
    )

    thought = dspy.OutputField(
        desc="Compare current vs target using knowledge_context. Identify capability gaps."
    )

    capability_gaps = dspy.OutputField(
        desc="Summary of identified gaps."
    )

    solution_steps = dspy.OutputField(
        desc="Improvement plan. [{'step': int, 'action': str, 'metric': str, 'description': str}]",
        prefix="```json\n"
    )


# =============================================================================
# Escalated / HGNN Signatures
# =============================================================================

class HGNNReasoningSignature(WithKnowledgeMixin, dspy.Signature):
    """
    Hypergraph-based escalated reasoning for anomaly or structural drift.
    """

    structural_context = dspy.InputField(
        desc="Graph neighbors, structural embedding context, or hypergraph slices relevant to anomaly."
    )

    anomaly_description = dspy.InputField(
        desc="Raw anomaly description or logs causing escalation."
    )

    thought = dspy.OutputField(
        desc="Deep structural reasoning using hgnn_embedding from knowledge_context."
    )

    root_cause_hypothesis = dspy.OutputField(
        desc="Hypothesized root cause."
    )

    mitigation_plan = dspy.OutputField(
        desc="Step-by-step remediation plan."
    )


class CausalDecompositionSignature(WithKnowledgeMixin, dspy.Signature):
    """
    Decompose high-entropy events into dependency-ordered sub-tasks.
    """

    structural_context = dspy.InputField(
        desc="Entities and relationships relevant to incident (e.g., ['Room 404','DoorLock'])."
    )

    incident_report = dspy.InputField(
        desc="Unstructured narrative of the incident (guest call transcript, logs)."
    )

    thought = dspy.OutputField(
        desc="Reasoning: correlate structural context with incident narrative and knowledge_context."
    )

    execution_plan = dspy.OutputField(
        desc=(
            "Dependency-ordered subtasks.\n"
            "Format (one per line): 'TaskID | Organ | Action | DependsOn'\n"
            "Example:\n"
            "T1 | Security | Override Lock | None\n"
            "T2 | Engineering | Replace Battery | T1\n"
        )
    )
