from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

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


class AuthzDecisionDisposition(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    QUARANTINE = "quarantine"


@dataclass(frozen=True)
class CompiledTrustGap:
    code: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GovernedDecisionReceipt:
    decision_hash: str
    disposition: AuthzDecisionDisposition
    snapshot_ref: str
    snapshot_id: Optional[int]
    snapshot_version: Optional[str]
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
    allow_quarantine: bool = True
    break_glass: bool = False
    at: Optional[datetime] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "principal_ref", _normalize_required_ref(self.principal_ref, field_name="principal_ref"))
        object.__setattr__(self, "operation", _normalize_required_ref(self.operation, field_name="operation").upper())
        object.__setattr__(self, "resource_ref", _normalize_optional_ref(self.resource_ref))
        object.__setattr__(self, "asset_ref", _normalize_optional_ref(self.asset_ref))
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
    resource_state_hash: Optional[str] = None
    requires_break_glass: bool = False
    bypass_deny: bool = False
    required_current_custodian: bool = False
    required_transferable_state: bool = False
    max_telemetry_age_seconds: Optional[int] = None
    max_inspection_age_seconds: Optional[int] = None
    require_attestation: bool = False
    require_seal: bool = False
    allow_quarantine: bool = True
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    provenance_source: Optional[str] = None


@dataclass(frozen=True)
class CompiledPermissionMatch:
    allowed: bool
    matched_subjects: Tuple[str, ...] = ()
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
    role_memberships: Dict[str, Set[str]] = field(default_factory=dict)
    delegations: Dict[str, Set[str]] = field(default_factory=dict)
    resource_zones: Dict[str, Set[str]] = field(default_factory=dict)
    permissions_by_subject: Dict[str, List[CompiledPermission]] = field(default_factory=dict)
    resource_to_asset: Dict[str, str] = field(default_factory=dict)
    asset_states: Dict[str, CompiledAssetState] = field(default_factory=dict)
    nodes_by_ref: Dict[str, AuthzNode] = field(default_factory=dict)

    def resolve_subjects(self, principal_ref: str) -> Tuple[str, ...]:
        resolved: List[str] = []
        seen: Set[str] = set()
        stack = [principal_ref]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            resolved.append(current)
            stack.extend(sorted(self.role_memberships.get(current, set()) - seen))
            stack.extend(sorted(self.delegations.get(current, set()) - seen))
        return tuple(resolved)

    def can_access(
        self,
        *,
        principal_ref: str,
        operation: str,
        resource_ref: str,
        zone_ref: Optional[str] = None,
        network_ref: Optional[str] = None,
        resource_state_hash: Optional[str] = None,
        at: Optional[datetime] = None,
        break_glass: bool = False,
    ) -> CompiledPermissionMatch:
        effective_at = at.astimezone(timezone.utc) if at and at.tzinfo else at or _utcnow()
        subject_refs = self.resolve_subjects(principal_ref)
        allow_matches: List[CompiledPermission] = []
        deny_matches: List[CompiledPermission] = []
        break_glass_matches: List[CompiledPermission] = []
        expected_op = str(operation).strip().upper()
        effective_zone = _normalize_optional_ref(zone_ref)
        effective_network = _normalize_optional_ref(network_ref)
        effective_hash = _normalize_optional_ref(resource_state_hash)
        known_zones = self.resource_zones.get(resource_ref, set())

        for subject_ref in subject_refs:
            for permission in self.permissions_by_subject.get(subject_ref, []):
                if permission.operation != expected_op:
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
                if permission.resource_state_hash and effective_hash != permission.resource_state_hash:
                    continue
                if permission.effect == PermissionEffect.DENY:
                    deny_matches.append(permission)
                elif permission.requires_break_glass or permission.bypass_deny:
                    break_glass_matches.append(permission)
                else:
                    allow_matches.append(permission)

        if deny_matches:
            if break_glass and break_glass_matches and any(item.bypass_deny for item in break_glass_matches):
                return CompiledPermissionMatch(
                    allowed=True,
                    matched_subjects=subject_refs,
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

        if requirements.require_current_custodian:
            if asset_state is None or asset_state.current_custodian is None:
                trust_gaps.append(
                    CompiledTrustGap(
                        code="missing_current_custodian",
                        message="The asset has no compiled current custodian.",
                        details={"asset_ref": asset_ref},
                    )
                )
            else:
                if request.expected_custodian_ref and asset_state.current_custodian != request.expected_custodian_ref:
                    deny_reasons.append("expected_custodian_mismatch")
                if asset_state.current_custodian != request.principal_ref:
                    deny_reasons.append("principal_not_current_custodian")
        elif request.expected_custodian_ref:
            if asset_state is None or asset_state.current_custodian is None:
                trust_gaps.append(
                    CompiledTrustGap(
                        code="missing_current_custodian",
                        message="The asset has no compiled current custodian.",
                        details={"asset_ref": asset_ref},
                    )
                )
            elif asset_state.current_custodian != request.expected_custodian_ref:
                deny_reasons.append("expected_custodian_mismatch")

        if requirements.custody_points:
            if request.custody_point_ref is not None and request.custody_point_ref not in requirements.custody_points:
                deny_reasons.append("custody_point_mismatch")
            elif asset_state is not None and asset_state.custody_points:
                if requirements.custody_points.isdisjoint(asset_state.custody_points):
                    deny_reasons.append("asset_not_in_required_custody_point")
            elif request.custody_point_ref is None:
                trust_gaps.append(
                    CompiledTrustGap(
                        code="missing_custody_point",
                        message="The transition requires a custody point but none was provided.",
                        details={"required_custody_points": sorted(requirements.custody_points)},
                    )
                )

        if requirements.require_transferable_state:
            if asset_state is None:
                trust_gaps.append(
                    CompiledTrustGap(
                        code="missing_asset_state",
                        message="The asset has no compiled state for transfer validation.",
                        details={"asset_ref": asset_ref},
                    )
                )
            else:
                if asset_state.restricted is True:
                    deny_reasons.append("asset_restricted")
                elif asset_state.transferable is False:
                    deny_reasons.append("asset_not_transferable")
                elif asset_state.transferable is None and asset_state.state is None:
                    trust_gaps.append(
                        CompiledTrustGap(
                            code="unknown_transfer_state",
                            message="The asset does not expose a transferability state.",
                            details={"asset_ref": asset_ref},
                        )
                    )

        effective_at = request.at.astimezone(timezone.utc) if request.at and request.at.tzinfo else request.at or _utcnow()
        if requirements.max_telemetry_age_seconds is not None:
            if asset_state is None or asset_state.last_telemetry_at is None:
                trust_gaps.append(
                    CompiledTrustGap(
                        code="missing_telemetry",
                        message="The asset is missing compiled telemetry coverage.",
                        details={"asset_ref": asset_ref},
                    )
                )
            elif effective_at - asset_state.last_telemetry_at > timedelta(seconds=requirements.max_telemetry_age_seconds):
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

        if requirements.max_inspection_age_seconds is not None:
            if asset_state is None or asset_state.last_inspection_at is None:
                trust_gaps.append(
                    CompiledTrustGap(
                        code="missing_inspection",
                        message="The asset is missing a compiled inspection or attestation timestamp.",
                        details={"asset_ref": asset_ref},
                    )
                )
            elif effective_at - asset_state.last_inspection_at > timedelta(seconds=requirements.max_inspection_age_seconds):
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

        if requirements.require_attestation and (asset_state is None or not asset_state.attestation_refs):
            trust_gaps.append(
                CompiledTrustGap(
                    code="missing_attestation",
                    message="The asset has no compiled attestation references.",
                    details={"asset_ref": asset_ref},
                )
            )

        if requirements.require_seal and (asset_state is None or not asset_state.seal_refs):
            trust_gaps.append(
                CompiledTrustGap(
                    code="missing_seal",
                    message="The asset has no compiled seal binding.",
                    details={"asset_ref": asset_ref},
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
            requirements.allow_quarantine = requirements.allow_quarantine and permission.allow_quarantine
            requirements.custody_points.update(permission.custody_points)
        return requirements

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
            evidence_refs = tuple(sorted(asset_state.evidence_refs | asset_state.attestation_refs | asset_state.seal_refs))
            if asset_state.evidence_quality_score is not None:
                advisory["evidence_quality_score"] = asset_state.evidence_quality_score

        payload = {
            "snapshot_ref": self.snapshot_ref,
            "snapshot_id": self.snapshot_id,
            "snapshot_version": self.snapshot_version,
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
        )
        for node in snapshot.nodes:
            self._consume_node(index, node)
        for edge in snapshot.edges:
            self._consume_edge(index, edge)
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
            return

        if node.kind == NodeKind.RESOURCE:
            asset_ref = _normalize_optional_ref(node.attributes.get("asset_ref"))
            asset_id = _normalize_optional_ref(node.attributes.get("asset_id"))
            if asset_ref is None and asset_id is not None:
                asset_ref = asset_id if asset_id.startswith("asset:") else f"asset:{asset_id}"
            if asset_ref is not None:
                index.resource_to_asset[node.ref] = asset_ref
                _ensure_asset_state(index, asset_ref)
            return

        if node.kind == NodeKind.ASSET_BATCH:
            _ensure_asset_state(index, node.ref)

    def _consume_edge(self, index: CompiledAuthzIndex, edge: AuthzEdge) -> None:
        if edge.kind == EdgeKind.HAS_ROLE:
            index.role_memberships.setdefault(edge.src, set()).add(edge.dst)
            return
        if edge.kind == EdgeKind.DELEGATED_TO:
            index.delegations.setdefault(edge.src, set()).add(edge.dst)
            return
        if edge.kind == EdgeKind.LOCATED_IN:
            index.resource_zones.setdefault(edge.src, set()).add(edge.dst)
            if edge.src.startswith("asset:"):
                state = _ensure_asset_state(index, edge.src)
                dst_node = index.nodes_by_ref.get(edge.dst)
                if dst_node and dst_node.kind == NodeKind.CUSTODY_POINT:
                    state.custody_points.add(edge.dst)
                else:
                    state.zones.add(edge.dst)
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
        if edge.kind == EdgeKind.BACKED_BY and edge.src.startswith("asset:"):
            state = _ensure_asset_state(index, edge.src)
            dst_node = index.nodes_by_ref.get(edge.dst)
            if dst_node is not None:
                if dst_node.kind == NodeKind.TWIN:
                    state.twin_ref = edge.dst
                elif dst_node.kind == NodeKind.ASSET_BATCH:
                    state.batch_ref = edge.dst
                elif dst_node.kind in {
                    NodeKind.REGISTRATION,
                    NodeKind.TRACKING_EVENT,
                    NodeKind.DIGITAL_PASSPORT_FRAGMENT,
                    NodeKind.ATTESTATION,
                    NodeKind.INSPECTION,
                    NodeKind.RECEIPT,
                }:
                    state.evidence_refs.add(edge.dst)
            return
        if edge.kind != EdgeKind.CAN or not edge.operation:
            return

        zones = frozenset(str(value) for value in edge.constraints.get("zones", []) if str(value).strip())
        networks = frozenset(str(value) for value in edge.constraints.get("networks", []) if str(value).strip())
        custody_points = frozenset(
            str(value) for value in edge.constraints.get("custody_points", []) if str(value).strip()
        )
        permission = CompiledPermission(
            subject_ref=edge.src,
            resource_ref=edge.dst,
            operation=edge.operation,
            effect=edge.effect,
            zones=zones,
            networks=networks,
            custody_points=custody_points,
            resource_state_hash=_normalize_optional_ref(edge.constraints.get("resource_state_hash")),
            requires_break_glass=bool(edge.constraints.get("requires_break_glass")),
            bypass_deny=bool(edge.constraints.get("bypass_deny")),
            required_current_custodian=bool(edge.constraints.get("required_current_custodian")),
            required_transferable_state=bool(edge.constraints.get("required_transferable_state")),
            max_telemetry_age_seconds=_coerce_optional_int(edge.constraints.get("max_telemetry_age_seconds")),
            max_inspection_age_seconds=_coerce_optional_int(edge.constraints.get("max_inspection_age_seconds")),
            require_attestation=bool(edge.constraints.get("require_attestation")),
            require_seal=bool(edge.constraints.get("require_seal")),
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
