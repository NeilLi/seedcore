from __future__ import annotations

from collections import deque
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Deque, Dict, Iterable, List, Optional, Set, Tuple

from .ontology import AuthzEdge, AuthzGraphSnapshot, AuthzNode, EdgeKind, NodeKind, PermissionEffect


def _parse_iso8601(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_optional_ref(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_required_ref(value: str, *, field_name: str) -> str:
    normalized = _normalize_optional_ref(value)
    if normalized is None:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _as_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _candidate_timestamp(*values: Optional[str | datetime]) -> Optional[datetime]:
    for value in values:
        if value is None:
            continue
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        parsed = _parse_iso8601(str(value))
        if parsed is not None:
            return parsed
    return None


def _prefer_latest(current: Optional[datetime], candidate: Optional[datetime]) -> Optional[datetime]:
    if candidate is None:
        return current
    if current is None or candidate > current:
        return candidate
    return current


def _merge_quality_score(current: Optional[float], candidate: Optional[float]) -> Optional[float]:
    if candidate is None:
        return current
    if current is None:
        return candidate
    return min(current, candidate)


def _canonical_json(data: Dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def _operation_matches(permission_operation: str, requested_operation: str) -> bool:
    permission_op = str(permission_operation).strip().upper()
    requested_op = str(requested_operation).strip().upper()
    if permission_op == requested_op:
        return True
    if permission_op == "ACTION":
        return True
    if permission_op == "MUTATE" and requested_op in {
        "MOVE",
        "PICK",
        "PLACE",
        "SCAN",
        "PACK",
        "RELEASE",
    }:
        return True
    return False


class AuthzDecisionDisposition(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    QUARANTINE = "quarantine"


TRANSFER_TRUST_GAP_TAXONOMY: Tuple[str, ...] = (
    "missing_current_custodian",
    "missing_custody_point",
    "missing_asset_state",
    "unknown_transfer_state",
    "missing_telemetry",
    "stale_telemetry",
    "missing_inspection",
    "stale_inspection",
    "missing_attestation",
    "missing_seal",
)


@dataclass(frozen=True)
class CompiledDecisionGraphSnapshot:
    snapshot_ref: str
    snapshot_id: Optional[int]
    snapshot_version: Optional[str]
    compiled_at: str
    snapshot_hash: str
    hot_path_workflow: str = "restricted_custody_transfer"
    trust_gap_taxonomy: Tuple[str, ...] = TRANSFER_TRUST_GAP_TAXONOMY
    entity_refs: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    authority_index: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    resource_index: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    asset_state_index: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    transition_requirements: Dict[str, Tuple[Dict[str, Any], ...]] = field(default_factory=dict)
    policy_refs: Tuple[str, ...] = ()
    provenance_refs: Tuple[str, ...] = ()
    restricted_transfer_ready: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_ref": self.snapshot_ref,
            "snapshot_id": self.snapshot_id,
            "snapshot_version": self.snapshot_version,
            "compiled_at": self.compiled_at,
            "snapshot_hash": self.snapshot_hash,
            "hot_path_workflow": self.hot_path_workflow,
            "trust_gap_taxonomy": list(self.trust_gap_taxonomy),
            "entity_refs": {key: list(value) for key, value in self.entity_refs.items()},
            "authority_index": {key: list(value) for key, value in self.authority_index.items()},
            "resource_index": {key: dict(value) for key, value in self.resource_index.items()},
            "asset_state_index": {key: dict(value) for key, value in self.asset_state_index.items()},
            "transition_requirements": {
                key: [dict(item) for item in value]
                for key, value in self.transition_requirements.items()
            },
            "policy_refs": list(self.policy_refs),
            "provenance_refs": list(self.provenance_refs),
            "restricted_transfer_ready": self.restricted_transfer_ready,
        }


@dataclass(frozen=True)
class CompiledTrustGap:
    code: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompiledConstraintCheck:
    code: str
    outcome: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GovernedDecisionReceipt:
    decision_hash: str
    disposition: AuthzDecisionDisposition
    snapshot_ref: str
    snapshot_id: Optional[int]
    snapshot_version: Optional[str]
    snapshot_hash: Optional[str]
    principal_ref: str
    operation: str
    asset_ref: Optional[str]
    resource_ref: Optional[str]
    twin_ref: Optional[str]
    reason: str
    generated_at: str
    custody_proof: Tuple[str, ...] = ()
    evidence_refs: Tuple[str, ...] = ()
    trust_gap_codes: Tuple[str, ...] = ()
    provenance_sources: Tuple[str, ...] = ()
    advisory: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuthzTransitionRequest:
    principal_ref: str
    operation: str
    resource_ref: Optional[str] = None
    asset_ref: Optional[str] = None
    source_registration_ref: Optional[str] = None
    registration_decision_ref: Optional[str] = None
    workflow_stage_ref: Optional[str] = None
    zone_ref: Optional[str] = None
    network_ref: Optional[str] = None
    custody_point_ref: Optional[str] = None
    resource_state_hash: Optional[str] = None
    expected_custodian_ref: Optional[str] = None
    require_current_custodian: bool = False
    require_transferable_state: bool = False
    max_telemetry_age_seconds: Optional[int] = None
    max_inspection_age_seconds: Optional[int] = None
    require_attestation: bool = False
    require_seal: bool = False
    require_approved_source_registration: bool = False
    allow_quarantine: bool = True
    break_glass: bool = False
    at: Optional[datetime] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "principal_ref", _normalize_required_ref(self.principal_ref, field_name="principal_ref"))
        object.__setattr__(self, "operation", _normalize_required_ref(self.operation, field_name="operation").upper())
        object.__setattr__(self, "resource_ref", _normalize_optional_ref(self.resource_ref))
        object.__setattr__(self, "asset_ref", _normalize_optional_ref(self.asset_ref))
        object.__setattr__(self, "source_registration_ref", _normalize_optional_ref(self.source_registration_ref))
        object.__setattr__(self, "registration_decision_ref", _normalize_optional_ref(self.registration_decision_ref))
        object.__setattr__(self, "workflow_stage_ref", _normalize_optional_ref(self.workflow_stage_ref))
        object.__setattr__(self, "zone_ref", _normalize_optional_ref(self.zone_ref))
        object.__setattr__(self, "network_ref", _normalize_optional_ref(self.network_ref))
        object.__setattr__(self, "custody_point_ref", _normalize_optional_ref(self.custody_point_ref))
        object.__setattr__(self, "resource_state_hash", _normalize_optional_ref(self.resource_state_hash))
        object.__setattr__(self, "expected_custodian_ref", _normalize_optional_ref(self.expected_custodian_ref))
        if self.at is not None and self.at.tzinfo is None:
            object.__setattr__(self, "at", self.at.replace(tzinfo=timezone.utc))


@dataclass(frozen=True)
class CompiledTransitionEvaluation:
    disposition: AuthzDecisionDisposition
    reason: str
    permission_match: "CompiledPermissionMatch"
    receipt: GovernedDecisionReceipt
    asset_ref: Optional[str] = None
    resource_ref: Optional[str] = None
    current_custodian: Optional[str] = None
    trust_gaps: Tuple[CompiledTrustGap, ...] = ()
    checked_constraints: Tuple[CompiledConstraintCheck, ...] = ()
    restricted_token_recommended: bool = False

    @property
    def allowed(self) -> bool:
        return self.disposition == AuthzDecisionDisposition.ALLOW

    @property
    def quarantined(self) -> bool:
        return self.disposition == AuthzDecisionDisposition.QUARANTINE


@dataclass
class CompiledAssetState:
    asset_ref: str
    twin_ref: Optional[str] = None
    batch_ref: Optional[str] = None
    product_ref: Optional[str] = None
    state: Optional[str] = None
    transferable: Optional[bool] = None
    restricted: Optional[bool] = None
    current_custodian: Optional[str] = None
    previous_custodians: Set[str] = field(default_factory=set)
    zones: Set[str] = field(default_factory=set)
    custody_points: Set[str] = field(default_factory=set)
    attestation_refs: Set[str] = field(default_factory=set)
    inspection_refs: Set[str] = field(default_factory=set)
    seal_refs: Set[str] = field(default_factory=set)
    evidence_refs: Set[str] = field(default_factory=set)
    registration_refs: Set[str] = field(default_factory=set)
    approved_registration_refs: Set[str] = field(default_factory=set)
    registration_decision_refs: Set[str] = field(default_factory=set)
    last_telemetry_at: Optional[datetime] = None
    last_inspection_at: Optional[datetime] = None
    evidence_quality_score: Optional[float] = None


@dataclass(frozen=True)
class CompiledPermission:
    subject_ref: str
    resource_ref: str
    operation: str
    effect: PermissionEffect
    zones: frozenset[str] = frozenset()
    networks: frozenset[str] = frozenset()
    custody_points: frozenset[str] = frozenset()
    workflow_stages: frozenset[str] = frozenset()
    resource_state_hash: Optional[str] = None
    requires_break_glass: bool = False
    bypass_deny: bool = False
    required_current_custodian: bool = False
    required_transferable_state: bool = False
    max_telemetry_age_seconds: Optional[int] = None
    max_inspection_age_seconds: Optional[int] = None
    require_attestation: bool = False
    require_seal: bool = False
    require_approved_source_registration: bool = False
    allow_quarantine: bool = True
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    provenance_source: Optional[str] = None


@dataclass(frozen=True)
class CompiledPermissionMatch:
    allowed: bool
    matched_subjects: Tuple[str, ...] = ()
    authority_paths: Tuple[Tuple[str, ...], ...] = ()
    matched_permissions: Tuple[CompiledPermission, ...] = ()
    deny_permissions: Tuple[CompiledPermission, ...] = ()
    break_glass_permissions: Tuple[CompiledPermission, ...] = ()
    break_glass_required: bool = False
    break_glass_used: bool = False
    reason: str = "no_matching_permission"


@dataclass
class CompiledAuthzIndex:
    snapshot_ref: str
    snapshot_id: Optional[int]
    snapshot_version: Optional[str]
    compiled_at: Optional[str] = None
    role_memberships: Dict[str, Set[str]] = field(default_factory=dict)
    delegations: Dict[str, Set[str]] = field(default_factory=dict)
    authority_links: Dict[str, Set[str]] = field(default_factory=dict)
    resource_zones: Dict[str, Set[str]] = field(default_factory=dict)
    permissions_by_subject: Dict[str, List[CompiledPermission]] = field(default_factory=dict)
    resource_to_asset: Dict[str, str] = field(default_factory=dict)
    resource_aliases_by_asset: Dict[str, Set[str]] = field(default_factory=dict)
    asset_states: Dict[str, CompiledAssetState] = field(default_factory=dict)
    nodes_by_ref: Dict[str, AuthzNode] = field(default_factory=dict)
    registration_decisions_by_registration: Dict[str, Set[str]] = field(default_factory=dict)
    decision_graph_snapshot: Optional[CompiledDecisionGraphSnapshot] = None

    @property
    def snapshot_hash(self) -> Optional[str]:
        if self.decision_graph_snapshot is None:
            return None
        return self.decision_graph_snapshot.snapshot_hash

    @property
    def restricted_transfer_ready(self) -> bool:
        return bool(self.decision_graph_snapshot and self.decision_graph_snapshot.restricted_transfer_ready)

    def resolve_subject_paths(self, principal_ref: str) -> Dict[str, Tuple[str, ...]]:
        paths: Dict[str, Tuple[str, ...]] = {principal_ref: (principal_ref,)}
        queue: Deque[str] = deque([principal_ref])

        while queue:
            current = queue.popleft()
            current_path = paths[current]
            next_subjects = sorted(self.authority_links.get(current, set()))
            for next_subject in next_subjects:
                if next_subject in paths:
                    continue
                paths[next_subject] = current_path + (next_subject,)
                queue.append(next_subject)
        return paths

    def resolve_subjects(self, principal_ref: str) -> Tuple[str, ...]:
        return tuple(self.resolve_subject_paths(principal_ref).keys())

    def can_access(
        self,
        *,
        principal_ref: str,
        operation: str,
        resource_ref: str,
        zone_ref: Optional[str] = None,
        network_ref: Optional[str] = None,
        workflow_stage_ref: Optional[str] = None,
        resource_state_hash: Optional[str] = None,
        at: Optional[datetime] = None,
        break_glass: bool = False,
    ) -> CompiledPermissionMatch:
        effective_at = at.astimezone(timezone.utc) if at and at.tzinfo else at or _utcnow()
        subject_paths = self.resolve_subject_paths(principal_ref)
        subject_refs = tuple(subject_paths.keys())
        allow_matches: List[CompiledPermission] = []
        deny_matches: List[CompiledPermission] = []
        break_glass_matches: List[CompiledPermission] = []
        authority_paths: List[Tuple[str, ...]] = []
        seen_paths: Set[Tuple[str, ...]] = set()
        expected_op = str(operation).strip().upper()
        effective_zone = _normalize_optional_ref(zone_ref)
        effective_network = _normalize_optional_ref(network_ref)
        effective_workflow_stage = _normalize_optional_ref(workflow_stage_ref)
        effective_hash = _normalize_optional_ref(resource_state_hash)
        known_zones = self.resource_zones.get(resource_ref, set())

        for subject_ref in subject_refs:
            for permission in self.permissions_by_subject.get(subject_ref, []):
                if not _operation_matches(permission.operation, expected_op):
                    continue
                if permission.resource_ref != resource_ref:
                    continue
                if permission.valid_from and effective_at < permission.valid_from:
                    continue
                if permission.valid_to and effective_at > permission.valid_to:
                    continue
                if permission.zones:
                    if effective_zone is not None:
                        if effective_zone not in permission.zones:
                            continue
                    elif known_zones and permission.zones.isdisjoint(known_zones):
                        continue
                if permission.networks and effective_network not in permission.networks:
                    continue
                if permission.workflow_stages and effective_workflow_stage not in permission.workflow_stages:
                    continue
                if permission.resource_state_hash and effective_hash != permission.resource_state_hash:
                    continue
                if permission.effect == PermissionEffect.DENY:
                    deny_matches.append(permission)
                elif permission.requires_break_glass or permission.bypass_deny:
                    break_glass_matches.append(permission)
                else:
                    allow_matches.append(permission)
                authority_path = subject_paths.get(subject_ref)
                if authority_path is not None and authority_path not in seen_paths:
                    seen_paths.add(authority_path)
                    authority_paths.append(authority_path)

        if deny_matches:
            if break_glass and break_glass_matches and any(item.bypass_deny for item in break_glass_matches):
                return CompiledPermissionMatch(
                    allowed=True,
                    matched_subjects=subject_refs,
                    authority_paths=tuple(authority_paths),
                    matched_permissions=tuple(allow_matches),
                    deny_permissions=tuple(deny_matches),
                    break_glass_permissions=tuple(break_glass_matches),
                    break_glass_required=True,
                    break_glass_used=True,
                    reason="break_glass_override",
                )
            return CompiledPermissionMatch(
                allowed=False,
                matched_subjects=subject_refs,
                authority_paths=tuple(authority_paths),
                matched_permissions=tuple(allow_matches),
                deny_permissions=tuple(deny_matches),
                break_glass_permissions=tuple(break_glass_matches),
                break_glass_required=bool(break_glass_matches),
                reason="explicit_deny",
            )
        if allow_matches:
            return CompiledPermissionMatch(
                allowed=True,
                matched_subjects=subject_refs,
                authority_paths=tuple(authority_paths),
                matched_permissions=tuple(allow_matches),
                deny_permissions=(),
                break_glass_permissions=tuple(break_glass_matches),
                break_glass_required=False,
                break_glass_used=False,
                reason="matched_allow_permission",
            )
        if break_glass_matches:
            if break_glass:
                return CompiledPermissionMatch(
                    allowed=True,
                    matched_subjects=subject_refs,
                    authority_paths=tuple(authority_paths),
                    matched_permissions=tuple(allow_matches),
                    deny_permissions=(),
                    break_glass_permissions=tuple(break_glass_matches),
                    break_glass_required=True,
                    break_glass_used=True,
                    reason="matched_break_glass_permission",
                )
            return CompiledPermissionMatch(
                allowed=False,
                matched_subjects=subject_refs,
                authority_paths=tuple(authority_paths),
                matched_permissions=tuple(allow_matches),
                deny_permissions=(),
                break_glass_permissions=tuple(break_glass_matches),
                break_glass_required=True,
                break_glass_used=False,
                reason="break_glass_required",
            )
        return CompiledPermissionMatch(
            allowed=False,
            matched_subjects=subject_refs,
            authority_paths=(),
            matched_permissions=(),
            deny_permissions=(),
            break_glass_permissions=(),
            break_glass_required=False,
            break_glass_used=False,
            reason="no_matching_permission",
        )

    def evaluate_transition(self, request: AuthzTransitionRequest) -> CompiledTransitionEvaluation:
        target_ref, permission_match = self._resolve_transition_permission_match(request)
        asset_ref = request.asset_ref or self.resource_to_asset.get(target_ref or "")
        asset_state = self.asset_states.get(asset_ref) if asset_ref else None

        if not permission_match.allowed:
            receipt = self._mint_receipt(
                disposition=AuthzDecisionDisposition.DENY,
                reason=permission_match.reason,
                request=request,
                permission_match=permission_match,
                asset_state=asset_state,
            )
            return CompiledTransitionEvaluation(
                disposition=AuthzDecisionDisposition.DENY,
                reason=permission_match.reason,
                permission_match=permission_match,
                receipt=receipt,
                asset_ref=asset_ref,
                resource_ref=target_ref,
                current_custodian=asset_state.current_custodian if asset_state else None,
            )

        requirements = self._collect_transition_requirements(request, permission_match)
        deny_reasons: List[str] = []
        trust_gaps: List[CompiledTrustGap] = []
        checked_constraints: List[CompiledConstraintCheck] = []

        if requirements.require_current_custodian:
            if asset_state is None or asset_state.current_custodian is None:
                checked_constraints.append(
                    CompiledConstraintCheck(
                        code="current_custodian",
                        outcome="missing",
                        message="The asset has no compiled current custodian.",
                        details={"asset_ref": asset_ref},
                    )
                )
                trust_gaps.append(
                    CompiledTrustGap(
                        code="missing_current_custodian",
                        message="The asset has no compiled current custodian.",
                        details={"asset_ref": asset_ref},
                    )
                )
            else:
                if request.expected_custodian_ref and asset_state.current_custodian != request.expected_custodian_ref:
                    checked_constraints.append(
                        CompiledConstraintCheck(
                            code="expected_custodian",
                            outcome="failed",
                            message="The compiled current custodian does not match the expected custodian.",
                            details={
                                "asset_ref": asset_ref,
                                "expected_custodian_ref": request.expected_custodian_ref,
                                "current_custodian": asset_state.current_custodian,
                            },
                        )
                    )
                    deny_reasons.append("expected_custodian_mismatch")
                if asset_state.current_custodian != request.principal_ref:
                    checked_constraints.append(
                        CompiledConstraintCheck(
                            code="current_custodian",
                            outcome="failed",
                            message="The principal is not the compiled current custodian.",
                            details={
                                "asset_ref": asset_ref,
                                "principal_ref": request.principal_ref,
                                "current_custodian": asset_state.current_custodian,
                            },
                        )
                    )
                    deny_reasons.append("principal_not_current_custodian")
                if not deny_reasons:
                    checked_constraints.append(
                        CompiledConstraintCheck(
                            code="current_custodian",
                            outcome="passed",
                            message="The principal matches the compiled current custodian.",
                            details={
                                "asset_ref": asset_ref,
                                "principal_ref": request.principal_ref,
                                "current_custodian": asset_state.current_custodian,
                            },
                        )
                    )
        elif request.expected_custodian_ref:
            if asset_state is None or asset_state.current_custodian is None:
                checked_constraints.append(
                    CompiledConstraintCheck(
                        code="expected_custodian",
                        outcome="missing",
                        message="The asset has no compiled current custodian for expected-custodian validation.",
                        details={"asset_ref": asset_ref, "expected_custodian_ref": request.expected_custodian_ref},
                    )
                )
                trust_gaps.append(
                    CompiledTrustGap(
                        code="missing_current_custodian",
                        message="The asset has no compiled current custodian.",
                        details={"asset_ref": asset_ref},
                    )
                )
            elif asset_state.current_custodian != request.expected_custodian_ref:
                checked_constraints.append(
                    CompiledConstraintCheck(
                        code="expected_custodian",
                        outcome="failed",
                        message="The compiled current custodian does not match the expected custodian.",
                        details={
                            "asset_ref": asset_ref,
                            "expected_custodian_ref": request.expected_custodian_ref,
                            "current_custodian": asset_state.current_custodian,
                        },
                    )
                )
                deny_reasons.append("expected_custodian_mismatch")
            else:
                checked_constraints.append(
                    CompiledConstraintCheck(
                        code="expected_custodian",
                        outcome="passed",
                        message="The compiled current custodian matches the expected custodian.",
                        details={
                            "asset_ref": asset_ref,
                            "expected_custodian_ref": request.expected_custodian_ref,
                            "current_custodian": asset_state.current_custodian,
                        },
                    )
                )

        if requirements.custody_points:
            if request.custody_point_ref is not None and request.custody_point_ref not in requirements.custody_points:
                checked_constraints.append(
                    CompiledConstraintCheck(
                        code="custody_point",
                        outcome="failed",
                        message="The request custody point is not allowed by the compiled transition requirements.",
                        details={
                            "provided_custody_point_ref": request.custody_point_ref,
                            "required_custody_points": sorted(requirements.custody_points),
                        },
                    )
                )
                deny_reasons.append("custody_point_mismatch")
            elif asset_state is not None and asset_state.custody_points:
                if requirements.custody_points.isdisjoint(asset_state.custody_points):
                    checked_constraints.append(
                        CompiledConstraintCheck(
                            code="custody_point",
                            outcome="failed",
                            message="The asset is not currently in one of the required custody points.",
                            details={
                                "asset_custody_points": sorted(asset_state.custody_points),
                                "required_custody_points": sorted(requirements.custody_points),
                            },
                        )
                    )
                    deny_reasons.append("asset_not_in_required_custody_point")
                else:
                    checked_constraints.append(
                        CompiledConstraintCheck(
                            code="custody_point",
                            outcome="passed",
                            message="The asset matches the required custody point constraints.",
                            details={
                                "asset_custody_points": sorted(asset_state.custody_points),
                                "required_custody_points": sorted(requirements.custody_points),
                            },
                        )
                    )
            elif request.custody_point_ref is None:
                checked_constraints.append(
                    CompiledConstraintCheck(
                        code="custody_point",
                        outcome="missing",
                        message="The transition requires a custody point but none was provided.",
                        details={"required_custody_points": sorted(requirements.custody_points)},
                    )
                )
                trust_gaps.append(
                    CompiledTrustGap(
                        code="missing_custody_point",
                        message="The transition requires a custody point but none was provided.",
                        details={"required_custody_points": sorted(requirements.custody_points)},
                    )
                )

        if requirements.require_transferable_state:
            if asset_state is None:
                checked_constraints.append(
                    CompiledConstraintCheck(
                        code="transferable_state",
                        outcome="missing",
                        message="The asset has no compiled state for transfer validation.",
                        details={"asset_ref": asset_ref},
                    )
                )
                trust_gaps.append(
                    CompiledTrustGap(
                        code="missing_asset_state",
                        message="The asset has no compiled state for transfer validation.",
                        details={"asset_ref": asset_ref},
                    )
                )
            else:
                if asset_state.restricted is True:
                    checked_constraints.append(
                        CompiledConstraintCheck(
                            code="transferable_state",
                            outcome="failed",
                            message="The asset is already restricted.",
                            details={"asset_ref": asset_ref},
                        )
                    )
                    deny_reasons.append("asset_restricted")
                elif asset_state.transferable is False:
                    checked_constraints.append(
                        CompiledConstraintCheck(
                            code="transferable_state",
                            outcome="failed",
                            message="The asset is not in a transferable state.",
                            details={"asset_ref": asset_ref, "state": asset_state.state},
                        )
                    )
                    deny_reasons.append("asset_not_transferable")
                elif asset_state.transferable is None and asset_state.state is None:
                    checked_constraints.append(
                        CompiledConstraintCheck(
                            code="transferable_state",
                            outcome="missing",
                            message="The asset does not expose a transferability state.",
                            details={"asset_ref": asset_ref},
                        )
                    )
                    trust_gaps.append(
                        CompiledTrustGap(
                            code="unknown_transfer_state",
                            message="The asset does not expose a transferability state.",
                            details={"asset_ref": asset_ref},
                        )
                    )
                else:
                    checked_constraints.append(
                        CompiledConstraintCheck(
                            code="transferable_state",
                            outcome="passed",
                            message="The asset is transferable under the compiled state.",
                            details={"asset_ref": asset_ref, "state": asset_state.state},
                        )
                    )

        effective_at = request.at.astimezone(timezone.utc) if request.at and request.at.tzinfo else request.at or _utcnow()
        if requirements.max_telemetry_age_seconds is not None:
            if asset_state is None or asset_state.last_telemetry_at is None:
                checked_constraints.append(
                    CompiledConstraintCheck(
                        code="telemetry_freshness",
                        outcome="missing",
                        message="The asset is missing compiled telemetry coverage.",
                        details={"asset_ref": asset_ref},
                    )
                )
                trust_gaps.append(
                    CompiledTrustGap(
                        code="missing_telemetry",
                        message="The asset is missing compiled telemetry coverage.",
                        details={"asset_ref": asset_ref},
                    )
                )
            elif effective_at - asset_state.last_telemetry_at > timedelta(seconds=requirements.max_telemetry_age_seconds):
                checked_constraints.append(
                    CompiledConstraintCheck(
                        code="telemetry_freshness",
                        outcome="failed",
                        message="The asset telemetry is older than the permitted trust window.",
                        details={
                            "asset_ref": asset_ref,
                            "last_telemetry_at": asset_state.last_telemetry_at.isoformat(),
                            "max_age_seconds": requirements.max_telemetry_age_seconds,
                        },
                    )
                )
                trust_gaps.append(
                    CompiledTrustGap(
                        code="stale_telemetry",
                        message="The asset telemetry is older than the permitted trust window.",
                        details={
                            "asset_ref": asset_ref,
                            "last_telemetry_at": asset_state.last_telemetry_at.isoformat(),
                            "max_age_seconds": requirements.max_telemetry_age_seconds,
                        },
                    )
                )
            else:
                checked_constraints.append(
                    CompiledConstraintCheck(
                        code="telemetry_freshness",
                        outcome="passed",
                        message="The asset telemetry is within the permitted trust window.",
                        details={
                            "asset_ref": asset_ref,
                            "last_telemetry_at": asset_state.last_telemetry_at.isoformat(),
                            "max_age_seconds": requirements.max_telemetry_age_seconds,
                        },
                    )
                )

        if requirements.max_inspection_age_seconds is not None:
            if asset_state is None or asset_state.last_inspection_at is None:
                checked_constraints.append(
                    CompiledConstraintCheck(
                        code="inspection_freshness",
                        outcome="missing",
                        message="The asset is missing a compiled inspection or attestation timestamp.",
                        details={"asset_ref": asset_ref},
                    )
                )
                trust_gaps.append(
                    CompiledTrustGap(
                        code="missing_inspection",
                        message="The asset is missing a compiled inspection or attestation timestamp.",
                        details={"asset_ref": asset_ref},
                    )
                )
            elif effective_at - asset_state.last_inspection_at > timedelta(seconds=requirements.max_inspection_age_seconds):
                checked_constraints.append(
                    CompiledConstraintCheck(
                        code="inspection_freshness",
                        outcome="failed",
                        message="The asset inspection is older than the permitted trust window.",
                        details={
                            "asset_ref": asset_ref,
                            "last_inspection_at": asset_state.last_inspection_at.isoformat(),
                            "max_age_seconds": requirements.max_inspection_age_seconds,
                        },
                    )
                )
                trust_gaps.append(
                    CompiledTrustGap(
                        code="stale_inspection",
                        message="The asset inspection is older than the permitted trust window.",
                        details={
                            "asset_ref": asset_ref,
                            "last_inspection_at": asset_state.last_inspection_at.isoformat(),
                            "max_age_seconds": requirements.max_inspection_age_seconds,
                        },
                    )
                )
            else:
                checked_constraints.append(
                    CompiledConstraintCheck(
                        code="inspection_freshness",
                        outcome="passed",
                        message="The asset inspection is within the permitted trust window.",
                        details={
                            "asset_ref": asset_ref,
                            "last_inspection_at": asset_state.last_inspection_at.isoformat(),
                            "max_age_seconds": requirements.max_inspection_age_seconds,
                        },
                    )
                )

        if requirements.require_attestation:
            if asset_state is None or not asset_state.attestation_refs:
                checked_constraints.append(
                    CompiledConstraintCheck(
                        code="attestation",
                        outcome="missing",
                        message="The asset has no compiled attestation references.",
                        details={"asset_ref": asset_ref},
                    )
                )
                trust_gaps.append(
                    CompiledTrustGap(
                        code="missing_attestation",
                        message="The asset has no compiled attestation references.",
                        details={"asset_ref": asset_ref},
                    )
                )
            else:
                checked_constraints.append(
                    CompiledConstraintCheck(
                        code="attestation",
                        outcome="passed",
                        message="The asset has compiled attestation references.",
                        details={"asset_ref": asset_ref, "attestation_refs": sorted(asset_state.attestation_refs)},
                    )
                )

        if requirements.require_seal:
            if asset_state is None or not asset_state.seal_refs:
                checked_constraints.append(
                    CompiledConstraintCheck(
                        code="seal",
                        outcome="missing",
                        message="The asset has no compiled seal binding.",
                        details={"asset_ref": asset_ref},
                    )
                )
                trust_gaps.append(
                    CompiledTrustGap(
                        code="missing_seal",
                        message="The asset has no compiled seal binding.",
                        details={"asset_ref": asset_ref},
                    )
                )
            else:
                checked_constraints.append(
                    CompiledConstraintCheck(
                        code="seal",
                        outcome="passed",
                        message="The asset has compiled seal evidence.",
                        details={"asset_ref": asset_ref, "seal_refs": sorted(asset_state.seal_refs)},
                    )
                )

        if requirements.require_approved_source_registration:
            effective_registration_refs, effective_approved_registration_refs, effective_registration_decision_refs = (
                self._resolve_registration_scope(asset_state)
            )
            if request.source_registration_ref is None:
                checked_constraints.append(
                    CompiledConstraintCheck(
                        code="source_registration",
                        outcome="missing",
                        message="The transition requires a source registration reference but none was provided.",
                        details={"asset_ref": asset_ref},
                    )
                )
                deny_reasons.append("missing_source_registration")
            elif request.source_registration_ref not in effective_registration_refs:
                checked_constraints.append(
                    CompiledConstraintCheck(
                        code="source_registration",
                        outcome="failed",
                        message="The requested source registration is not linked to the asset or its batch lineage.",
                        details={
                            "asset_ref": asset_ref,
                            "source_registration_ref": request.source_registration_ref,
                            "known_registration_refs": sorted(effective_registration_refs),
                        },
                    )
                )
                deny_reasons.append("missing_source_registration")
            elif request.source_registration_ref not in effective_approved_registration_refs:
                checked_constraints.append(
                    CompiledConstraintCheck(
                        code="source_registration",
                        outcome="failed",
                        message="The requested source registration is linked but not approved.",
                        details={
                            "asset_ref": asset_ref,
                            "source_registration_ref": request.source_registration_ref,
                            "approved_registration_refs": sorted(effective_approved_registration_refs),
                        },
                    )
                )
                deny_reasons.append("unapproved_source_registration")
            elif (
                request.registration_decision_ref is not None
                and request.registration_decision_ref not in effective_registration_decision_refs
            ):
                checked_constraints.append(
                    CompiledConstraintCheck(
                        code="registration_decision",
                        outcome="failed",
                        message="The requested registration decision does not match the approved registration lineage.",
                        details={
                            "asset_ref": asset_ref,
                            "registration_decision_ref": request.registration_decision_ref,
                            "known_registration_decision_refs": sorted(effective_registration_decision_refs),
                        },
                    )
                )
                deny_reasons.append("mismatched_registration_decision")
            else:
                checked_constraints.append(
                    CompiledConstraintCheck(
                        code="source_registration",
                        outcome="passed",
                        message="The asset lineage includes an approved source registration for this transition.",
                        details={
                            "asset_ref": asset_ref,
                            "source_registration_ref": request.source_registration_ref,
                            "registration_decision_ref": request.registration_decision_ref,
                        },
                    )
                )

        if deny_reasons:
            disposition = AuthzDecisionDisposition.DENY
            reason = deny_reasons[0]
        elif trust_gaps:
            disposition = AuthzDecisionDisposition.QUARANTINE if requirements.allow_quarantine else AuthzDecisionDisposition.DENY
            reason = "trust_gap_quarantine" if disposition == AuthzDecisionDisposition.QUARANTINE else "trust_gap_denied"
        else:
            disposition = AuthzDecisionDisposition.ALLOW
            reason = permission_match.reason

        receipt = self._mint_receipt(
            disposition=disposition,
            reason=reason,
            request=request,
            permission_match=permission_match,
            asset_state=asset_state,
            trust_gaps=trust_gaps,
        )
        return CompiledTransitionEvaluation(
            disposition=disposition,
            reason=reason,
            permission_match=permission_match,
            receipt=receipt,
            asset_ref=asset_ref,
            resource_ref=target_ref,
            current_custodian=asset_state.current_custodian if asset_state else None,
            trust_gaps=tuple(trust_gaps),
            checked_constraints=tuple(checked_constraints),
            restricted_token_recommended=disposition == AuthzDecisionDisposition.QUARANTINE,
        )

    def _resolve_transition_permission_match(
        self,
        request: AuthzTransitionRequest,
    ) -> tuple[Optional[str], CompiledPermissionMatch]:
        candidates: List[str] = []
        if request.resource_ref:
            candidates.append(request.resource_ref)
        if request.asset_ref:
            candidates.append(request.asset_ref)
        effective_asset_ref = request.asset_ref
        if effective_asset_ref is None and request.resource_ref:
            effective_asset_ref = self.resource_to_asset.get(request.resource_ref)
        if effective_asset_ref is not None:
            candidates.extend(sorted(self.resource_aliases_by_asset.get(effective_asset_ref, set())))
        if not candidates:
            return None, CompiledPermissionMatch(allowed=False, reason="no_permission_target")

        deduped_candidates: List[str] = []
        for candidate in candidates:
            if candidate not in deduped_candidates:
                deduped_candidates.append(candidate)

        best_match = CompiledPermissionMatch(allowed=False, reason="no_matching_permission")
        best_target: Optional[str] = deduped_candidates[0]
        for candidate in deduped_candidates:
            match = self.can_access(
                principal_ref=request.principal_ref,
                operation=request.operation,
                resource_ref=candidate,
                zone_ref=request.zone_ref,
                network_ref=request.network_ref,
                workflow_stage_ref=request.workflow_stage_ref,
                resource_state_hash=request.resource_state_hash,
                at=request.at,
                break_glass=request.break_glass,
            )
            if match.allowed:
                return candidate, match
            if best_match.reason == "no_matching_permission" and match.reason != "no_matching_permission":
                best_match = match
                best_target = candidate
        return best_target, best_match

    def _collect_transition_requirements(
        self,
        request: AuthzTransitionRequest,
        permission_match: CompiledPermissionMatch,
    ) -> "_TransitionRequirements":
        requirements = _TransitionRequirements(
            require_current_custodian=request.require_current_custodian,
            require_transferable_state=request.require_transferable_state,
            max_telemetry_age_seconds=request.max_telemetry_age_seconds,
            max_inspection_age_seconds=request.max_inspection_age_seconds,
            require_attestation=request.require_attestation,
            require_seal=request.require_seal,
            require_approved_source_registration=request.require_approved_source_registration,
            allow_quarantine=request.allow_quarantine,
            custody_points={request.custody_point_ref} if request.custody_point_ref else set(),
        )
        for permission in (*permission_match.matched_permissions, *permission_match.break_glass_permissions):
            if permission.required_current_custodian:
                requirements.require_current_custodian = True
            if permission.required_transferable_state:
                requirements.require_transferable_state = True
            if permission.max_telemetry_age_seconds is not None:
                requirements.max_telemetry_age_seconds = _min_optional_int(
                    requirements.max_telemetry_age_seconds,
                    permission.max_telemetry_age_seconds,
                )
            if permission.max_inspection_age_seconds is not None:
                requirements.max_inspection_age_seconds = _min_optional_int(
                    requirements.max_inspection_age_seconds,
                    permission.max_inspection_age_seconds,
                )
            if permission.require_attestation:
                requirements.require_attestation = True
            if permission.require_seal:
                requirements.require_seal = True
            if permission.require_approved_source_registration:
                requirements.require_approved_source_registration = True
            requirements.allow_quarantine = requirements.allow_quarantine and permission.allow_quarantine
            requirements.custody_points.update(permission.custody_points)
        return requirements

    def _resolve_registration_scope(
        self,
        asset_state: Optional[CompiledAssetState],
    ) -> tuple[Set[str], Set[str], Set[str]]:
        registration_refs: Set[str] = set()
        approved_registration_refs: Set[str] = set()
        registration_decision_refs: Set[str] = set()

        def _merge_state(state: Optional[CompiledAssetState]) -> None:
            if state is None:
                return
            registration_refs.update(state.registration_refs)
            approved_registration_refs.update(state.approved_registration_refs)
            registration_decision_refs.update(state.registration_decision_refs)
            for registration_ref in state.registration_refs:
                for decision_ref in self.registration_decisions_by_registration.get(registration_ref, set()):
                    registration_decision_refs.add(decision_ref)
                    decision_node = self.nodes_by_ref.get(decision_ref)
                    if decision_node is not None and str(decision_node.attributes.get("decision") or "").strip().lower() == "approved":
                        approved_registration_refs.add(registration_ref)

        _merge_state(asset_state)
        batch_ref = asset_state.batch_ref if asset_state is not None else None
        if batch_ref is not None:
            _merge_state(self.asset_states.get(batch_ref))

        return registration_refs, approved_registration_refs, registration_decision_refs

    def _mint_receipt(
        self,
        *,
        disposition: AuthzDecisionDisposition,
        reason: str,
        request: AuthzTransitionRequest,
        permission_match: CompiledPermissionMatch,
        asset_state: Optional[CompiledAssetState],
        trust_gaps: Iterable[CompiledTrustGap] = (),
    ) -> GovernedDecisionReceipt:
        generated_at = (request.at.astimezone(timezone.utc) if request.at and request.at.tzinfo else request.at or _utcnow()).isoformat()
        trust_gap_codes = tuple(sorted(gap.code for gap in trust_gaps))
        provenance_sources = tuple(
            sorted(
                {
                    item.provenance_source
                    for item in (*permission_match.matched_permissions, *permission_match.deny_permissions, *permission_match.break_glass_permissions)
                    if item.provenance_source
                }
            )
        )
        custody_proof: Tuple[str, ...] = ()
        evidence_refs: Tuple[str, ...] = ()
        advisory: Dict[str, Any] = {}
        if asset_state is not None:
            custody_refs = []
            if asset_state.current_custodian:
                custody_refs.append(f"current_custodian:{asset_state.current_custodian}")
            for prior in sorted(asset_state.previous_custodians):
                custody_refs.append(f"previous_custodian:{prior}")
            if asset_state.batch_ref:
                custody_refs.append(f"batch:{asset_state.batch_ref}")
            if asset_state.twin_ref:
                custody_refs.append(f"twin:{asset_state.twin_ref}")
            custody_proof = tuple(custody_refs)
            registration_refs, _, registration_decision_refs = self._resolve_registration_scope(asset_state)
            evidence_refs = tuple(
                sorted(
                    asset_state.evidence_refs
                    | asset_state.attestation_refs
                    | asset_state.seal_refs
                    | registration_refs
                    | registration_decision_refs
                )
            )
            if asset_state.evidence_quality_score is not None:
                advisory["evidence_quality_score"] = asset_state.evidence_quality_score

        payload = {
            "snapshot_ref": self.snapshot_ref,
            "snapshot_id": self.snapshot_id,
            "snapshot_version": self.snapshot_version,
            "snapshot_hash": self.snapshot_hash,
            "disposition": disposition.value,
            "principal_ref": request.principal_ref,
            "operation": request.operation,
            "resource_ref": request.resource_ref,
            "asset_ref": request.asset_ref or (asset_state.asset_ref if asset_state else None),
            "reason": reason,
            "trust_gap_codes": trust_gap_codes,
            "provenance_sources": provenance_sources,
            "custody_proof": custody_proof,
            "evidence_refs": evidence_refs,
        }
        decision_hash = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        return GovernedDecisionReceipt(
            decision_hash=decision_hash,
            disposition=disposition,
            snapshot_ref=self.snapshot_ref,
            snapshot_id=self.snapshot_id,
            snapshot_version=self.snapshot_version,
            snapshot_hash=self.snapshot_hash,
            principal_ref=request.principal_ref,
            operation=request.operation,
            asset_ref=request.asset_ref or (asset_state.asset_ref if asset_state else None),
            resource_ref=request.resource_ref,
            twin_ref=asset_state.twin_ref if asset_state else None,
            reason=reason,
            generated_at=generated_at,
            custody_proof=custody_proof,
            evidence_refs=evidence_refs,
            trust_gap_codes=trust_gap_codes,
            provenance_sources=provenance_sources,
            advisory=advisory,
        )


@dataclass
class _TransitionRequirements:
    require_current_custodian: bool = False
    require_transferable_state: bool = False
    max_telemetry_age_seconds: Optional[int] = None
    max_inspection_age_seconds: Optional[int] = None
    require_attestation: bool = False
    require_seal: bool = False
    require_approved_source_registration: bool = False
    allow_quarantine: bool = True
    custody_points: Set[str] = field(default_factory=set)


def _min_optional_int(current: Optional[int], candidate: Optional[int]) -> Optional[int]:
    if candidate is None:
        return current
    if current is None:
        return candidate
    return min(current, candidate)


class AuthzGraphCompiler:
    """
    Compiles an authorization graph snapshot into read-only indexes suitable for
    synchronous PDP evaluation and asset-centric transition checks.
    """

    def compile(self, snapshot: AuthzGraphSnapshot) -> CompiledAuthzIndex:
        index = CompiledAuthzIndex(
            snapshot_ref=snapshot.snapshot_ref,
            snapshot_id=snapshot.snapshot_id,
            snapshot_version=snapshot.snapshot_version,
            compiled_at=_utcnow().isoformat(),
        )
        for node in snapshot.nodes:
            self._consume_node(index, node)
        for edge in snapshot.edges:
            self._consume_edge(index, edge)
        index.decision_graph_snapshot = _build_decision_graph_snapshot(index)
        return index

    def _consume_node(self, index: CompiledAuthzIndex, node: AuthzNode) -> None:
        index.nodes_by_ref[node.ref] = node

        if node.kind == NodeKind.ASSET:
            state = _ensure_asset_state(index, node.ref)
            state.state = _normalize_optional_ref(node.attributes.get("state")) or state.state
            node_transferable = _as_bool(node.attributes.get("transferable"))
            node_restricted = _as_bool(node.attributes.get("restricted"))
            if node_transferable is not None:
                state.transferable = node_transferable
            if node_restricted is not None:
                state.restricted = node_restricted
            twin_id = _normalize_optional_ref(node.attributes.get("batch_twin_id") or node.attributes.get("twin_id"))
            if twin_id is not None:
                state.twin_ref = twin_id if twin_id.startswith("twin:") else f"twin:{twin_id}"
            lot_id = _normalize_optional_ref(node.attributes.get("lot_id"))
            if lot_id is not None:
                state.batch_ref = lot_id if lot_id.startswith("asset_batch:") else f"asset_batch:{lot_id}"
            product_id = _normalize_optional_ref(node.attributes.get("product_id"))
            if product_id is not None:
                state.product_ref = product_id if product_id.startswith("product:") else f"product:{product_id}"
            return

        if node.kind == NodeKind.RESOURCE:
            asset_ref = _normalize_optional_ref(node.attributes.get("asset_ref"))
            asset_id = _normalize_optional_ref(node.attributes.get("asset_id"))
            if asset_ref is None and asset_id is not None:
                asset_ref = asset_id if asset_id.startswith("asset:") else f"asset:{asset_id}"
            if asset_ref is not None:
                index.resource_to_asset[node.ref] = asset_ref
                index.resource_aliases_by_asset.setdefault(asset_ref, set()).add(node.ref)
                _ensure_asset_state(index, asset_ref)
            return

        if node.kind == NodeKind.ASSET_BATCH:
            _ensure_asset_state(index, node.ref)

    def _consume_edge(self, index: CompiledAuthzIndex, edge: AuthzEdge) -> None:
        if edge.kind == EdgeKind.HAS_ROLE:
            index.role_memberships.setdefault(edge.src, set()).add(edge.dst)
            _link_authority(index, edge.src, edge.dst)
            return
        if edge.kind == EdgeKind.DELEGATED_TO:
            index.delegations.setdefault(edge.src, set()).add(edge.dst)
            _link_authority(index, edge.src, edge.dst)
            return
        if edge.kind in {
            EdgeKind.MEMBER_OF,
            EdgeKind.DELEGATED_BY,
            EdgeKind.APPROVED_FOR,
            EdgeKind.OPERATES,
            EdgeKind.CONTROLS,
            EdgeKind.BOUND_TO_DEVICE,
            EdgeKind.CERTIFIED_FOR,
        }:
            _link_authority(index, edge.src, edge.dst)
            return
        if edge.kind == EdgeKind.LOCATED_IN:
            index.resource_zones.setdefault(edge.src, set()).add(edge.dst)
            if edge.src.startswith("asset:") or edge.src.startswith("asset_batch:"):
                state = _ensure_asset_state(index, edge.src)
                dst_node = index.nodes_by_ref.get(edge.dst)
                if dst_node and dst_node.kind == NodeKind.CUSTODY_POINT:
                    state.custody_points.add(edge.dst)
                else:
                    state.zones.add(edge.dst)
            return
        if edge.kind == EdgeKind.PART_OF:
            if edge.src.startswith("asset:") or edge.src.startswith("asset_batch:"):
                state = _ensure_asset_state(index, edge.src)
                dst_node = index.nodes_by_ref.get(edge.dst)
                if dst_node and dst_node.kind == NodeKind.PRODUCT:
                    state.product_ref = edge.dst
            return
        if edge.kind == EdgeKind.HELD_BY:
            state = _ensure_asset_state(index, edge.src)
            state.current_custodian = edge.dst
            edge_transferable = _as_bool(edge.attributes.get("transferable"))
            edge_restricted = _as_bool(edge.attributes.get("restricted"))
            edge_state = _normalize_optional_ref(edge.attributes.get("state"))
            if edge_transferable is not None:
                state.transferable = edge_transferable
            if edge_restricted is not None:
                state.restricted = edge_restricted
            if edge_state is not None:
                state.state = edge_state
            return
        if edge.kind == EdgeKind.TRANSFERRED_FROM:
            _ensure_asset_state(index, edge.src).previous_custodians.add(edge.dst)
            return
        if edge.kind == EdgeKind.ATTESTED_BY:
            state = _ensure_asset_state(index, edge.src)
            state.attestation_refs.add(edge.dst)
            state.evidence_refs.add(edge.dst)
            attestation_time = _candidate_timestamp(edge.valid_to, edge.valid_from)
            if attestation_time is None:
                node = index.nodes_by_ref.get(edge.dst)
                if node is not None:
                    attestation_time = _candidate_timestamp(node.valid_to, node.valid_from)
            state.last_inspection_at = _prefer_latest(state.last_inspection_at, attestation_time)
            return
        if edge.kind == EdgeKind.OBSERVED_IN:
            state = _ensure_asset_state(index, edge.src)
            state.evidence_refs.add(edge.dst)
            observed_at = _candidate_timestamp(edge.valid_to, edge.valid_from)
            if observed_at is None:
                node = index.nodes_by_ref.get(edge.dst)
                if node is not None:
                    observed_at = _candidate_timestamp(node.valid_to, node.valid_from)
                    state.evidence_quality_score = _merge_quality_score(
                        state.evidence_quality_score,
                        _as_float(node.attributes.get("quality_score")),
                    )
            state.last_telemetry_at = _prefer_latest(state.last_telemetry_at, observed_at)
            state.evidence_quality_score = _merge_quality_score(
                state.evidence_quality_score,
                _as_float(edge.attributes.get("quality_score")),
            )
            return
        if edge.kind == EdgeKind.SEALED_WITH:
            state = _ensure_asset_state(index, edge.src)
            state.seal_refs.add(edge.dst)
            state.evidence_refs.add(edge.dst)
            return
        if edge.kind == EdgeKind.BACKED_BY and (edge.src.startswith("asset:") or edge.src.startswith("asset_batch:")):
            state = _ensure_asset_state(index, edge.src)
            dst_node = index.nodes_by_ref.get(edge.dst)
            if dst_node is not None:
                if dst_node.kind == NodeKind.TWIN:
                    state.twin_ref = edge.dst
                elif dst_node.kind == NodeKind.ASSET_BATCH:
                    state.batch_ref = edge.dst
                elif dst_node.kind == NodeKind.RESOURCE and edge.src.startswith("asset:"):
                    index.resource_to_asset[edge.dst] = edge.src
                    index.resource_aliases_by_asset.setdefault(edge.src, set()).add(edge.dst)
                elif dst_node.kind == NodeKind.PRODUCT:
                    state.product_ref = edge.dst
                elif dst_node.kind in {
                    NodeKind.REGISTRATION,
                    NodeKind.TRACKING_EVENT,
                    NodeKind.DIGITAL_PASSPORT_FRAGMENT,
                    NodeKind.ATTESTATION,
                    NodeKind.INSPECTION,
                    NodeKind.RECEIPT,
                }:
                    state.evidence_refs.add(edge.dst)
                    if dst_node.kind == NodeKind.REGISTRATION:
                        state.registration_refs.add(edge.dst)
                        status = str(dst_node.attributes.get("status") or "").strip().lower()
                        if status == "approved":
                            state.approved_registration_refs.add(edge.dst)
                elif dst_node.kind == NodeKind.REGISTRATION_DECISION:
                    state.registration_decision_refs.add(edge.dst)
                    state.evidence_refs.add(edge.dst)
            return
        if edge.kind == EdgeKind.BACKED_BY and edge.src.startswith("registration:"):
            dst_node = index.nodes_by_ref.get(edge.dst)
            if dst_node is not None and dst_node.kind == NodeKind.REGISTRATION_DECISION:
                index.registration_decisions_by_registration.setdefault(edge.src, set()).add(edge.dst)
            return
        if edge.kind != EdgeKind.CAN or not edge.operation:
            return

        zones = frozenset(str(value) for value in edge.constraints.get("zones", []) if str(value).strip())
        networks = frozenset(str(value) for value in edge.constraints.get("networks", []) if str(value).strip())
        custody_points = frozenset(
            str(value) for value in edge.constraints.get("custody_points", []) if str(value).strip()
        )
        workflow_stages = frozenset(
            str(value) for value in edge.constraints.get("workflow_stages", []) if str(value).strip()
        )
        permission = CompiledPermission(
            subject_ref=edge.src,
            resource_ref=edge.dst,
            operation=edge.operation,
            effect=edge.effect,
            zones=zones,
            networks=networks,
            custody_points=custody_points,
            workflow_stages=workflow_stages,
            resource_state_hash=_normalize_optional_ref(edge.constraints.get("resource_state_hash")),
            requires_break_glass=bool(edge.constraints.get("requires_break_glass")),
            bypass_deny=bool(edge.constraints.get("bypass_deny")),
            required_current_custodian=bool(edge.constraints.get("required_current_custodian")),
            required_transferable_state=bool(edge.constraints.get("required_transferable_state")),
            max_telemetry_age_seconds=_coerce_optional_int(edge.constraints.get("max_telemetry_age_seconds")),
            max_inspection_age_seconds=_coerce_optional_int(edge.constraints.get("max_inspection_age_seconds")),
            require_attestation=bool(edge.constraints.get("require_attestation")),
            require_seal=bool(edge.constraints.get("require_seal")),
            require_approved_source_registration=bool(edge.constraints.get("require_approved_source_registration")),
            allow_quarantine=bool(edge.constraints.get("allow_quarantine", True)),
            valid_from=_parse_iso8601(edge.valid_from),
            valid_to=_parse_iso8601(edge.valid_to),
            provenance_source=edge.provenance.source_ref if edge.provenance else None,
        )
        index.permissions_by_subject.setdefault(edge.src, []).append(permission)


def _coerce_optional_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ensure_asset_state(index: CompiledAuthzIndex, asset_ref: str) -> CompiledAssetState:
    state = index.asset_states.get(asset_ref)
    if state is None:
        state = CompiledAssetState(asset_ref=asset_ref)
        index.asset_states[asset_ref] = state
    return state


def _link_authority(index: CompiledAuthzIndex, src: str, dst: str) -> None:
    index.authority_links.setdefault(src, set()).add(dst)


def _sorted_tuple(values: Iterable[str]) -> Tuple[str, ...]:
    return tuple(sorted({str(value).strip() for value in values if str(value).strip()}))


def _entity_refs_by_kind(index: CompiledAuthzIndex) -> Dict[str, Tuple[str, ...]]:
    refs_by_kind: Dict[str, Set[str]] = {
        "principals": set(),
        "devices": set(),
        "facilities": set(),
        "zones": set(),
        "custody_points": set(),
        "assets": set(),
        "asset_batches": set(),
        "twins": set(),
        "networks": set(),
        "workflow_stages": set(),
    }
    for ref, node in index.nodes_by_ref.items():
        if node.kind == NodeKind.PRINCIPAL:
            refs_by_kind["principals"].add(ref)
        elif node.kind == NodeKind.DEVICE:
            refs_by_kind["devices"].add(ref)
        elif node.kind == NodeKind.FACILITY:
            refs_by_kind["facilities"].add(ref)
        elif node.kind == NodeKind.ZONE:
            refs_by_kind["zones"].add(ref)
        elif node.kind == NodeKind.CUSTODY_POINT:
            refs_by_kind["custody_points"].add(ref)
        elif node.kind == NodeKind.ASSET:
            refs_by_kind["assets"].add(ref)
        elif node.kind == NodeKind.ASSET_BATCH:
            refs_by_kind["asset_batches"].add(ref)
        elif node.kind == NodeKind.TWIN:
            refs_by_kind["twins"].add(ref)
        elif node.kind == NodeKind.NETWORK_SEGMENT:
            refs_by_kind["networks"].add(ref)
        elif node.kind == NodeKind.WORKFLOW_STAGE:
            refs_by_kind["workflow_stages"].add(ref)
    return {key: _sorted_tuple(value) for key, value in refs_by_kind.items()}


def _resource_index(index: CompiledAuthzIndex) -> Dict[str, Dict[str, Any]]:
    payload: Dict[str, Dict[str, Any]] = {}
    for resource_ref in sorted(set(index.resource_to_asset.keys()) | set(index.resource_zones.keys())):
        payload[resource_ref] = {
            "asset_ref": index.resource_to_asset.get(resource_ref),
            "zone_refs": sorted(index.resource_zones.get(resource_ref, set())),
        }
    return payload


def _asset_state_index(index: CompiledAuthzIndex) -> Dict[str, Dict[str, Any]]:
    payload: Dict[str, Dict[str, Any]] = {}
    for asset_ref in sorted(index.asset_states):
        state = index.asset_states[asset_ref]
        payload[asset_ref] = {
            "twin_ref": state.twin_ref,
            "batch_ref": state.batch_ref,
            "product_ref": state.product_ref,
            "state": state.state,
            "transferable": state.transferable,
            "restricted": state.restricted,
            "current_custodian": state.current_custodian,
            "previous_custodians": sorted(state.previous_custodians),
            "zone_refs": sorted(state.zones),
            "custody_point_refs": sorted(state.custody_points),
            "attestation_refs": sorted(state.attestation_refs),
            "inspection_refs": sorted(state.inspection_refs),
            "seal_refs": sorted(state.seal_refs),
            "evidence_refs": sorted(state.evidence_refs),
            "registration_refs": sorted(state.registration_refs),
            "approved_registration_refs": sorted(state.approved_registration_refs),
            "registration_decision_refs": sorted(state.registration_decision_refs),
            "last_telemetry_at": state.last_telemetry_at.isoformat() if state.last_telemetry_at is not None else None,
            "last_inspection_at": state.last_inspection_at.isoformat() if state.last_inspection_at is not None else None,
            "evidence_quality_score": state.evidence_quality_score,
        }
    return payload


def _transition_requirement_payload(permission: CompiledPermission) -> Dict[str, Any]:
    return {
        "subject_ref": permission.subject_ref,
        "resource_ref": permission.resource_ref,
        "operation": permission.operation,
        "effect": permission.effect.value,
        "zone_refs": sorted(permission.zones),
        "network_refs": sorted(permission.networks),
        "custody_point_refs": sorted(permission.custody_points),
        "workflow_stage_refs": sorted(permission.workflow_stages),
        "resource_state_hash": permission.resource_state_hash,
        "requires_break_glass": permission.requires_break_glass,
        "bypass_deny": permission.bypass_deny,
        "required_current_custodian": permission.required_current_custodian,
        "required_transferable_state": permission.required_transferable_state,
        "max_telemetry_age_seconds": permission.max_telemetry_age_seconds,
        "max_inspection_age_seconds": permission.max_inspection_age_seconds,
        "require_attestation": permission.require_attestation,
        "require_seal": permission.require_seal,
        "require_approved_source_registration": permission.require_approved_source_registration,
        "allow_quarantine": permission.allow_quarantine,
        "valid_from": permission.valid_from.isoformat() if permission.valid_from is not None else None,
        "valid_to": permission.valid_to.isoformat() if permission.valid_to is not None else None,
        "provenance_source": permission.provenance_source,
    }


def _transition_requirements(index: CompiledAuthzIndex) -> Dict[str, Tuple[Dict[str, Any], ...]]:
    payload: Dict[str, Tuple[Dict[str, Any], ...]] = {}
    for subject_ref in sorted(index.permissions_by_subject):
        entries = sorted(
            (_transition_requirement_payload(permission) for permission in index.permissions_by_subject[subject_ref]),
            key=lambda item: (
                str(item.get("resource_ref") or ""),
                str(item.get("operation") or ""),
                str(item.get("effect") or ""),
                str(item.get("provenance_source") or ""),
            ),
        )
        payload[subject_ref] = tuple(entries)
    return payload


def _restricted_transfer_ready(index: CompiledAuthzIndex) -> bool:
    for permissions in index.permissions_by_subject.values():
        for permission in permissions:
            if permission.effect != PermissionEffect.ALLOW:
                continue
            if permission.operation not in {"MOVE", "TRANSFER_CUSTODY", "MUTATE", "ACTION"}:
                continue
            if (
                permission.required_current_custodian
                or permission.required_transferable_state
                or permission.max_telemetry_age_seconds is not None
                or permission.max_inspection_age_seconds is not None
                or permission.require_attestation
                or permission.require_seal
                or permission.require_approved_source_registration
                or bool(permission.custody_points)
            ):
                return True
    return False


def _build_decision_graph_snapshot(index: CompiledAuthzIndex) -> CompiledDecisionGraphSnapshot:
    entity_refs = _entity_refs_by_kind(index)
    authority_index = {key: _sorted_tuple(values) for key, values in sorted(index.authority_links.items())}
    resource_index = _resource_index(index)
    asset_state_index = _asset_state_index(index)
    transition_requirements = _transition_requirements(index)
    policy_refs = _sorted_tuple(
        permission.provenance_source
        for permissions in index.permissions_by_subject.values()
        for permission in permissions
        if permission.provenance_source
    )
    provenance_refs = _sorted_tuple(
        list(policy_refs)
        + [
            ref
            for state in index.asset_states.values()
            for ref in (
                list(state.evidence_refs)
                + list(state.attestation_refs)
                + list(state.seal_refs)
                + list(state.registration_refs)
                + list(state.registration_decision_refs)
            )
        ]
    )
    preimage = {
        "snapshot_ref": index.snapshot_ref,
        "snapshot_id": index.snapshot_id,
        "snapshot_version": index.snapshot_version,
        "hot_path_workflow": "restricted_custody_transfer",
        "trust_gap_taxonomy": list(TRANSFER_TRUST_GAP_TAXONOMY),
        "entity_refs": {key: list(value) for key, value in entity_refs.items()},
        "authority_index": {key: list(value) for key, value in authority_index.items()},
        "resource_index": resource_index,
        "asset_state_index": asset_state_index,
        "transition_requirements": {
            key: [dict(item) for item in value]
            for key, value in transition_requirements.items()
        },
        "policy_refs": list(policy_refs),
        "provenance_refs": list(provenance_refs),
        "restricted_transfer_ready": _restricted_transfer_ready(index),
    }
    snapshot_hash = hashlib.sha256(_canonical_json(preimage).encode("utf-8")).hexdigest()
    return CompiledDecisionGraphSnapshot(
        snapshot_ref=index.snapshot_ref,
        snapshot_id=index.snapshot_id,
        snapshot_version=index.snapshot_version,
        compiled_at=index.compiled_at or _utcnow().isoformat(),
        snapshot_hash=snapshot_hash,
        entity_refs=entity_refs,
        authority_index=authority_index,
        resource_index=resource_index,
        asset_state_index=asset_state_index,
        transition_requirements=transition_requirements,
        policy_refs=policy_refs,
        provenance_refs=provenance_refs,
        restricted_transfer_ready=preimage["restricted_transfer_ready"],
    )
