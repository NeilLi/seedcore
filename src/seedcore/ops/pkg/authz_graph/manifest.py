from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .ontology import PermissionEffect


def _normalize_required_str(value: str, *, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _normalize_optional_str(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


class PolicyEdgeManifest(BaseModel):
    """
    Snapshot-authored authorization edge definition.

    This is distinct from the runtime authz graph ontology. It represents what a
    policy author declares in snapshot rule metadata, which is later projected
    into `AuthzEdge` records.
    """

    model_config = ConfigDict(extra="forbid")

    source_selector: str
    target_selector: str
    relationship: str = "can"
    operation: str
    effect: PermissionEffect = PermissionEffect.ALLOW
    conditions: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    rule_id: Optional[str] = None
    rule_name: Optional[str] = None

    @field_validator("source_selector", "target_selector", "relationship", "operation")
    @classmethod
    def _validate_required_fields(cls, value: str, info) -> str:
        normalized = _normalize_required_str(value, field_name=info.field_name)
        if info.field_name in {"relationship", "operation"}:
            return normalized.lower() if info.field_name == "relationship" else normalized.upper()
        return normalized

    @field_validator("rule_id", "rule_name")
    @classmethod
    def _validate_optional_fields(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_str(value)

    @property
    def requires_break_glass(self) -> bool:
        return bool(self.conditions.get("requires_break_glass"))

    @property
    def bypass_deny(self) -> bool:
        relationship = self.relationship.strip().lower()
        return relationship == "can_bypass" or bool(self.conditions.get("bypass_deny"))


def extract_policy_edge_manifests(
    *,
    rule_id: Any,
    rule_name: Any,
    metadata: Any,
) -> List[PolicyEdgeManifest]:
    if not isinstance(metadata, Mapping):
        return []

    authz_graph = metadata.get("authz_graph")
    if isinstance(authz_graph, Mapping):
        raw_manifests = authz_graph.get("edge_manifests")
    else:
        raw_manifests = metadata.get("edge_manifests")

    if not isinstance(raw_manifests, Iterable) or isinstance(raw_manifests, (str, bytes, Mapping)):
        return []

    manifests: List[PolicyEdgeManifest] = []
    normalized_rule_id = _normalize_optional_str(str(rule_id) if rule_id is not None else None)
    normalized_rule_name = _normalize_optional_str(str(rule_name) if rule_name is not None else None)
    for item in raw_manifests:
        if not isinstance(item, Mapping):
            continue
        payload = dict(item)
        payload.setdefault("rule_id", normalized_rule_id)
        payload.setdefault("rule_name", normalized_rule_name)
        manifests.append(PolicyEdgeManifest(**payload))
    return manifests
