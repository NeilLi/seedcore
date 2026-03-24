from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_ref(value: str, *, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _normalize_optional_ref(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_timestamp(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = _normalize_ref(value, field_name="timestamp")
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _freeze_value(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple((key, _freeze_value(val)) for key, val in sorted(value.items()))
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    return value


class NodeKind(str, Enum):
    POLICY_RULE = "policy_rule"
    CONSTRAINT = "constraint"
    ORG = "org"
    PRINCIPAL = "principal"
    ROLE_PROFILE = "role_profile"
    DEVICE = "device"
    FACILITY = "facility"
    CERTIFICATION = "certification"
    PRODUCT = "product"
    WORKFLOW_STAGE = "workflow_stage"
    ASSET = "asset"
    ASSET_BATCH = "asset_batch"
    RESOURCE = "resource"
    ZONE = "zone"
    NETWORK_SEGMENT = "network_segment"
    CUSTODY_POINT = "custody_point"
    REGISTRATION = "registration"
    ATTESTATION = "attestation"
    INSPECTION = "inspection"
    SENSOR_OBSERVATION = "sensor_observation"
    HANDSHAKE_INTENT = "handshake_intent"
    DIGITAL_PASSPORT_FRAGMENT = "digital_passport_fragment"
    TRACKING_EVENT = "tracking_event"
    FACT = "fact"
    POLICY_SNAPSHOT = "policy_snapshot"
    TWIN = "twin"
    RECEIPT = "receipt"
    REGISTRATION_DECISION = "registration_decision"


class EdgeKind(str, Enum):
    MEMBER_OF = "member_of"
    HAS_ROLE = "has_role"
    DELEGATED_TO = "delegated_to"
    DELEGATED_BY = "delegated_by"
    APPROVED_FOR = "approved_for"
    OPERATES = "operates"
    CONTROLS = "controls"
    BOUND_TO_DEVICE = "bound_to_device"
    CERTIFIED_FOR = "certified_for"
    REQUIRES = "requires"
    PART_OF = "part_of"
    CAN = "can"
    HELD_BY = "held_by"
    TRANSFERRED_FROM = "transferred_from"
    ATTESTED_BY = "attested_by"
    OBSERVED_IN = "observed_in"
    SEALED_WITH = "sealed_with"
    LOCATED_IN = "located_in"
    AT_STAGE = "at_stage"
    REQUESTED = "requested"
    BACKED_BY = "backed_by"
    RECORDED_BY = "recorded_by"
    GOVERNED_BY = "governed_by"


class PermissionEffect(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


class GraphProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: str
    source_ref: str
    snapshot_id: Optional[int] = None
    snapshot_version: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_type", "source_ref")
    @classmethod
    def _validate_required_fields(cls, value: str, info) -> str:
        return _normalize_ref(value, field_name=info.field_name)

    @field_validator("snapshot_version")
    @classmethod
    def _validate_optional_refs(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_ref(value)


class AuthzNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: NodeKind
    ref: str
    display_name: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    provenance: Optional[GraphProvenance] = None

    @field_validator("ref")
    @classmethod
    def _validate_ref(cls, value: str) -> str:
        return _normalize_ref(value, field_name="ref")

    @field_validator("display_name")
    @classmethod
    def _validate_display_name(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_ref(value)

    @field_validator("valid_from", "valid_to")
    @classmethod
    def _validate_timestamps(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_timestamp(value)


class AuthzEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: EdgeKind
    src: str
    dst: str
    operation: Optional[str] = None
    effect: PermissionEffect = PermissionEffect.ALLOW
    constraints: Dict[str, Any] = Field(default_factory=dict)
    attributes: Dict[str, Any] = Field(default_factory=dict)
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    provenance: Optional[GraphProvenance] = None

    @field_validator("src", "dst")
    @classmethod
    def _validate_refs(cls, value: str, info) -> str:
        return _normalize_ref(value, field_name=info.field_name)

    @field_validator("operation")
    @classmethod
    def _validate_operation(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_ref(value.upper() if isinstance(value, str) else value)

    @field_validator("valid_from", "valid_to")
    @classmethod
    def _validate_timestamps(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_timestamp(value)


class AuthzGraphSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_ref: str
    snapshot_id: Optional[int] = None
    snapshot_version: Optional[str] = None
    generated_at: str
    nodes: List[AuthzNode] = Field(default_factory=list)
    edges: List[AuthzEdge] = Field(default_factory=list)

    @field_validator("snapshot_ref", "snapshot_version")
    @classmethod
    def _validate_optional_refs(cls, value: Optional[str], info) -> Optional[str]:
        if value is None and info.field_name == "snapshot_version":
            return None
        if value is None:
            raise ValueError(f"{info.field_name} must not be empty")
        return _normalize_ref(value, field_name=info.field_name)

    @field_validator("generated_at")
    @classmethod
    def _validate_generated_at(cls, value: str) -> str:
        return _normalize_timestamp(value) or value

    def deduplicated(self) -> "AuthzGraphSnapshot":
        node_map = {node.ref: node for node in self.nodes}
        edge_map = {
            (
                edge.kind.value,
                edge.src,
                edge.dst,
                edge.operation,
                edge.effect.value,
                edge.valid_from,
                edge.valid_to,
                _freeze_value(edge.constraints),
            ): edge
            for edge in self.edges
        }
        return self.model_copy(update={"nodes": list(node_map.values()), "edges": list(edge_map.values())})
