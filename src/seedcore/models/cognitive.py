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

class CognitiveType(Enum):
    """Cognitive reasoning jobs for CognitiveCore (stateless)."""

    # Core reasoning
    CHAT = "chat"
    PROBLEM_SOLVING = "problem_solving"
    TASK_PLANNING = "task_planning"
    DECISION_MAKING = "decision_making"
    FAILURE_ANALYSIS = "failure_analysis"

    # Memory-based reasoning
    MEMORY_SYNTHESIS = "memory_synthesis"
    CAPABILITY_ASSESSMENT = "capability_assessment"

class LLMProfile(str, Enum):
    """
    Infrastructure-level resource definitions.
    
    This maps to specific model families (e.g., GPT-4o-mini vs GPT-4o) 
    and determines timeouts, retry logic, and cost tracking.
    """
    
    # High throughput, low latency, lower cost.
    # Targets: GPT-4o-mini, Claude Haiku, Llama-3-8B
    # Use for: Chat, Summarization, Extraction, Simple Tools.
    FAST = "fast"

    # High reasoning, large context, higher latency/cost.
    # Targets: GPT-4o, Claude Sonnet/Opus, Llama-3-70B/405B
    # Use for: Planning, HGNN, Complex Analysis, Coding.
    DEEP = "deep"

    # (Optional) Future-proofing for O1/DeepSeek-R1 style models
    # REASONING = "reasoning"

# --- This is the "Payload" (The Full Request) ---
@dataclass
class CognitiveContext:
    agent_id: str
    cog_type: CognitiveType
    input_data: Dict[str, Any]
    memory_context: Optional[Dict[str, Any]] = None
    energy_context: Optional[Dict[str, Any]] = None
    lifecycle_context: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if not self.cog_type:
            raise ValueError("CognitiveContext requires a valid cog_type")
        if self.input_data is None:
            self.input_data = {}

    @property
    def decision_kind(self) -> DecisionKind:
        """Extracts decision kind from TaskPayload v2 params."""
        # 1. Check v2 envelope
        params = self.input_data.get("params", {})
        if "cognitive" in params:
            kind = params["cognitive"].get("decision_kind")
            if kind:
                try:
                    return DecisionKind(kind)
                except ValueError:
                    pass
        
        # 2. Check legacy top-level
        kind = self.input_data.get("meta", {}).get("decision_kind")
        try:
            return DecisionKind(kind) if kind else DecisionKind.FAST_PATH
        except ValueError:
            return DecisionKind.FAST_PATH

    @property
    def requested_profile_override(self) -> Optional[LLMProfile]:
        """
        Checks if the payload explicitly requests a specific hardware profile.
        This allows 'force_deep_reasoning' logic to work.
        """
        cog_params = self.input_data.get("params", {}).get("cognitive", {})
        
        # Explicit flag in v2 payload
        if cog_params.get("force_deep_reasoning"):
            return LLMProfile.DEEP
            
        return None

# Backward compatibility alias (to be deprecated)
CognitiveTaskType = CognitiveType

# ... you would also put other shared models here ...
# from ..models.fact import Fact
