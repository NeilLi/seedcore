from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .ontology import AuthzEdge, AuthzGraphSnapshot, EdgeKind, PermissionEffect


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


@dataclass(frozen=True)
class CompiledPermission:
    subject_ref: str
    resource_ref: str
    operation: str
    effect: PermissionEffect
    zones: frozenset[str] = frozenset()
    networks: frozenset[str] = frozenset()
    resource_state_hash: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    provenance_source: Optional[str] = None


@dataclass(frozen=True)
class CompiledPermissionMatch:
    allowed: bool
    matched_subjects: Tuple[str, ...] = ()
    matched_permissions: Tuple[CompiledPermission, ...] = ()
    deny_permissions: Tuple[CompiledPermission, ...] = ()
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
    ) -> CompiledPermissionMatch:
        effective_at = at.astimezone(timezone.utc) if at and at.tzinfo else at or datetime.now(timezone.utc)
        subject_refs = self.resolve_subjects(principal_ref)
        allow_matches: List[CompiledPermission] = []
        deny_matches: List[CompiledPermission] = []
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
                else:
                    allow_matches.append(permission)

        if deny_matches:
            return CompiledPermissionMatch(
                allowed=False,
                matched_subjects=subject_refs,
                matched_permissions=tuple(allow_matches),
                deny_permissions=tuple(deny_matches),
                reason="explicit_deny",
            )
        if allow_matches:
            return CompiledPermissionMatch(
                allowed=True,
                matched_subjects=subject_refs,
                matched_permissions=tuple(allow_matches),
                deny_permissions=(),
                reason="matched_allow_permission",
            )
        return CompiledPermissionMatch(
            allowed=False,
            matched_subjects=subject_refs,
            matched_permissions=(),
            deny_permissions=(),
            reason="no_matching_permission",
        )


class AuthzGraphCompiler:
    """
    Compiles an authorization graph snapshot into read-only indexes suitable for
    synchronous PDP evaluation.
    """

    def compile(self, snapshot: AuthzGraphSnapshot) -> CompiledAuthzIndex:
        index = CompiledAuthzIndex(
            snapshot_ref=snapshot.snapshot_ref,
            snapshot_id=snapshot.snapshot_id,
            snapshot_version=snapshot.snapshot_version,
        )
        for edge in snapshot.edges:
            self._consume_edge(index, edge)
        return index

    def _consume_edge(self, index: CompiledAuthzIndex, edge: AuthzEdge) -> None:
        if edge.kind == EdgeKind.HAS_ROLE:
            index.role_memberships.setdefault(edge.src, set()).add(edge.dst)
            return
        if edge.kind == EdgeKind.DELEGATED_TO:
            index.delegations.setdefault(edge.src, set()).add(edge.dst)
            return
        if edge.kind == EdgeKind.LOCATED_IN:
            index.resource_zones.setdefault(edge.src, set()).add(edge.dst)
            return
        if edge.kind != EdgeKind.CAN or not edge.operation:
            return

        zones = frozenset(str(value) for value in edge.constraints.get("zones", []) if str(value).strip())
        networks = frozenset(str(value) for value in edge.constraints.get("networks", []) if str(value).strip())
        permission = CompiledPermission(
            subject_ref=edge.src,
            resource_ref=edge.dst,
            operation=edge.operation,
            effect=edge.effect,
            zones=zones,
            networks=networks,
            resource_state_hash=_normalize_optional_ref(edge.constraints.get("resource_state_hash")),
            valid_from=_parse_iso8601(edge.valid_from),
            valid_to=_parse_iso8601(edge.valid_to),
            provenance_source=edge.provenance.source_ref if edge.provenance else None,
        )
        index.permissions_by_subject.setdefault(edge.src, []).append(permission)
