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
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
from dataclasses import dataclass

from pydantic import BaseModel, Field, ConfigDict, computed_field, model_validator, field_validator, HttpUrl
from datetime import datetime, timezone

# Note: We use TYPE_CHECKING to avoid circular imports with utils modules
# The actual SpanMap class is imported lazily when needed


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
# PKG-related Enums (from migrations 013-015)
# =========================

class PKGEnv(str, Enum):
    """PKG environment types."""
    PROD = "prod"
    STAGING = "staging"
    DEV = "dev"


class PKGEngine(str, Enum):
    """PKG execution engines."""
    WASM = "wasm"
    NATIVE = "native"


class PKGConditionType(str, Enum):
    """PKG condition types for rule evaluation."""
    TAG = "TAG"
    SIGNAL = "SIGNAL"
    VALUE = "VALUE"
    FACT = "FACT"


class PKGOperator(str, Enum):
    """PKG operators for condition evaluation."""
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
    """PKG relationship types between rules and subtasks."""
    EMITS = "EMITS"
    ORDERS = "ORDERS"
    GATE = "GATE"


class PKGArtifactType(str, Enum):
    """PKG artifact types for compiled policies."""
    REGO_BUNDLE = "rego_bundle"
    WASM_PACK = "wasm_pack"


# =========================
# PKG Core Models (from migration 013)
# =========================

class PKGSnapshot(BaseModel):
    """PKG snapshot model representing versioned policy snapshots."""
    id: Optional[int] = Field(None, description="Database ID")
    version: str = Field(..., description="Snapshot version string")
    env: PKGEnv = Field(default=PKGEnv.PROD, description="Environment")
    entrypoint: str = Field(default="data.pkg", description="OPA/Rego entrypoint")
    schema_version: str = Field(default="1", description="Schema version")
    checksum: str = Field(..., min_length=64, max_length=64, description="SHA-256 checksum (hex)")
    size_bytes: Optional[int] = Field(None, ge=0, description="Snapshot size in bytes")
    signature: Optional[str] = Field(None, description="Optional Ed25519/PGP signature")
    is_active: bool = Field(default=False, description="Whether this snapshot is active")
    notes: Optional[str] = Field(None, description="Optional notes")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(extra="forbid")

    @field_validator("checksum")
    @classmethod
    def _validate_checksum(cls, v: str) -> str:
        if not v or len(v) != 64:
            raise ValueError("checksum must be exactly 64 hex characters")
        try:
            int(v, 16)  # Validate hex
        except ValueError:
            raise ValueError("checksum must be valid hexadecimal")
        return v.lower()

    @classmethod
    def from_db_row(cls, row) -> "PKGSnapshot":
        """Create PKGSnapshot from database row."""
        return cls(
            id=row[0],
            version=row[1],
            env=PKGEnv(row[2]),
            entrypoint=row[3],
            schema_version=row[4],
            checksum=row[5],
            size_bytes=row[6],
            signature=row[7],
            is_active=row[8],
            notes=row[9],
            created_at=row[10]
        )


class PKGSubtaskType(BaseModel):
    """PKG subtask type definition."""
    id: Optional[str] = Field(None, description="UUID")
    snapshot_id: int = Field(..., description="Reference to PKG snapshot")
    name: str = Field(..., description="Subtask type name")
    default_params: Optional[Dict[str, Any]] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(extra="forbid")


class PKGPolicyRule(BaseModel):
    """PKG policy rule definition."""
    id: Optional[str] = Field(None, description="UUID")
    snapshot_id: int = Field(..., description="Reference to PKG snapshot")
    rule_name: str = Field(..., description="Rule name")
    priority: int = Field(default=100, ge=0, le=1000, description="Rule priority")
    rule_source: str = Field(..., description="YAML/Datalog/Rego source")
    compiled_rule: Optional[str] = Field(None, description="Optional compiled form")
    engine: PKGEngine = Field(default=PKGEngine.WASM, description="Execution engine")
    rule_hash: Optional[str] = Field(None, description="Hash of rule_source")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    disabled: bool = Field(default=False, description="Whether rule is disabled")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(extra="forbid")


class PKGRuleCondition(BaseModel):
    """PKG rule condition for policy evaluation."""
    rule_id: str = Field(..., description="Reference to PKG policy rule")
    condition_type: PKGConditionType = Field(..., description="Type of condition")
    condition_key: str = Field(..., description="Condition key (e.g., vip, x6, subject)")
    operator: PKGOperator = Field(default=PKGOperator.EXISTS, description="Comparison operator")
    value: Optional[str] = Field(None, description="Condition value")
    position: int = Field(default=0, ge=0, description="Position in condition chain")

    model_config = ConfigDict(extra="forbid")


class PKGRuleEmission(BaseModel):
    """PKG rule emission linking rules to subtask types."""
    rule_id: str = Field(..., description="Reference to PKG policy rule")
    subtask_type_id: str = Field(..., description="Reference to PKG subtask type")
    relationship_type: PKGRelation = Field(default=PKGRelation.EMITS, description="Relationship type")
    params: Optional[Dict[str, Any]] = Field(default_factory=dict)
    position: int = Field(default=0, ge=0, description="Position in emission chain")

    model_config = ConfigDict(extra="forbid")


class PKGSnapshotArtifact(BaseModel):
    """PKG snapshot artifact (WASM/Rego compiled policies)."""
    snapshot_id: int = Field(..., description="Reference to PKG snapshot")
    artifact_type: PKGArtifactType = Field(..., description="Type of artifact")
    artifact_bytes: bytes = Field(..., description="Compiled artifact bytes")
    sha256: str = Field(..., min_length=64, max_length=64, description="SHA-256 of artifact")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = Field(default="system", description="Creator identifier")

    model_config = ConfigDict(extra="forbid")

    @computed_field
    @property
    def size_bytes(self) -> int:
        """Size of artifact in bytes."""
        return len(self.artifact_bytes)

    @field_validator("sha256")
    @classmethod
    def _validate_sha256(cls, v: str) -> str:
        if not v or len(v) != 64:
            raise ValueError("sha256 must be exactly 64 hex characters")
        try:
            int(v, 16)  # Validate hex
        except ValueError:
            raise ValueError("sha256 must be valid hexadecimal")
        return v.lower()


# =========================
# PKG Operations Models (from migration 014)
# =========================

class PKGDeployment(BaseModel):
    """PKG targeted deployment configuration."""
    id: Optional[int] = Field(None, description="Database ID")
    snapshot_id: int = Field(..., description="Reference to PKG snapshot")
    target: str = Field(..., description="Target (e.g., 'router','edge:door','edge:robot')")
    region: str = Field(default="global", description="Deployment region")
    percent: int = Field(default=100, ge=0, le=100, description="Deployment percentage")
    is_active: bool = Field(default=True, description="Whether deployment is active")
    activated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    activated_by: str = Field(default="system", description="Activation actor")

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def from_db_row(cls, row) -> "PKGDeployment":
        """Create PKGDeployment from database row."""
        return cls(
            id=row[0],
            snapshot_id=row[1],
            target=row[2],
            region=row[3],
            percent=row[4],
            is_active=row[5],
            activated_at=row[6],
            activated_by=row[7]
        )


class PKGFact(BaseModel):
    """PKG temporal policy fact."""
    id: Optional[int] = Field(None, description="Database ID")
    snapshot_id: Optional[int] = Field(None, description="Reference to PKG snapshot")
    namespace: str = Field(default="default", description="Fact namespace")
    subject: str = Field(..., description="Fact subject (e.g., 'guest:Ben')")
    predicate: str = Field(..., description="Fact predicate (e.g., 'hasTemporaryAccess')")
    object: Dict[str, Any] = Field(..., description="Fact object (e.g., {'service':'lounge'})")
    valid_from: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    valid_to: Optional[datetime] = Field(None, description="Expiration time (NULL = indefinite)")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = Field(default="system", description="Creator identifier")

    model_config = ConfigDict(extra="forbid")

    @computed_field
    @property
    def is_expired(self) -> bool:
        """Whether this fact has expired."""
        if self.valid_to is None:
            return False
        return datetime.now(timezone.utc) > self.valid_to

    @computed_field
    @property
    def is_valid(self) -> bool:
        """Whether this fact is currently valid."""
        now = datetime.now(timezone.utc)
        return now >= self.valid_from and not self.is_expired

    @classmethod
    def from_db_row(cls, row) -> "PKGFact":
        """Create PKGFact from database row."""
        return cls(
            id=row[0],
            snapshot_id=row[1],
            namespace=row[2],
            subject=row[3],
            predicate=row[4],
            object=row[5],
            valid_from=row[6],
            valid_to=row[7],
            created_at=row[8],
            created_by=row[9]
        )


class PKGValidationFixture(BaseModel):
    """PKG validation fixture for testing policies."""
    id: Optional[int] = Field(None, description="Database ID")
    snapshot_id: int = Field(..., description="Reference to PKG snapshot")
    name: str = Field(..., description="Fixture name")
    input: Dict[str, Any] = Field(..., description="Evaluator input")
    expect: Dict[str, Any] = Field(..., description="Expected outputs/properties")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(extra="forbid")


class PKGValidationRun(BaseModel):
    """PKG validation run result."""
    id: Optional[int] = Field(None, description="Database ID")
    snapshot_id: int = Field(..., description="Reference to PKG snapshot")
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = Field(None, description="Completion time")
    success: Optional[bool] = Field(None, description="Whether validation succeeded")
    report: Optional[Dict[str, Any]] = Field(None, description="Validation report")

    model_config = ConfigDict(extra="forbid")

    @computed_field
    @property
    def duration_seconds(self) -> Optional[float]:
        """Validation duration in seconds."""
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()


class PKGPromotion(BaseModel):
    """PKG promotion/rollback audit record."""
    id: Optional[int] = Field(None, description="Database ID")
    snapshot_id: int = Field(..., description="Reference to PKG snapshot")
    from_version: Optional[str] = Field(None, description="Previous version")
    to_version: Optional[str] = Field(None, description="New version")
    actor: str = Field(..., description="Promotion actor")
    action: str = Field(..., description="Action: 'promote' or 'rollback'")
    reason: Optional[str] = Field(None, description="Promotion reason")
    metrics: Optional[Dict[str, Any]] = Field(None, description="Evaluation metrics")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    success: bool = Field(default=True, description="Whether promotion succeeded")

    model_config = ConfigDict(extra="forbid")


class PKGDeviceVersion(BaseModel):
    """PKG device version heartbeat tracking."""
    device_id: str = Field(..., description="Device ID (e.g., 'door:D-1510')")
    device_type: str = Field(..., description="Device type (e.g., 'door', 'robot', 'shuttle')")
    region: str = Field(default="global", description="Device region")
    snapshot_id: Optional[int] = Field(None, description="Reference to PKG snapshot")
    version: Optional[str] = Field(None, description="Device version")
    last_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(extra="forbid")

    @computed_field
    @property
    def is_stale(self, stale_threshold_seconds: int = 300) -> bool:
        """Whether device heartbeat is stale (default 5 minutes)."""
        now = datetime.now(timezone.utc)
        return (now - self.last_seen).total_seconds() > stale_threshold_seconds


# =========================
# Leaf / atomic models
# =========================

class PatternMatch(BaseModel):
    """Individual pattern match result with enhanced span mapping capabilities."""
    pattern_id: str = Field(..., description="Unique identifier (pattern key)")
    pattern_type: str = Field(..., description="regex|keyword|entity|gazetteer")
    matched_text: str = Field(..., description="Matched span text (may include PII)")
    start_pos: int = Field(..., ge=0, description="Start index in ORIGINAL text")
    end_pos: int = Field(..., ge=0, description="End index (exclusive) in ORIGINAL text")
    confidence: float = Field(..., ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # Enhanced fields for better pattern matching
    engine: str = Field(default="re", description="Pattern engine used: re|re2|hyperscan")
    priority: int = Field(default=100, description="Pattern priority (lower = higher priority)")
    whole_word: bool = Field(default=False, description="Whether pattern was anchored to word boundaries")
    normalized_start: Optional[int] = Field(None, description="Start position in normalized text")
    normalized_end: Optional[int] = Field(None, description="End position in normalized text")
    groups: Optional[List[str]] = Field(None, description="Regex capture groups if applicable")
    
    model_config = ConfigDict(extra="forbid")
    
    @computed_field
    @property
    def span_length(self) -> int:
        """Length of the matched span."""
        return self.end_pos - self.start_pos
    
    @computed_field
    @property
    def normalized_span_length(self) -> Optional[int]:
        """Length of the matched span in normalized text."""
        if self.normalized_start is not None and self.normalized_end is not None:
            return self.normalized_end - self.normalized_start
        return None


class EntitySpan(BaseModel):
    """Detected entity (PII or domain entity) with offsets in ORIGINAL text."""
    entity_type: str = Field(..., description="e.g., EMAIL_ADDRESS, ROOM_ID")
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)
    score: float = Field(0.0, ge=0.0, le=1.0)
    text: str = Field(..., description="Original text slice")
    replacement: Optional[str] = Field(None, description="Replacement used (if redacted)")

    model_config = ConfigDict(extra="forbid")


class TextNormalizationResult(BaseModel):
    """Result of text normalization with bidirectional span mapping."""
    original_text: str = Field(..., description="Original input text")
    normalized_text: str = Field(..., description="Normalized text")
    span_map: Optional[Any] = Field(None, description="Bidirectional span mapping (SpanMap from text_normalizer)")
    normalization_applied: List[str] = Field(default_factory=list, description="Types of normalization applied")
    processing_time_ms: float = Field(0.0, description="Normalization processing time")
    
    model_config = ConfigDict(extra="forbid")
    
    def project_span_to_original(self, start: int, end: int) -> Tuple[int, int]:
        """Project a span from normalized text back to original text."""
        if self.span_map:
            return self.span_map.project_norm_span_to_orig(start, end)
        return (start, end)
    
    def project_span_to_normalized(self, start: int, end: int) -> Tuple[int, int]:
        """Project a span from original text to normalized text."""
        if self.span_map:
            return self.span_map.project_orig_span_to_norm(start, end)
        return (start, end)


class PatternCompilationResult(BaseModel):
    """Result of pattern compilation with engine information."""
    pattern_id: str = Field(..., description="Unique pattern identifier")
    engine: str = Field(..., description="Compilation engine: re|re2|hyperscan")
    pattern_type: str = Field(..., description="Pattern type: regex|keyword|entity")
    priority: int = Field(default=100, description="Pattern priority (lower = higher)")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Default confidence")
    whole_word: bool = Field(default=False, description="Word boundary anchoring")
    compilation_time_ms: float = Field(0.0, description="Compilation time")
    flags: int = Field(default=0, description="Regex flags used")
    is_compiled: bool = Field(default=True, description="Whether pattern was successfully compiled")
    error_message: Optional[str] = Field(None, description="Compilation error if any")
    
    model_config = ConfigDict(extra="forbid")
    
    @computed_field
    @property
    def engine_capabilities(self) -> Dict[str, bool]:
        """Engine capabilities based on the compilation engine."""
        capabilities = {
            "supports_unicode": True,
            "supports_word_boundaries": True,
            "supports_case_insensitive": True,
            "supports_multiline": True,
            "supports_dotall": True,
            "supports_verbose": True
        }
        
        if self.engine == "re2":
            capabilities.update({
                "linear_time": True,
                "no_catastrophic_backtracking": True,
                "limited_lookahead": True
            })
        elif self.engine == "hyperscan":
            capabilities.update({
                "multi_pattern": True,
                "ultra_fast": True,
                "streaming": True
            })
        
        return capabilities


class PIIAudit(BaseModel):
    """Audit payload for PII processing."""
    used_engine: str = Field(..., description="presidio|fallback|none")
    mode: RedactMode = Field(default=RedactMode.REDACT)
    entities_evaluated: List[str] = Field(default_factory=list)
    spans: List[EntitySpan] = Field(default_factory=list, description="Detected PII/entity spans")
    counts_by_type: Dict[str, int] = Field(default_factory=dict)
    raw_text_sha256: str = Field(..., description="SHA-256 of ORIGINAL text for audit")
    version: str = Field("2.2.0", description="PII client version")
    mask_char: str = Field("•")
    mask_keep_len: bool = Field(True)
    preserve_offsets: bool = Field(True)

    model_config = ConfigDict(extra="forbid")


class EventSignals(BaseModel):
    """
    Signals used by the router (subset may be missing).
    - x1..x6 are in [0,1] if present
    - OCPS CUSUM fields included for x2 drift construction
    """
    x1_cache_novelty: Optional[float] = Field(None, ge=0.0, le=1.0)
    x2_ocps_drift: Optional[float] = Field(None, ge=0.0, le=1.0)
    x3_ood_novelty: Optional[float] = Field(None, ge=0.0, le=1.0)
    x4_graph_novelty: Optional[float] = Field(None, ge=0.0, le=1.0)
    x5_dep_uncertainty: Optional[float] = Field(None, ge=0.0, le=1.0)
    x6_cost_risk: Optional[float] = Field(None, ge=0.0, le=1.0)

    # OCPS/Neural-CUSUM fields
    s_t: Optional[float] = Field(None, description="MLP scalar s_t at t")
    S_t: Optional[float] = Field(None, description="CUSUM cumulative statistic at t")
    h: Optional[float] = Field(None, description="CUSUM threshold")
    h_clr: Optional[float] = Field(None, description="CUSUM clear threshold (hysteresis)")
    drift_flag: Optional[bool] = Field(None, description="OCPS drift flag")

    # Housekeeping
    feature_dim: Optional[int] = Field(None, ge=1, description="Feature dimensions for OOD χ² mapping")
    missing_count: int = Field(0, ge=0)

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "x1_cache_novelty", "x2_ocps_drift", "x3_ood_novelty", "x4_graph_novelty",
        "x5_dep_uncertainty", "x6_cost_risk"
    )
    @classmethod
    def _nan_guard(cls, v: Optional[float]) -> Optional[float]:
        # If NaN slips in, coerce to None so downstream renorm works.
        if v is not None and (v != v):  # NaN check
            return None
        return v


class EventTags(BaseModel):
    """Structured tags and pattern evidence extracted from text."""
    event_types: List[EventType] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list, description="Domain entities (non-PII)")
    patterns: List[PatternMatch] = Field(default_factory=list)
    priority: int = Field(default=0, ge=0, le=10)
    urgency: Urgency = Field(default=Urgency.NORMAL)

    model_config = ConfigDict(use_enum_values=True, extra="forbid")


class EventAttributes(BaseModel):
    """Routing attributes/hints for downstream organs."""
    required_service: Optional[str] = Field(None, description="e.g., hvac, security, kitchen")
    required_skill: Optional[str] = Field(None, description="Classifier/tool capability")
    target_organ: Optional[str] = Field(None, description="Suggested organ name/ID")
    processing_timeout: Optional[float] = Field(None, ge=0.0, description="SLA hint (seconds)")
    resource_requirements: Dict[str, Any] = Field(default_factory=dict)
    routing_hints: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class RuleProvenance(BaseModel):
    """Enhanced rule provenance with PKG integration."""
    rule_id: str = Field(..., description="Stable rule UUID or name")
    snapshot_version: str = Field(..., description="PKG snapshot version string")
    snapshot_id: Optional[int] = Field(None, description="PKG snapshot database ID")
    reason: str = Field(..., description="Short explanation (why fired)")
    weight: Optional[float] = Field(None, ge=0.0, le=1.0, description="Optional priority/weight")
    rule_priority: Optional[int] = Field(None, ge=0, le=1000, description="PKG rule priority")
    engine: Optional[PKGEngine] = Field(None, description="PKG execution engine used")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional rule metadata")

    model_config = ConfigDict(extra="forbid")


class ProtoSubtask(BaseModel):
    """PKG-emitted proto-subtask with optional parameters & provenance."""
    name: str = Field(..., description="e.g., private_comms, hvac_stabilize")
    params: Dict[str, Any] = Field(default_factory=dict)
    provenance: List[RuleProvenance] = Field(default_factory=list)
    priority: Optional[str] = Field(None, description="critical|high|normal|low")
    sla_min: Optional[int] = Field(None, ge=0)

    model_config = ConfigDict(extra="forbid")


class ProtoDagEdge(BaseModel):
    """Directed edge between proto-subtasks."""
    before: str = Field(..., description="Subtask name that must run first")
    after: str = Field(..., description="Subtask name that depends on 'before'")
    constraint: Optional[str] = Field(None, description="e.g., privacy_gated")

    model_config = ConfigDict(extra="forbid")


class PKGHint(BaseModel):
    """Enhanced PKG output with full snapshot integration."""
    subtasks: List[ProtoSubtask] = Field(default_factory=list)
    edges: List[ProtoDagEdge] = Field(default_factory=list)
    provenance: List[RuleProvenance] = Field(default_factory=list)
    applied_snapshot: Optional[str] = Field(None, description="PKG snapshot version used")
    snapshot_id: Optional[int] = Field(None, description="PKG snapshot database ID")
    snapshot_env: Optional[PKGEnv] = Field(None, description="PKG environment")
    snapshot_checksum: Optional[str] = Field(None, description="PKG snapshot checksum")
    validation_passed: Optional[bool] = Field(None, description="Whether validation fixtures passed")
    deployment_target: Optional[str] = Field(None, description="Target deployment (router, edge, etc.)")
    deployment_region: Optional[str] = Field(None, description="Deployment region")
    deployment_percent: Optional[int] = Field(None, ge=0, le=100, description="Deployment percentage")

    model_config = ConfigDict(extra="forbid")

    @computed_field
    @property
    def is_valid_snapshot(self) -> bool:
        """Whether the snapshot is valid and active."""
        return (
            self.applied_snapshot is not None and
            self.snapshot_id is not None and
            self.snapshot_checksum is not None
        )


class ConfidenceScore(BaseModel):
    """Confidence scoring for deterministic processing."""
    overall_confidence: float = Field(..., ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel = Field(...)

    needs_ml_fallback: bool = Field(..., description="Whether ML fallback is recommended")
    fallback_reasons: List[str] = Field(default_factory=list)
    processing_notes: List[str] = Field(default_factory=list)

    # thresholds echoed for observability
    high_threshold: float = Field(0.90, ge=0.0, le=1.0)
    medium_threshold: float = Field(0.70, ge=0.0, le=1.0)
    ml_fallback_threshold: float = Field(0.90, ge=0.0, le=1.0)

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


# =========================
# Requests / Responses
# =========================

class EventizerRequest(BaseModel):
    """Request model for eventizer processing (hot path)."""
    text: str = Field(..., description="Raw user/system text (will be normalized)")
    task_type: Optional[str] = Field(None, description="SeedCore task type")
    domain: Optional[str] = Field(None, description="Domain context (hotel_ops, fintech, etc.)")
    language: str = Field("en", description="ISO language code for analyzers")
    tenant_id: Optional[str] = Field(None, description="Multi-tenant ID")
    request_id: Optional[str] = Field(None, description="Upstream correlation/request ID")
    source: Optional[str] = Field(None, description="Source system (api-gw/mobile/robot)")
    timezone: Optional[str] = Field(None, description="IANA TZ for time expressions")
    now_utc: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Ingestion timestamp (UTC)"
    )

    # PII handling
    preserve_pii: bool = Field(False, description="If True, return original text alongside redacted")
    redact_mode: RedactMode = Field(RedactMode.REDACT)
    pii_entities: List[str] = Field(
        default_factory=lambda: ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD"],
        description="PII classes to process"
    )

    # Metadata output controls
    include_metadata: bool = Field(True)
    include_patterns: bool = Field(True)
    include_pkg_hint: bool = Field(True)

    # Extensibility
    custom_patterns: Optional[List[Dict[str, Any]]] = Field(
        None, description="Inline extra patterns (compiled per-request if provided)"
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("text")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("text must be non-empty")
        return v


class EventizerResponse(BaseModel):
    """Response model for eventizer processing (hot path) with enhanced utilities integration."""
    # Core text artifacts
    original_text: str = Field(..., description="Original input (may be returned only when preserve_pii=True)")
    original_text_sha256: str = Field(..., description="Stable audit hash of original")
    normalized_text: str = Field(..., description="Lowercased/canonicalized text (pre-PII)")
    processed_text: str = Field(..., description="Text AFTER PII redaction/anonymization")

    # Enhanced text processing results
    text_normalization: Optional[TextNormalizationResult] = Field(
        None, description="Detailed text normalization results with span mapping"
    )
    pattern_compilation: Optional[List[PatternCompilationResult]] = Field(
        None, description="Pattern compilation results for audit and debugging"
    )

    # PII audit
    pii: Optional[PIIAudit] = Field(None, description="PII audit block (spans, engine, counts)")

    # Semantic outputs
    event_tags: EventTags = Field(default_factory=EventTags)
    attributes: EventAttributes = Field(default_factory=EventAttributes)
    signals: EventSignals = Field(default_factory=EventSignals)

    # PKG hints (proto-subtasks/DAG)
    pkg_hint: Optional[PKGHint] = Field(None)

    # Router decision hint (optional)
    decision_hint: Optional[RouteDecision] = Field(None)

    # Confidence
    confidence: ConfidenceScore = Field(...)

    # Observability & governance
    processing_time_ms: float = Field(..., ge=0.0)
    patterns_applied: int = Field(0, ge=0)
    pii_redacted: bool = Field(False)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    processing_log: List[str] = Field(default_factory=list)

    # Versions / engines for audit
    eventizer_version: str = Field("1.0.0")
    engines: Dict[str, str] = Field(
        default_factory=dict,
        description="Engine/versions used (regex, ac, presidio, onnx, pkg_snapshot, etc.)",
    )
    
    # PKG integration metadata
    pkg_snapshot_version: Optional[str] = Field(None, description="PKG snapshot version used")
    pkg_snapshot_id: Optional[int] = Field(None, description="PKG snapshot database ID")
    pkg_validation_status: Optional[bool] = Field(None, description="PKG validation status")
    pkg_deployment_info: Optional[Dict[str, Any]] = Field(None, description="PKG deployment metadata")

    model_config = ConfigDict(extra="forbid")

    @computed_field  # type: ignore[misc]
    @property
    def missing_signals_count(self) -> int:
        """Count of missing x1..x6 (used for guardrails/telemetry)."""
        sigs = [
            self.signals.x1_cache_novelty,
            self.signals.x2_ocps_drift,
            self.signals.x3_ood_novelty,
            self.signals.x4_graph_novelty,
            self.signals.x5_dep_uncertainty,
            self.signals.x6_cost_risk,
        ]
        return sum(1 for v in sigs if v is None)
    
    def project_pattern_span_to_original(self, pattern_match: PatternMatch) -> Tuple[int, int]:
        """Project a pattern match span from normalized text back to original text."""
        if self.text_normalization and pattern_match.normalized_start is not None and pattern_match.normalized_end is not None:
            return self.text_normalization.project_span_to_original(
                pattern_match.normalized_start, 
                pattern_match.normalized_end
            )
        return (pattern_match.start_pos, pattern_match.end_pos)
    
    def get_compilation_summary(self) -> Dict[str, Any]:
        """Get a summary of pattern compilation results."""
        if not self.pattern_compilation:
            return {"total_patterns": 0, "engines_used": [], "compilation_errors": 0}
        
        engines_used = list(set(comp.engine for comp in self.pattern_compilation))
        compilation_errors = sum(1 for comp in self.pattern_compilation if not comp.is_compiled)
        
        return {
            "total_patterns": len(self.pattern_compilation),
            "engines_used": engines_used,
            "compilation_errors": compilation_errors,
            "average_compilation_time": sum(comp.compilation_time_ms for comp in self.pattern_compilation) / len(self.pattern_compilation) if self.pattern_compilation else 0.0
        }
    
    def get_normalization_summary(self) -> Dict[str, Any]:
        """Get a summary of text normalization results."""
        if not self.text_normalization:
            return {"normalization_applied": [], "has_span_mapping": False}
        
        return {
            "normalization_applied": self.text_normalization.normalization_applied,
            "has_span_mapping": self.text_normalization.span_map is not None,
            "processing_time_ms": self.text_normalization.processing_time_ms,
            "text_length_ratio": len(self.text_normalization.normalized_text) / len(self.text_normalization.original_text) if self.text_normalization.original_text else 1.0
        }


class EventizerConfig(BaseModel):
    """Service configuration (wired at startup, echoed in /status)."""
    # Pattern matching
    enable_regex: bool = Field(True)
    enable_keyword: bool = Field(True)
    enable_entity: bool = Field(True)

    # Engines
    enable_presidio: bool = Field(False, description="Enable Presidio analyzer/anonymizer")
    enable_hyperscan: bool = Field(False, description="Use Hyperscan for high-perf regex if available")
    enable_re2: bool = Field(False, description="Use RE2 for safe regex where needed")
    enable_onnx_ort: bool = Field(False, description="Enable ONNX Runtime for tiny models")
    onnx_execution_providers: List[str] = Field(default_factory=lambda: ["OpenVINO", "CPUExecutionProvider"])

    # PII
    enable_pii_redaction: bool = Field(True)
    pii_redaction_entities: List[str] = Field(
        default_factory=lambda: ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD"],
        description="Default PII classes"
    )
    redact_mode: RedactMode = Field(RedactMode.REDACT)
    mask_char: str = Field("•")
    mask_keep_len: bool = Field(True)
    preserve_offsets: bool = Field(True)

    # Confidence thresholds
    high_confidence_threshold: float = Field(0.90, ge=0.0, le=1.0)
    medium_confidence_threshold: float = Field(0.70, ge=0.0, le=1.0)
    ml_fallback_threshold: float = Field(0.90, ge=0.0, le=1.0)

    # Performance
    p95_budget_ms: float = Field(2.0, ge=0.1, description="Hot-path target for router use")
    max_processing_time_ms: float = Field(100.0, ge=1.0, description="Absolute ceiling (failsafe)")
    enable_caching: bool = Field(True)
    cache_ttl_seconds: int = Field(3600, ge=1)

    # Pattern sources
    pattern_files: List[str] = Field(default_factory=list)
    keyword_dictionaries: List[str] = Field(default_factory=list)

    # PKG Governance
    pkg_active_snapshot: Optional[str] = Field(None, description="Active PKG snapshot version")
    pkg_active_snapshot_id: Optional[int] = Field(None, description="Active PKG snapshot database ID")
    pkg_environment: PKGEnv = Field(default=PKGEnv.PROD, description="PKG environment")
    policy_console_url: Optional[HttpUrl] = Field(None, description="Optional link to policy console")
    
    # PKG validation settings
    pkg_validation_enabled: bool = Field(default=True, description="Enable PKG validation")
    pkg_validation_timeout_seconds: float = Field(default=5.0, ge=1.0, le=60.0, description="PKG validation timeout")
    pkg_require_active_snapshot: bool = Field(default=True, description="Require active PKG snapshot")

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_thresholds(self) -> "EventizerConfig":
        if not (0.0 <= self.medium_confidence_threshold <= self.high_confidence_threshold <= 1.0):
            raise ValueError("Thresholds must satisfy 0 <= medium <= high <= 1")
        if not (0.0 <= self.ml_fallback_threshold <= 1.0):
            raise ValueError("ml_fallback_threshold must be in [0,1]")
        return self


class BudgetControl(BaseModel):
    """Budget control settings for pattern matching."""
    model_config = ConfigDict(extra="forbid")
    
    budget_ms_soft: float = Field(default=40.0, ge=1.0, le=1000.0, description="Soft budget limit in milliseconds")
    budget_ms_hard: float = Field(default=100.0, ge=1.0, le=1000.0, description="Hard budget limit in milliseconds")
    max_regex_length: int = Field(default=4096, ge=100, le=10000, description="Maximum regex pattern length")
    max_keywords_total: int = Field(default=200000, ge=1000, le=1000000, description="Maximum total keywords")
    
    @model_validator(mode='after')
    def validate_budget_limits(self) -> 'BudgetControl':
        if self.budget_ms_soft >= self.budget_ms_hard:
            raise ValueError("budget_ms_soft must be less than budget_ms_hard")
        return self


class PerformanceStats(BaseModel):
    """Performance statistics for pattern matching."""
    model_config = ConfigDict(extra="forbid")
    
    patterns_added: int = Field(default=0, ge=0, description="Number of patterns added")
    matches_found: int = Field(default=0, ge=0, description="Number of matches found")
    total_time_ms: float = Field(default=0.0, ge=0.0, description="Total processing time in milliseconds")
    budget_exceeded: bool = Field(default=False, description="Whether budget was exceeded")
    avg_match_time_ms: float = Field(default=0.0, ge=0.0, description="Average time per match")
    
    @computed_field
    @property
    def efficiency_ratio(self) -> float:
        """Calculate efficiency ratio (matches per millisecond)."""
        if self.total_time_ms == 0:
            return 0.0
        return self.matches_found / self.total_time_ms


class DomainStats(BaseModel):
    """Statistics for a specific domain."""
    model_config = ConfigDict(extra="forbid")
    
    domain: Domain = Field(description="Domain name")
    pattern_count: int = Field(ge=0, description="Number of patterns in this domain")
    event_types: List[EventType] = Field(default_factory=list, description="Event types in this domain")
    avg_priority: float = Field(ge=0.0, le=1000.0, description="Average priority")
    avg_confidence: float = Field(ge=0.0, le=1.0, description="Average confidence")
    coverage_percentage: float = Field(ge=0.0, le=100.0, description="Coverage percentage")


# =========================
# PKG Helper Functions and Utilities
# =========================

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
        """Create a rule provenance record."""
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
        snapshot: PKGSnapshot,
        subtasks: Optional[List[ProtoSubtask]] = None,
        edges: Optional[List[ProtoDagEdge]] = None,
        provenance: Optional[List[RuleProvenance]] = None,
        deployment_target: Optional[str] = None,
        deployment_region: Optional[str] = None,
        deployment_percent: Optional[int] = None
    ) -> PKGHint:
        """Create a PKG hint from a snapshot."""
        return PKGHint(
            subtasks=subtasks or [],
            edges=edges or [],
            provenance=provenance or [],
            applied_snapshot=snapshot.version,
            snapshot_id=snapshot.id,
            snapshot_env=snapshot.env,
            snapshot_checksum=snapshot.checksum,
            deployment_target=deployment_target,
            deployment_region=deployment_region,
            deployment_percent=deployment_percent
        )
    
    @staticmethod
    def validate_snapshot_checksum(snapshot: PKGSnapshot, expected_checksum: str) -> bool:
        """Validate snapshot checksum."""
        return snapshot.checksum.lower() == expected_checksum.lower()
    
    @staticmethod
    def is_snapshot_active(snapshot: PKGSnapshot) -> bool:
        """Check if snapshot is active."""
        return snapshot.is_active
    
    @staticmethod
    def create_validation_fixture(
        snapshot_id: int,
        name: str,
        input_data: Dict[str, Any],
        expected_output: Dict[str, Any]
    ) -> PKGValidationFixture:
        """Create a validation fixture."""
        return PKGValidationFixture(
            snapshot_id=snapshot_id,
            name=name,
            input=input_data,
            expect=expected_output
        )
    
    @staticmethod
    def create_temporal_fact(
        subject: str,
        predicate: str,
        object_data: Dict[str, Any],
        snapshot_id: Optional[int] = None,
        namespace: str = "default",
        valid_from: Optional[datetime] = None,
        valid_to: Optional[datetime] = None,
        created_by: str = "system"
    ) -> PKGFact:
        """Create a temporal policy fact."""
        return PKGFact(
            snapshot_id=snapshot_id,
            namespace=namespace,
            subject=subject,
            predicate=predicate,
            object=object_data,
            valid_from=valid_from or datetime.now(timezone.utc),
            valid_to=valid_to,
            created_by=created_by
        )


class PKGValidationResult(BaseModel):
    """Result of PKG validation operation."""
    success: bool = Field(..., description="Whether validation succeeded")
    snapshot_id: int = Field(..., description="PKG snapshot ID")
    snapshot_version: str = Field(..., description="PKG snapshot version")
    validation_time_ms: float = Field(..., ge=0.0, description="Validation time in milliseconds")
    fixtures_tested: int = Field(0, ge=0, description="Number of fixtures tested")
    fixtures_passed: int = Field(0, ge=0, description="Number of fixtures passed")
    fixtures_failed: int = Field(0, ge=0, description="Number of fixtures failed")
    error_message: Optional[str] = Field(None, description="Error message if validation failed")
    report: Optional[Dict[str, Any]] = Field(None, description="Detailed validation report")
    
    model_config = ConfigDict(extra="forbid")
    
    @computed_field
    @property
    def success_rate(self) -> float:
        """Success rate of validation fixtures."""
        if self.fixtures_tested == 0:
            return 0.0
        return self.fixtures_passed / self.fixtures_tested


class PKGDeploymentStatus(BaseModel):
    """PKG deployment status information."""
    target: str = Field(..., description="Deployment target")
    region: str = Field(..., description="Deployment region")
    snapshot_id: int = Field(..., description="PKG snapshot ID")
    snapshot_version: str = Field(..., description="PKG snapshot version")
    is_active: bool = Field(..., description="Whether deployment is active")
    percent: int = Field(..., ge=0, le=100, description="Deployment percentage")
    devices_total: int = Field(0, ge=0, description="Total devices")
    devices_on_snapshot: int = Field(0, ge=0, description="Devices running target snapshot")
    activated_at: datetime = Field(..., description="Activation timestamp")
    activated_by: str = Field(..., description="Activation actor")
    
    model_config = ConfigDict(extra="forbid")
    
    @computed_field
    @property
    def coverage_percentage(self) -> float:
        """Device coverage percentage."""
        if self.devices_total == 0:
            return 0.0
        return (self.devices_on_snapshot / self.devices_total) * 100.0
    
    @computed_field
    @property
    def is_fully_deployed(self) -> bool:
        """Whether deployment is at 100%."""
        return self.percent == 100 and self.is_active
