from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Any, List


class IntentSource(str, Enum):
    """Provenance of intent extraction."""

    TASK_PAYLOAD_ROUTING = "task_payload.routing"  # TaskPayload params.routing (instance-level hard constraint)
    PKG_TOP_LEVEL = "pkg.top_level"
    PKG_STEP_EMBEDDED = "pkg.step[0]"
    PKG_AGGREGATED = "pkg.aggregated"
    COORDINATOR_BASELINE = "coordinator.baseline"  # NEW: Perception-based fallback
    LEGACY_RESOLVER = "legacy.resolver"
    FALLBACK_NEUTRAL = "fallback.neutral"


class IntentConfidence(str, Enum):
    """Confidence level of intent extraction."""

    HIGH = "high"  # Explicit PKG + Semantic Match
    MEDIUM = "medium"  # Inferred from hints or strong perception
    LOW = "low"  # Conflicting signals
    MINIMAL = "minimal"  # No hints, pure fallback


@dataclass
class RoutingIntent:
    """
    Internal DTO for routing instructions.
    Modified for v2.5 to support Semantic Enrichment.
    """

    specialization: Optional[str] = None
    organ_hint: Optional[str] = None
    skills: Dict[str, float] = field(default_factory=dict)

    source: IntentSource = IntentSource.FALLBACK_NEUTRAL
    confidence: IntentConfidence = IntentConfidence.MINIMAL

    # NEW: Carry forward grounded metadata (e.g., grounded_time, camera_id)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_explicit(self) -> bool:
        return self.source in (
            IntentSource.TASK_PAYLOAD_ROUTING,
            IntentSource.PKG_TOP_LEVEL,
            IntentSource.PKG_STEP_EMBEDDED,
            IntentSource.PKG_AGGREGATED,
        )

    def to_routing_params(self) -> Dict[str, Any]:
        """Generates the authoritative 'routing' envelope for TaskPayload."""
        params = {
            "required_specialization": self.specialization
            if self.is_explicit()
            else None,
            "specialization": self.specialization if not self.is_explicit() else None,
            "skills": self.skills,
            "provenance": {
                "source": self.source.value,
                "confidence": self.confidence.value,
            },
        }
        # Inject metadata for downstream Organism usage
        if self.metadata:
            params["context_grounding"] = self.metadata
        return {k: v for k, v in params.items() if v is not None}


@dataclass(frozen=True)
class IntentInsight:
    """
    Cognitive audit trail explaining why the system made a routing decision.
    
    This structured insight synthesizes Perception (Eventizer), Memory (Cortex),
    and Policy (PKG) signals into a human-readable narrative.
    
    Attributes:
        summary: Human-readable explanation of the routing decision
        primary_driver: Main signal source ('policy', 'memory', or 'perception')
        confidence_score: Overall confidence (0.0 - 1.0)
        grounding_hits: Number of historical memories used for grounding
        is_escalated: Whether OCPS triggered System 2 escalation
        perception_signals: Breakdown of Eventizer signals (x1..x6)
        policy_rules: List of PKG rules that matched
        memory_context: Count of semantic context items used
    """
    
    summary: str  # Human-readable explanation
    primary_driver: str  # 'policy', 'memory', or 'perception'
    confidence_score: float  # 0.0 - 1.0
    grounding_hits: int  # Number of historical memories used
    is_escalated: bool  # Whether OCPS triggered System 2
    
    # Detailed breakdown (optional)
    perception_signals: Dict[str, float] = field(default_factory=dict)
    policy_rules: List[str] = field(default_factory=list)
    memory_context: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "summary": self.summary,
            "primary_driver": self.primary_driver,
            "confidence_score": self.confidence_score,
            "grounding_hits": self.grounding_hits,
            "is_escalated": self.is_escalated,
            "perception_signals": self.perception_signals,
            "policy_rules": self.policy_rules,
            "memory_context": self.memory_context,
        }
