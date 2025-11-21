from __future__ import annotations
import dspy

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
# Mixins and Base Signatures
# =============================================================================

class WithKnowledgeMixin:
    """
    A mixin to add a standardized knowledge context field to any signature.
    This data is for read-only context.
    """
    knowledge_context = dspy.InputField(
        desc=("A JSON object containing relevant, non-executable facts with provenance, "
              "a summary, and a usage policy. This data is for context only. "
              "It may also contain an 'hgnn_embedding' key, which represents "
              "deep graph context from the 'ESCALATED' (hgnn) path.")
    )

# =============================================================================
# Production-Level DSPy Signatures
# =============================================================================

class AnalyzeFailureSignature(WithKnowledgeMixin, dspy.Signature):
    """Analyze agent failures and propose a structured solution."""
    
    incident_context = dspy.InputField(
        desc=("A JSON string describing the failure. "
              "Schema: {'agent_id': str, 'failed_task': dict, 'error': str, 'timestamp': str}")
    )
    
    thought = dspy.OutputField(
        desc="Step-by-step reasoning. Analyze the root cause, contributing factors, "
             "and how the knowledge context (especially historical facts) informs your plan."
    )
    
    solution_steps = dspy.OutputField(
        desc=("A JSON list of dictionaries for the corrective plan. "
              "Schema: [{'step': int, 'action': str, 'description': str, 'target_agent': str}]"),
        prefix="```json\n"
    )
    
    confidence_score = dspy.OutputField(
        desc="A single floating-point number between 0.0 and 1.0 (e.g., 0.9)."
    )
    
    risk_factors = dspy.OutputField(
        desc="A brief text summary of identified risk factors and potential failure modes from the knowledge context."
    )


class TaskPlanningSignature(WithKnowledgeMixin, dspy.Signature):
    """
    Decompose a complex task description into a structured, multi-step plan
    for the Coordinator to execute.
    """
    
    task_description = dspy.InputField(
        desc="High-level description of the task to be planned."
    )
    
    agent_capabilities = dspy.InputField(
        desc=("JSON string describing the agent's capabilities. "
              "Schema: {'tools': ['tool_name_1', ...], 'skills': ['skill_1', ...]}")
    )
    
    available_resources = dspy.InputField(
        desc=("JSON string describing available resources. "
              "Schema: {'memory_cells': ['cell_id_1', ...], 'available_gpus': int}")
    )
    
    thought = dspy.OutputField(
        desc="Step-by-step reasoning. Analyze the task, constraints, and resources. "
             "Break down the problem. Use the knowledge context (especially the hgnn_embedding, if present) "
             "to inform the plan structure. Finally, generate the JSON plan."
    )
    
    solution_steps = dspy.OutputField(
        desc=("A JSON list of dictionaries for the plan. "
              "Schema: [{'step': int, 'tool_to_call': str, 'params': dict, 'description': str}]"),
        prefix="```json\n"
    )
    
    estimated_complexity = dspy.OutputField(
        desc="A single integer between 1 and 10, representing the plan's complexity."
    )


class DecisionMakingSignature(WithKnowledgeMixin, dspy.Signature):
    """Evaluate a set of options and select the single best one."""
    
    decision_context = dspy.InputField(
        desc=("JSON string containing the decision to be made and all available options. "
              "Schema: {'question': 'Which VM should we use?', "
              "'options': [{'id': 'A', 'desc': 'VM-Large'}, {'id': 'B', 'desc': 'VM-Small'}]}")
    )
    
    historical_data = dspy.InputField(
        desc=("JSON string of relevant historical data. "
              "Schema: [{'past_decision': 'A', 'outcome': 'Success', 'cost': 1.0}, ...]")
    )
    
    thought = dspy.OutputField(
        desc="Step-by-step reasoning. Evaluate each option against the historical data "
             "and knowledge context. State the pros and cons of each. Conclude with the best choice."
    )
    
    decision = dspy.OutputField(
        desc="The single 'id' of the chosen option from the decision_context (e.g., 'A')."
    )
    
    confidence = dspy.OutputField(
        desc="A single floating-point number between 0.0 and 1.0 (e.g., 0.75)."
    )


class ProblemSolvingSignature(WithKnowledgeMixin, dspy.Signature):
    """
    Given an open-ended problem, generate a structured, multi-step plan.
    This is the default handler for the 'hgnn' (ESCALATED) path.
    """
    
    problem_statement = dspy.InputField(
        desc="Clear, high-level statement of the problem to be solved (e.g., 'Analyze Q3 sales dip')."
    )
    
    constraints = dspy.InputField(
        desc=("JSON string describing constraints. "
              "Schema: {'max_time_ms': 5000, 'allowed_tools': ['...'], 'priority': 'high'}")
    )
    
    available_tools = dspy.InputField(
        desc=("JSON string describing available tools (functions) the plan can use. "
              "Schema: {'tool_name_1': {'desc': '...', 'params': {'arg1': 'type'}}, ...}")
    )
    
    thought = dspy.OutputField(
        desc="Step-by-step reasoning. Analyze the problem, constraints, and tools. "
             "Pay close attention to the 'knowledge_context', especially the 'hgnn_embedding' if present, "
             "as it contains critical information from historical tasks. "
             "Formulate a high-level approach, then break it down into concrete steps using the available tools. "
             "Finally, generate the JSON plan."
    )
    
    solution_steps = dspy.OutputField(
        desc=("A JSON list of dictionaries for the solution plan. This will be parsed and "
              "executed by the Coordinator. "
              "Schema: [{'step': int, 'tool_to_call': str, 'params': dict, 'description': str}]"),
        prefix="```json\n"
    )
    
    success_metrics = dspy.OutputField(
        desc="A brief text description of 1-3 metrics to measure the solution's success."
    )


class ChatSignature(WithKnowledgeMixin, dspy.Signature):
    """
    Lightweight conversational path for chat-based interactions.
    Provides natural language responses based on user messages and knowledge context.
    """
    
    message = dspy.InputField(
        desc="The user's message or question to respond to."
    )
    
    conversation_history = dspy.InputField(
        desc=("Optional JSON string containing recent conversation history. "
              "Schema: [{'role': 'user'|'assistant', 'content': '...'}, ...]")
    )
    
    response = dspy.OutputField(
        desc="A natural, conversational response to the user's message. "
             "Use the knowledge context to provide accurate and helpful information. "
             "Keep responses concise and relevant."
    )
    
    confidence = dspy.OutputField(
        desc="A single floating-point number between 0.0 and 1.0 indicating confidence in the response."
    )


class MemorySynthesisSignature(WithKnowledgeMixin, dspy.Signature):
    """Synthesize a single, actionable insight from multiple memory fragments."""
    
    memory_fragments = dspy.InputField(
        desc=("JSON string. A list of memory fragments to synthesize. "
              "Schema: [{'source': 'task_123', 'content': '...'}, {'source': 'agent_abc', 'content': '...'}]")
    )
    
    synthesis_goal = dspy.InputField(
        desc="The specific goal of the synthesis (e.g., 'Find a common failure pattern', 'Identify new opportunities')."
    )
    
    thought = dspy.OutputField(
        desc="Step-by-step reasoning. Analyze the fragments in light of the goal and knowledge context. "
             "Identify connections, contradictions, and emerging patterns. Formulate a final insight."
    )
    
    synthesized_insight = dspy.OutputField(
        desc="A concise, actionable insight or pattern derived from the fragments."
    )
    
    confidence_level = dspy.OutputField(
        desc="A single floating-point number between 0.0 and 1.0 (e.g., 0.8)."
    )


class CapabilityAssessmentSignature(WithKnowledgeMixin, dspy.Signature):
    """Assess an agent's capabilities and generate a plan for improvement."""
    
    agent_performance_data = dspy.InputField(
        desc=("JSON string. "
              "Schema: {'task_history': [{'task': '...', 'success': bool}], 'success_rate': 0.8}")
    )
    
    current_capabilities = dspy.InputField(
        desc="JSON string. Schema: {'skills': ['skill_A', 'skill_B']}"
    )
    
    target_capabilities = dspy.InputField(
        desc="JSON string. Schema: {'skills': ['skill_A', 'skill_B', 'skill_C']}"
    )
    
    thought = dspy.OutputField(
        desc="Step-by-step reasoning. Compare current vs. target capabilities. "
             "Analyze performance data and knowledge context to identify gaps. "
             "Formulate an improvement plan."
    )
    
    capability_gaps = dspy.OutputField(
        desc="A concise text summary of the identified gaps (e.g., 'Missing skill_C, low success in skill_A')."
    )
    
    solution_steps = dspy.OutputField(
        desc=("A JSON list of dictionaries for the improvement plan. "
              "Schema: [{'step': int, 'action': str, 'metric': str, 'description': str}]"),
        prefix="```json\n"
    )


class HGNNReasoningSignature(dspy.Signature):
    """
    Performs deep diagnosis based on Hypergraph structural anomalies.
    Analyses why a specific task vector drifted from the norm.
    """
    
    # Input: The Translation of the Vector (From Phase 1)
    structural_context = dspy.InputField(
        desc="List of graph nodes and edges found near the anomaly vector."
    )
    
    # Input: The Raw Anomaly Data (From ML Service)
    anomaly_description = dspy.InputField(
        desc="The raw error logs or timeseries data that triggered the surprise."
    )
    
    # Chain of Thought
    structural_analysis = dspy.OutputField(
        desc="Analyze the relationship between the retrieved nodes. Are they shared dependencies? Is there a bottleneck?"
    )
    
    root_cause_hypothesis = dspy.OutputField(
        desc="The most likely root cause based on the structural proximity of the nodes."
    )
    
    mitigation_plan = dspy.OutputField(
        desc="A step-by-step plan to fix the structural issue."
    )


class CausalDecompositionSignature(WithKnowledgeMixin, dspy.Signature):
    """
    Decompose a high-entropy event into interdependent sub-tasks across organs.
    
    This signature is used by the Cognitive Core to break down complex incidents
    (like the hotel Presidential Suite incident) into a structured execution plan
    with explicit dependencies between tasks assigned to different organs.
    """
    
    structural_context = dspy.InputField(
        desc="Graph neighbors (e.g., 'Room 404', 'DoorLock', 'GuestProfile'). "
              "These represent the entities and relationships in the knowledge graph "
              "that are relevant to the incident."
    )
    
    incident_report = dspy.InputField(
        desc="The raw guest call transcript or incident description. "
              "This contains the unstructured narrative of what happened."
    )
    
    # The Output is a Structured Dependency List
    # Format: "TaskID | Organ | Action | DependsOn"
    execution_plan = dspy.OutputField(
        desc=("List of subtasks in structured format. "
              "Each line follows: 'TaskID | Organ | Action | DependsOn' "
              "Example: 'T1 | Security | Override Lock | None', "
              "'T2 | Engineering | Replace Battery | T1' "
              "Use 'None' for tasks with no dependencies. "
              "The knowledge context may contain historical patterns and organ capabilities "
              "to inform the decomposition.")
    )