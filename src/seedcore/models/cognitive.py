from enum import Enum
from dataclasses import dataclass
from typing import Any, Dict, Optional

# --- This is the "How" (The Pipeline) ---
class DecisionKind(str, Enum):
    """Canonical routing or processing path kinds across Coordinator and Cognitive subsystems."""
    FAST_PATH = "fast"          # Direct organism execution
    COGNITIVE = "planner"       # Reasoning route on cognitive
    ESCALATED = "hgnn"          # HGNN-based multi-plan decomposition (legacy escalation path)
    ERROR = "error"             # Fallback or failure condition

# --- This is the "What" (The Job) ---
class CognitiveType(Enum):
    """The specific job to be performed by the CognitiveCore."""

    # Core reasoning tasks
    FAILURE_ANALYSIS = "failure_analysis"
    TASK_PLANNING = "task_planning"
    DECISION_MAKING = "decision_making"
    PROBLEM_SOLVING = "problem_solving"
    MEMORY_SYNTHESIS = "memory_synthesis"
    CAPABILITY_ASSESSMENT = "capability_assessment"

    # Graph tasks
    GRAPH_EMBED = "graph_embed"
    GRAPH_RAG_QUERY = "graph_rag_query"
    GRAPH_SYNC_NODES = "graph_sync_nodes"

    # Facts system
    GRAPH_FACT_EMBED = "graph_fact_embed"
    GRAPH_FACT_QUERY = "graph_fact_query"
    FACT_SEARCH = "fact_search"
    FACT_STORE = "fact_store"

    # Resource management
    ARTIFACT_MANAGE = "artifact_manage"
    CAPABILITY_MANAGE = "capability_manage"
    MEMORY_CELL_MANAGE = "memory_cell_manage"

    # Agent layer
    MODEL_MANAGE = "model_manage"
    POLICY_MANAGE = "policy_manage"
    SERVICE_MANAGE = "service_manage"
    SKILL_MANAGE = "skill_manage"


# --- This is the "Payload" (The Full Request) ---
@dataclass(init=False)
class CognitiveContext:
    """The standard request payload for the CognitiveService."""

    agent_id: str
    cog_type: CognitiveType
    input_data: Dict[str, Any]
    memory_context: Optional[Dict[str, Any]] = None
    energy_context: Optional[Dict[str, Any]] = None
    lifecycle_context: Optional[Dict[str, Any]] = None

    def __init__(
        self,
        agent_id: str,
        *,
        cog_type: Optional[CognitiveType] = None,
        input_data: Optional[Dict[str, Any]] = None,
        memory_context: Optional[Dict[str, Any]] = None,
        energy_context: Optional[Dict[str, Any]] = None,
        lifecycle_context: Optional[Dict[str, Any]] = None,
        task_type: Optional[CognitiveType] = None,
    ) -> None:
        resolved_type = cog_type or task_type
        if resolved_type is None:
            raise ValueError("CognitiveContext requires cog_type or task_type")

        self.agent_id = agent_id
        self.cog_type = resolved_type
        self.input_data = input_data or {}
        self.memory_context = memory_context
        self.energy_context = energy_context
        self.lifecycle_context = lifecycle_context

    @property
    def task_type(self) -> CognitiveType:
        """Backward-compatible alias for cog_type."""
        return self.cog_type

    @task_type.setter
    def task_type(self, value: CognitiveType) -> None:
        self.cog_type = value

# Backward compatibility alias (to be deprecated)
CognitiveTaskType = CognitiveType

# ... you would also put other shared models here ...
# from ..models.fact import Fact
