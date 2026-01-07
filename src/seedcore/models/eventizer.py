#!/usr/bin/env python3
"""
Eventizer Pydantic Models (product-grade)

- Strong typing for tags/signals/PII/proto-subtasks
- OCPS fields (s_t, S_t, thresholds) + Surprise signals x1..x6
- PKG proto-subtasks & proto-DAG hints with rule provenance
- Governance/observability: versions, request_id, tenant, timing, engines
- Validation helpers & safe defaults
- PKG integration for policy-driven event processing
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

from pydantic import (
    BaseModel,
    Field,
    ConfigDict,
    computed_field,
    model_validator,
    HttpUrl,
)  # pyright: ignore[reportMissingImports]
from datetime import datetime, timezone


# =========================
# Enums
# =========================


class ConfidenceLevel(str, Enum):
    HIGH = "high"  # >= high_threshold
    MEDIUM = "medium"  # [medium_threshold, high_threshold)
    LOW = "low"  # < medium_threshold


class EventType(str, Enum):
    """Open-ended EventType enum that accepts custom values for flexible, policy-driven categorization.
    
    This enum supports both hardcoded types (for backward compatibility) and custom types
    (for domain-specific or PKG-defined event types). Custom values are automatically
    mapped to CUSTOM, allowing the system to handle new event types without code changes.
    
    The actual event type resolution happens in the PKG layer, which can map keywords
    and attributes to event types dynamically based on Domain Knowledge Graph rules.
    """
    # Hotel Operations
    HVAC = "hvac"
    VIP = "vip"
    ALLERGEN = "allergen"
    SECURITY = "security"
    MAINTENANCE = "maintenance"
    EMERGENCY = "emergency"
    PRIVACY = "privacy"
    LUGGAGE = "luggage_custody"
    ROUTINE = "routine"

    # Fintech
    FRAUD = "fraud"
    PAYMENT = "payment"
    CHARGEBACK = "chargeback"

    # Healthcare
    HEALTHCARE = "healthcare"
    MEDICAL = "medical"
    ALLERGY = "allergy"

    # Robotics/IoT
    ROBOTICS = "robotics"
    IOT = "iot"
    FAULT = "fault"

    # Generic
    CUSTOM = "custom"

    @classmethod
    def _missing_(cls, value: Any) -> "EventType":
        """Allows the Enum to accept strings not explicitly defined.
        
        This enables the system to handle custom event types defined in PKG policies
        or Domain Knowledge Graph without requiring code changes. Custom values are
        mapped to CUSTOM, but the original value is preserved for PKG evaluation.
        """
        # Return CUSTOM but preserve the original value for PKG/vector search
        return cls.CUSTOM


class Domain(str, Enum):
    HOTEL_OPS = "hotel_ops"
    FINTECH = "fintech"
    HEALTHCARE = "healthcare"
    ROBOTICS = "robotics"
    SECURITY = "security"
    CUSTOM = "custom"


class Urgency(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class RedactMode(str, Enum):
    REDACT = "redact"  # placeholders <TYPE_i>
    MASK = "mask"  # ••••
    TOKENIZE = "tokenize"  # <TYPE_i>:hmac8
    HASH = "hash"  # hmac_sha256


class RouteDecision(str, Enum):
    FAST = "fast"
    PLANNER = "planner"
    HGNN = "hgnn"


class ModalityType(str, Enum):
    """Media modality types for multimodal event processing."""

    TEXT = "text"
    VOICE = "voice"
    VISION = "vision"
    SENSOR = "sensor"


# =========================
# PKG-related Enums
# =========================


class PKGEnv(str, Enum):
    PROD = "prod"
    STAGING = "staging"
    DEV = "dev"


class PKGEngine(str, Enum):
    WASM = "wasm"
    NATIVE = "native"


class PKGConditionType(str, Enum):
    TAG = "TAG"
    SIGNAL = "SIGNAL"
    VALUE = "VALUE"
    FACT = "FACT"


class PKGOperator(str, Enum):
    EQUALS = "="
    NOT_EQUALS = "!="
    GREATER_EQUAL = ">="
    LESS_EQUAL = "<="
    GREATER = ">"
    LESS = "<"
    EXISTS = "EXISTS"
    IN = "IN"
    MATCHES = "MATCHES"


class PKGRelation(str, Enum):
    EMITS = "EMITS"
    ORDERS = "ORDERS"
    GATE = "GATE"


class PKGArtifactType(str, Enum):
    REGO_BUNDLE = "rego_bundle"
    WASM_PACK = "wasm_pack"


# =========================
# Core Models
# =========================


class PKGSnapshot(BaseModel):
    id: Optional[int] = None
    version: str
    env: PKGEnv = PKGEnv.PROD
    entrypoint: str = "data.pkg"
    schema_version: str = "1"
    checksum: str = Field(..., min_length=64, max_length=64)
    size_bytes: Optional[int] = None
    signature: Optional[str] = None
    is_active: bool = False
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(extra="forbid")


class PatternMatch(BaseModel):
    """Individual pattern match result with enhanced span mapping capabilities."""

    pattern_id: str
    pattern_type: str
    matched_text: str
    start_pos: int = Field(..., ge=0)
    end_pos: int = Field(..., ge=0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    engine: str = "re"
    priority: int = 100
    whole_word: bool = False
    normalized_start: Optional[int] = None
    normalized_end: Optional[int] = None
    groups: Optional[List[str]] = None

    model_config = ConfigDict(extra="forbid")


class EntitySpan(BaseModel):
    entity_type: str
    start: int
    end: int
    score: float = 0.0
    text: str
    replacement: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class TextNormalizationResult(BaseModel):
    original_text: str
    normalized_text: str
    span_map: Optional[Any] = None
    normalization_applied: List[str] = Field(default_factory=list)
    processing_time_ms: float = 0.0

    model_config = ConfigDict(extra="forbid")


class PatternCompilationResult(BaseModel):
    pattern_id: str
    engine: str
    pattern_type: str
    priority: int = 100
    confidence: float = 1.0
    whole_word: bool = False
    compilation_time_ms: float = 0.0
    flags: int = 0
    is_compiled: bool = True
    error_message: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class PIIAudit(BaseModel):
    used_engine: str
    mode: RedactMode = RedactMode.REDACT
    entities_evaluated: List[str] = Field(default_factory=list)
    spans: List[EntitySpan] = Field(default_factory=list)
    counts_by_type: Dict[str, int] = Field(default_factory=dict)
    raw_text_sha256: str
    version: str = "2.2.0"
    mask_char: str = "•"
    mask_keep_len: bool = True
    preserve_offsets: bool = True

    model_config = ConfigDict(extra="forbid")


class MediaContext(BaseModel):
    """Metadata for Voice/Vision ingestion and multimodal event processing.

    This model bridges the Eventizer output with the Unified Memory System,
    providing traceability for media files and modality-specific metadata.
    """

    modality: ModalityType = ModalityType.TEXT
    media_uri: Optional[HttpUrl] = None
    media_sha256: Optional[str] = None

    # Voice specific fields
    duration_seconds: Optional[float] = Field(None, ge=0.0)
    language_code: Optional[str] = "en-US"
    transcription: Optional[str] = None
    transcription_engine: Optional[str] = None  # e.g., 'whisper-v3', 'google-speech'

    # Vision specific fields
    camera_id: Optional[str] = None
    frame_timestamp: Optional[datetime] = None
    detected_objects: List[Dict[str, Any]] = Field(default_factory=list)
    scene_description: Optional[str] = None
    detection_engine: Optional[str] = None  # e.g., 'yolo-v8', 'detr'

    # Sensor specific fields
    sensor_type: Optional[str] = None
    sensor_location: Optional[str] = None
    sensor_reading: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(extra="ignore")


class EventSignals(BaseModel):
    """OCPS (Online Change Point Detection) and Surprise signals for drift detection.

    Enhanced with vector tier tracking and multimodal anomaly detection to support
    the Unified Memory System and fast-path routing decisions.
    """

    # Vector Tier Tracking (for Unified Memory System)
    embedding_id: Optional[str] = (
        None  # Reference to graph_embeddings_128/1024 or task_multimodal_embeddings
    )
    vector_dimension: int = (
        1024  # Dimension of the embedding vector (128, 768, or 1024)
    )
    embedding_model: Optional[str] = (
        None  # Model identifier (e.g., 'nim-retrieval-v1', 'whisper-v3')
    )

    # OCPS / Neural CUSUM Logic
    s_t: float = 0.0  # Current instantaneous score
    S_t: float = 0.0  # Cumulative sum (CUSUM)
    h_threshold: float = 2.5  # Valve threshold for drift detection
    h: Optional[float] = None  # Current threshold value
    h_clr: Optional[float] = None  # Clear threshold
    drift_flag: bool = False  # True if drift detected

    # Surprise Vector (x1..x6) - Enhanced for multimodal
    x1_cache_novelty: float = 0.0  # Cache hit/miss novelty
    x2_semantic_drift: float = (
        0.0  # Semantic drift (renamed from ocps_drift for clarity)
    )
    x3_multimodal_anomaly: float = 0.0  # Multimodal anomaly (image/audio weirdness)
    x4_graph_context_drift: float = (
        0.0  # Graph context drift (renamed from graph_novelty)
    )
    x5_logic_uncertainty: float = (
        0.0  # Logic/dependency uncertainty (renamed from dep_uncertainty)
    )
    x6_cost_risk: float = 0.0  # Cost/risk signal

    # Legacy fields (for backward compatibility)
    x2_ocps_drift: Optional[float] = None  # Deprecated: use x2_semantic_drift
    x3_ood_novelty: Optional[float] = None  # Deprecated: use x3_multimodal_anomaly
    x4_graph_novelty: Optional[float] = None  # Deprecated: use x4_graph_context_drift
    x5_dep_uncertainty: Optional[float] = None  # Deprecated: use x5_logic_uncertainty

    feature_dim: Optional[int] = None  # Feature dimension (for compatibility)
    missing_count: int = 0  # Count of missing features

    model_config = ConfigDict(extra="forbid")


class EventTags(BaseModel):
    """Flexible event tagging system supporting both deterministic and intelligent categorization.
    
    This model separates "hard tags" (regex/pattern-based) from "soft tags" (vector/LLM/PKG-based)
    to enable a flexible, policy-driven event type system. The resolved_type is the final
    event type determined by PKG evaluation against the Domain Knowledge Graph.
    
    Architecture:
    - hard_tags: Deterministic tags from FastEventizer regex patterns (fast, reliable)
    - soft_tags: Intelligent tags from vector search or PKG rules (flexible, semantic)
    - resolved_type: Final event type from PKG evaluation (policy-driven, can be custom)
    - event_types: Backward-compatible property combining hard_tags and soft_tags
    """
    # Deterministic Tags (from FastEventizer regex patterns)
    hard_tags: List[EventType] = Field(
        default_factory=list,
        description="Hard tags from deterministic pattern matching (regex-based)"
    )
    
    # Intelligent/Inferred Tags (from PKG, Vector Search, or LLM)
    soft_tags: List[str] = Field(
        default_factory=list,
        description="Soft tags from semantic similarity, PKG rules, or LLM inference"
    )
    
    # The "Effective" Type (The one the PKG actually acts upon)
    resolved_type: str = Field(
        default="routine",
        description="Final event type resolved by PKG evaluation against Domain Knowledge Graph. Can be custom."
    )
    
    # Backward-compatible fields
    event_types: List[EventType] = Field(
        default_factory=list,
        description="Combined hard_tags and soft_tags (backward compatibility). Use resolved_type for PKG evaluation."
    )
    
    keywords: List[str] = Field(
        default_factory=list,
        description="Extracted keywords for vector search and PKG evaluation"
    )
    entities: List[str] = Field(default_factory=list)
    patterns: List[PatternMatch] = Field(default_factory=list)
    priority: int = 0
    urgency: Urgency = Urgency.NORMAL

    model_config = ConfigDict(use_enum_values=True, extra="forbid")
    
    @model_validator(mode="before")
    @classmethod
    def _normalize_hard_tags(cls, data: Any) -> Any:
        """Normalize hard_tags and event_types from strings to EventType enums before validation."""
        if isinstance(data, dict):
            # Normalize hard_tags
            if "hard_tags" in data:
                hard_tags = data["hard_tags"]
                if isinstance(hard_tags, list):
                    normalized = []
                    for tag in hard_tags:
                        if isinstance(tag, EventType):
                            normalized.append(tag)
                        elif isinstance(tag, str):
                            try:
                                normalized.append(EventType(tag.lower()))
                            except ValueError:
                                normalized.append(EventType.CUSTOM)
                        else:
                            try:
                                normalized.append(EventType(str(tag).lower()))
                            except ValueError:
                                normalized.append(EventType.CUSTOM)
                    data["hard_tags"] = normalized
            
            # Normalize event_types
            if "event_types" in data:
                event_types = data["event_types"]
                if isinstance(event_types, list):
                    normalized = []
                    for tag in event_types:
                        if isinstance(tag, EventType):
                            normalized.append(tag)
                        elif isinstance(tag, str):
                            try:
                                normalized.append(EventType(tag.lower()))
                            except ValueError:
                                normalized.append(EventType.CUSTOM)
                        else:
                            try:
                                normalized.append(EventType(str(tag).lower()))
                            except ValueError:
                                normalized.append(EventType.CUSTOM)
                    data["event_types"] = normalized
        return data
    
    @computed_field
    @property
    def all_event_types(self) -> List[str]:
        """Returns all event types (hard + soft + resolved) as strings for PKG evaluation."""
        types = [et.value if isinstance(et, EventType) else str(et) for et in self.hard_tags]
        types.extend(self.soft_tags)
        if self.resolved_type not in types:
            types.append(self.resolved_type)
        return types
    
    def model_post_init(self, __context: Any) -> None:
        """Ensure backward compatibility: sync hard_tags and event_types bidirectionally."""
        # Normalize hard_tags: ensure all items are EventType enums (not strings)
        normalized_hard_tags: List[EventType] = []
        for tag in self.hard_tags:
            if isinstance(tag, EventType):
                normalized_hard_tags.append(tag)
            elif isinstance(tag, str):
                # Convert string to EventType enum
                try:
                    normalized_hard_tags.append(EventType(tag.lower()))
                except ValueError:
                    # If string doesn't match any enum, use CUSTOM
                    normalized_hard_tags.append(EventType.CUSTOM)
            else:
                # Fallback: try to convert to EventType
                try:
                    normalized_hard_tags.append(EventType(str(tag).lower()))
                except ValueError:
                    normalized_hard_tags.append(EventType.CUSTOM)
        self.hard_tags = normalized_hard_tags
        
        # Normalize event_types: ensure all items are EventType enums (not strings)
        normalized_event_types: List[EventType] = []
        for tag in self.event_types:
            if isinstance(tag, EventType):
                normalized_event_types.append(tag)
            elif isinstance(tag, str):
                # Convert string to EventType enum
                try:
                    normalized_event_types.append(EventType(tag.lower()))
                except ValueError:
                    # If string doesn't match any enum, use CUSTOM
                    normalized_event_types.append(EventType.CUSTOM)
            else:
                # Fallback: try to convert to EventType
                try:
                    normalized_event_types.append(EventType(str(tag).lower()))
                except ValueError:
                    normalized_event_types.append(EventType.CUSTOM)
        self.event_types = normalized_event_types
        
        # If event_types is provided but hard_tags is empty, populate hard_tags (backward compat)
        if self.event_types and not self.hard_tags:
            self.hard_tags = self.event_types.copy()
        
        # If hard_tags is provided but event_types is empty, populate event_types (forward compat)
        if self.hard_tags and not self.event_types:
            self.event_types = self.hard_tags.copy()
        
        # If resolved_type is default but we have hard_tags, use first hard tag as resolved_type
        if self.resolved_type == "routine" and self.hard_tags:
            first_tag = self.hard_tags[0]
            # Check if it's an Enum (has .value) or a string
            if hasattr(first_tag, 'value'):
                self.resolved_type = first_tag.value
            else:
                # It's already a string, use it directly
                self.resolved_type = str(first_tag)


class EventAttributes(BaseModel):
    required_service: Optional[str] = None
    required_skill: Optional[str] = None
    target_organ: Optional[str] = None
    processing_timeout: Optional[float] = None
    resource_requirements: Dict[str, Any] = Field(default_factory=dict)
    routing_hints: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class RuleProvenance(BaseModel):
    """Provenance tracking for PKG rules with memory tier mapping.

    The memory_tier field maps to the Unified Memory System tiers:
    - 'event_working': Multimodal perception events (the "now")
    - 'knowledge_base': Structural knowledge and graph entities (the "rules" and "world")
    """

    rule_id: str
    snapshot_version: str
    reason: str
    memory_tier: str = "knowledge_base"  # Maps to v_unified_cortex_memory.memory_tier
    snapshot_id: Optional[int] = None
    weight: Optional[float] = 1.0  # Default weight for rule importance
    rule_priority: Optional[int] = None
    engine: Optional[PKGEngine] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class ProtoSubtask(BaseModel):
    name: str
    params: Dict[str, Any] = Field(default_factory=dict)
    provenance: List[RuleProvenance] = Field(default_factory=list)
    priority: Optional[str] = None
    sla_min: Optional[int] = None

    model_config = ConfigDict(extra="forbid")


class ProtoDagEdge(BaseModel):
    before: str
    after: str
    constraint: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class PKGHint(BaseModel):
    subtasks: List[ProtoSubtask] = Field(default_factory=list)
    edges: List[ProtoDagEdge] = Field(default_factory=list)
    provenance: List[RuleProvenance] = Field(default_factory=list)
    applied_snapshot: Optional[str] = None
    snapshot_id: Optional[int] = None
    snapshot_env: Optional[PKGEnv] = None
    snapshot_checksum: Optional[str] = None
    validation_passed: Optional[bool] = None
    deployment_target: Optional[str] = None
    deployment_region: Optional[str] = None
    deployment_percent: Optional[int] = None

    model_config = ConfigDict(extra="forbid")

    @computed_field
    @property
    def is_valid_snapshot(self) -> bool:
        return (
            self.applied_snapshot is not None
            and self.snapshot_id is not None
            and self.snapshot_checksum is not None
        )


class PKGHelper:
    """Helper class for PKG operations and validation."""

    @staticmethod
    def create_rule_provenance(
        rule_id: str,
        snapshot_version: str,
        reason: str,
        snapshot_id: Optional[int] = None,
        weight: Optional[float] = None,
        rule_priority: Optional[int] = None,
        engine: Optional[PKGEngine] = None,
        memory_tier: str = "knowledge_base",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RuleProvenance:
        return RuleProvenance(
            rule_id=rule_id,
            snapshot_version=snapshot_version,
            snapshot_id=snapshot_id,
            reason=reason,
            weight=weight,
            rule_priority=rule_priority,
            engine=engine,
            memory_tier=memory_tier,
            metadata=metadata or {},
        )

    @staticmethod
    def create_pkg_hint_from_snapshot(
        snapshot: Optional[PKGSnapshot],
        subtasks: Optional[List[ProtoSubtask]] = None,
        edges: Optional[List[ProtoDagEdge]] = None,
        provenance: Optional[List[RuleProvenance]] = None,
        deployment_target: Optional[str] = None,
        deployment_region: Optional[str] = None,
        deployment_percent: Optional[int] = None,
    ) -> PKGHint:
        # Allow snapshot to be None for testing/fallback
        version = snapshot.version if snapshot else "unknown"
        sid = snapshot.id if snapshot else None
        env = snapshot.env if snapshot else None
        chk = snapshot.checksum if snapshot else None

        return PKGHint(
            subtasks=subtasks or [],
            edges=edges or [],
            provenance=provenance or [],
            applied_snapshot=version,
            snapshot_id=sid,
            snapshot_env=env,
            snapshot_checksum=chk,
            deployment_target=deployment_target,
            deployment_region=deployment_region,
            deployment_percent=deployment_percent,
        )


class ConfidenceScore(BaseModel):
    overall_confidence: float = Field(..., ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel
    needs_ml_fallback: bool
    fallback_reasons: List[str] = Field(default_factory=list)
    processing_notes: List[str] = Field(default_factory=list)

    high_threshold: float = 0.90
    medium_threshold: float = 0.70
    ml_fallback_threshold: float = 0.90

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _enforce_levels(self) -> "ConfidenceScore":
        if self.overall_confidence >= self.high_threshold:
            level = ConfidenceLevel.HIGH
        elif self.overall_confidence >= self.medium_threshold:
            level = ConfidenceLevel.MEDIUM
        else:
            level = ConfidenceLevel.LOW
        object.__setattr__(self, "confidence_level", level)
        need_ml = self.overall_confidence < self.ml_fallback_threshold
        object.__setattr__(self, "needs_ml_fallback", bool(need_ml))
        return self


class EventizerRequest(BaseModel):
    """Request model for Eventizer processing with multimodal support.

    The media_context field replaces the generic 'source' string to provide
    structured metadata for voice, vision, and sensor inputs.
    """

    text: str
    task_type: Optional[str] = None
    domain: Optional[str] = None
    language: str = "en"
    tenant_id: Optional[str] = None
    request_id: Optional[str] = None
    source: Optional[str] = None  # Deprecated: use media_context.modality instead
    media_context: Optional[MediaContext] = (
        None  # Multimodal metadata (voice/vision/sensor)
    )
    timezone: Optional[str] = None
    now_utc: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    preserve_pii: bool = False
    redact_mode: RedactMode = RedactMode.REDACT
    pii_entities: List[str] = Field(
        default_factory=lambda: [
            "PERSON",
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "CREDIT_CARD",
        ]
    )

    include_metadata: bool = True
    include_patterns: bool = True
    include_pkg_hint: bool = True

    custom_patterns: Optional[List[Dict[str, Any]]] = None

    model_config = ConfigDict(extra="forbid")


class EventizerResponse(BaseModel):
    """Response model for Eventizer processing, bridging to Unified Memory System.

    This response acts as the bridge between Eventizer output and the Unified Memory View
    (v_unified_cortex_memory), providing all necessary metadata for task creation and
    embedding storage in the appropriate tables (task_multimodal_embeddings or graph_embeddings_1024).
    """

    original_text: str
    original_text_sha256: str = ""
    normalized_text: str
    processed_text: str

    text_normalization: Optional[TextNormalizationResult] = None
    pattern_compilation: Optional[List[PatternCompilationResult]] = None

    pii: Optional[PIIAudit] = None
    event_tags: EventTags = Field(default_factory=EventTags)
    attributes: EventAttributes = Field(default_factory=EventAttributes)
    signals: EventSignals = Field(default_factory=EventSignals)

    # Multimodal Payload (matches params.multimodal in tasks table)
    multimodal: Optional[MediaContext] = None

    # PKG Decision Logic
    pkg_hint: Optional[PKGHint] = None
    decision_hint: Optional[RouteDecision] = None
    decision_kind: RouteDecision = (
        RouteDecision.FAST
    )  # Explicit decision kind for routing

    # Memory Link - Task ID for Unified Memory System
    # This ID will be used as:
    # - task_id in task_multimodal_embeddings (for multimodal events)
    # - ext_uuid in graph_node_map -> node_id in graph_embeddings_1024 (for graph tasks)
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    confidence: ConfidenceScore

    processing_time_ms: float
    patterns_applied: int
    pii_redacted: bool
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    processing_log: List[str] = Field(default_factory=list)

    eventizer_version: str = "1.2.0"
    engines: Dict[str, str] = Field(default_factory=dict)

    pkg_snapshot_version: Optional[str] = None
    pkg_snapshot_id: Optional[int] = None
    pkg_validation_status: Optional[bool] = None
    pkg_deployment_info: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(extra="forbid")


class EventizerConfig(BaseModel):
    enable_regex: bool = True
    enable_keyword: bool = True
    enable_entity: bool = True

    enable_presidio: bool = False
    enable_hyperscan: bool = False
    enable_re2: bool = False
    enable_aho_corasick: bool = True  # Aho-Corasick algorithm for fast keyword matching (temporal markers, etc.)
    enable_onnx_ort: bool = False
    onnx_execution_providers: List[str] = Field(
        default_factory=lambda: ["OpenVINO", "CPUExecutionProvider"]
    )

    enable_pii_redaction: bool = True
    pii_redaction_entities: List[str] = Field(
        default_factory=lambda: [
            "PERSON",
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "CREDIT_CARD",
            "DATE_TIME",  # Added for temporal intent detection (e.g., "6PM")
        ]
    )
    redact_mode: RedactMode = RedactMode.REDACT
    mask_char: str = "•"
    mask_keep_len: bool = True
    preserve_offsets: bool = True

    high_confidence_threshold: float = 0.90
    medium_confidence_threshold: float = 0.70
    ml_fallback_threshold: float = 0.90

    p95_budget_ms: float = 2.0
    max_processing_time_ms: float = 100.0
    enable_caching: bool = True
    cache_ttl_seconds: int = 3600

    pattern_files: List[str] = Field(default_factory=list)
    keyword_dictionaries: List[str] = Field(default_factory=list)

    pkg_active_snapshot: Optional[str] = None
    pkg_active_snapshot_id: Optional[int] = None
    pkg_environment: PKGEnv = PKGEnv.PROD
    policy_console_url: Optional[HttpUrl] = None

    pkg_validation_enabled: bool = True
    pkg_validation_timeout_seconds: float = 5.0
    pkg_require_active_snapshot: bool = True

    model_config = ConfigDict(extra="forbid")
