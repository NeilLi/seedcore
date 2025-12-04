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

from pydantic import BaseModel, Field, ConfigDict, computed_field, model_validator, HttpUrl  # pyright: ignore[reportMissingImports]
from datetime import datetime, timezone


# =========================
# Enums
# =========================

class ConfidenceLevel(str, Enum):
    HIGH = "high"        # >= high_threshold
    MEDIUM = "medium"    # [medium_threshold, high_threshold)
    LOW = "low"          # < medium_threshold


class EventType(str, Enum):
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
    REDACT = "redact"        # placeholders <TYPE_i>
    MASK = "mask"            # ••••
    TOKENIZE = "tokenize"    # <TYPE_i>:hmac8
    HASH = "hash"            # hmac_sha256


class RouteDecision(str, Enum):
    FAST = "fast"
    PLANNER = "planner"
    HGNN = "hgnn"


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


class EventSignals(BaseModel):
    x1_cache_novelty: Optional[float] = None
    x2_ocps_drift: Optional[float] = None
    x3_ood_novelty: Optional[float] = None
    x4_graph_novelty: Optional[float] = None
    x5_dep_uncertainty: Optional[float] = None
    x6_cost_risk: Optional[float] = None

    s_t: Optional[float] = None
    S_t: Optional[float] = None
    h: Optional[float] = None
    h_clr: Optional[float] = None
    drift_flag: Optional[bool] = None

    feature_dim: Optional[int] = None
    missing_count: int = 0

    model_config = ConfigDict(extra="forbid")


class EventTags(BaseModel):
    event_types: List[EventType] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    patterns: List[PatternMatch] = Field(default_factory=list)
    priority: int = 0
    urgency: Urgency = Urgency.NORMAL

    model_config = ConfigDict(use_enum_values=True, extra="forbid")


class EventAttributes(BaseModel):
    required_service: Optional[str] = None
    required_skill: Optional[str] = None
    target_organ: Optional[str] = None
    processing_timeout: Optional[float] = None
    resource_requirements: Dict[str, Any] = Field(default_factory=dict)
    routing_hints: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class RuleProvenance(BaseModel):
    rule_id: str
    snapshot_version: str
    reason: str
    snapshot_id: Optional[int] = None
    weight: Optional[float] = None
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
            self.applied_snapshot is not None and
            self.snapshot_id is not None and
            self.snapshot_checksum is not None
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
        metadata: Optional[Dict[str, Any]] = None
    ) -> RuleProvenance:
        return RuleProvenance(
            rule_id=rule_id,
            snapshot_version=snapshot_version,
            snapshot_id=snapshot_id,
            reason=reason,
            weight=weight,
            rule_priority=rule_priority,
            engine=engine,
            metadata=metadata or {}
        )
    
    @staticmethod
    def create_pkg_hint_from_snapshot(
        snapshot: Optional[PKGSnapshot],
        subtasks: Optional[List[ProtoSubtask]] = None,
        edges: Optional[List[ProtoDagEdge]] = None,
        provenance: Optional[List[RuleProvenance]] = None,
        deployment_target: Optional[str] = None,
        deployment_region: Optional[str] = None,
        deployment_percent: Optional[int] = None
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
            deployment_percent=deployment_percent
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
    text: str
    task_type: Optional[str] = None
    domain: Optional[str] = None
    language: str = "en"
    tenant_id: Optional[str] = None
    request_id: Optional[str] = None
    source: Optional[str] = None
    timezone: Optional[str] = None
    now_utc: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))

    preserve_pii: bool = False
    redact_mode: RedactMode = RedactMode.REDACT
    pii_entities: List[str] = Field(
        default_factory=lambda: ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD"]
    )

    include_metadata: bool = True
    include_patterns: bool = True
    include_pkg_hint: bool = True

    custom_patterns: Optional[List[Dict[str, Any]]] = None

    model_config = ConfigDict(extra="forbid")


class EventizerResponse(BaseModel):
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

    pkg_hint: Optional[PKGHint] = None
    decision_hint: Optional[RouteDecision] = None
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
    enable_onnx_ort: bool = False
    onnx_execution_providers: List[str] = Field(default_factory=lambda: ["OpenVINO", "CPUExecutionProvider"])

    enable_pii_redaction: bool = True
    pii_redaction_entities: List[str] = Field(
        default_factory=lambda: ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD"]
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