from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional

import ray  # pyright: ignore[reportMissingImports]

from .compiler import (
    AuthzDecisionDisposition,
    AuthzTransitionRequest,
    CompiledAuthzIndex,
    CompiledPermission,
    CompiledPermissionMatch,
    CompiledTrustGap,
    CompiledTransitionEvaluation,
    GovernedDecisionReceipt,
)
from .ontology import PermissionEffect
from .projector import AuthzGraphProjector
from .service import AuthzGraphProjectionService

DEFAULT_AUTHZ_GRAPH_CACHE_ACTOR_NAME = "seedcore_authz_graph_cache"


def _parse_optional_datetime(value: Any) -> Optional[datetime]:
    if value is None or isinstance(value, datetime):
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _serialize_permission_match(match: CompiledPermissionMatch) -> Dict[str, Any]:
    return {
        "allowed": match.allowed,
        "matched_subjects": list(match.matched_subjects),
        "matched_permissions_count": len(match.matched_permissions),
        "deny_permissions_count": len(match.deny_permissions),
        "break_glass_permissions_count": len(match.break_glass_permissions),
        "break_glass_required": match.break_glass_required,
        "break_glass_used": match.break_glass_used,
        "reason": match.reason,
    }


def _serialize_transition_evaluation(evaluation: CompiledTransitionEvaluation) -> Dict[str, Any]:
    return {
        "disposition": evaluation.disposition.value,
        "reason": evaluation.reason,
        "allowed": evaluation.allowed,
        "quarantined": evaluation.quarantined,
        "asset_ref": evaluation.asset_ref,
        "resource_ref": evaluation.resource_ref,
        "current_custodian": evaluation.current_custodian,
        "restricted_token_recommended": evaluation.restricted_token_recommended,
        "trust_gap_codes": [gap.code for gap in evaluation.trust_gaps],
        "permission_match": _serialize_permission_match(evaluation.permission_match),
        "receipt": {
            "decision_hash": evaluation.receipt.decision_hash,
            "disposition": evaluation.receipt.disposition.value,
            "snapshot_ref": evaluation.receipt.snapshot_ref,
            "snapshot_id": evaluation.receipt.snapshot_id,
            "snapshot_version": evaluation.receipt.snapshot_version,
            "principal_ref": evaluation.receipt.principal_ref,
            "operation": evaluation.receipt.operation,
            "asset_ref": evaluation.receipt.asset_ref,
            "resource_ref": evaluation.receipt.resource_ref,
            "reason": evaluation.receipt.reason,
            "generated_at": evaluation.receipt.generated_at,
            "trust_gap_codes": list(evaluation.receipt.trust_gap_codes),
            "provenance_sources": list(evaluation.receipt.provenance_sources),
        },
    }


def _index_status(index: CompiledAuthzIndex, *, source: str) -> Dict[str, Any]:
    permission_count = sum(len(items) for items in index.permissions_by_subject.values())
    return {
        "loaded": True,
        "source": source,
        "snapshot_ref": index.snapshot_ref,
        "snapshot_id": index.snapshot_id,
        "snapshot_version": index.snapshot_version,
        "subject_count": len(index.permissions_by_subject),
        "permission_count": permission_count,
        "resource_zone_count": len(index.resource_zones),
        "asset_state_count": len(index.asset_states),
        "node_count": len(index.nodes_by_ref),
    }


def _ray_namespace() -> str:
    return (os.getenv("SEEDCORE_NS") or os.getenv("RAY_NAMESPACE") or "seedcore-dev").strip() or "seedcore-dev"


def _ray_address() -> str:
    return (os.getenv("RAY_ADDRESS") or "auto").strip() or "auto"


def _authz_graph_cache_actor_name() -> str:
    return (os.getenv("SEEDCORE_AUTHZ_RAY_CACHE_ACTOR_NAME") or DEFAULT_AUTHZ_GRAPH_CACHE_ACTOR_NAME).strip() or DEFAULT_AUTHZ_GRAPH_CACHE_ACTOR_NAME


def _ensure_ray_initialized() -> bool:
    try:
        if ray.is_initialized():
            return True
        ray.init(
            address=_ray_address(),
            namespace=_ray_namespace(),
            ignore_reinit_error=True,
            log_to_driver=False,
        )
        return True
    except Exception:
        return False


def _get_or_create_authz_graph_cache_actor():
    if not _ensure_ray_initialized():
        return None
    actor_name = _authz_graph_cache_actor_name()
    namespace = _ray_namespace()
    try:
        return ray.get_actor(actor_name, namespace=namespace)
    except Exception:
        pass
    try:
        return AuthzGraphCacheActor.options(
            name=actor_name,
            lifetime="detached",
            namespace=namespace,
        ).remote()
    except Exception:
        try:
            return ray.get_actor(actor_name, namespace=namespace)
        except Exception:
            return None


def _placeholder_permissions(
    *,
    count: int,
    effect: PermissionEffect,
    operation: str,
    resource_ref: str | None,
) -> tuple[CompiledPermission, ...]:
    return tuple(
        CompiledPermission(
            subject_ref=f"ray:{effect.value}:{index}",
            resource_ref=resource_ref or "resource:unknown",
            operation=operation or "UNKNOWN",
            effect=effect,
        )
        for index in range(max(0, count))
    )


def _deserialize_permission_match(payload: Mapping[str, Any], *, operation: str, resource_ref: str | None) -> CompiledPermissionMatch:
    matched_subjects = tuple(str(item) for item in payload.get("matched_subjects", []) or [])
    matched_permissions_count = int(payload.get("matched_permissions_count") or 0)
    deny_permissions_count = int(payload.get("deny_permissions_count") or 0)
    break_glass_permissions_count = int(payload.get("break_glass_permissions_count") or 0)
    return CompiledPermissionMatch(
        allowed=bool(payload.get("allowed", False)),
        matched_subjects=matched_subjects,
        matched_permissions=_placeholder_permissions(
            count=matched_permissions_count,
            effect=PermissionEffect.ALLOW,
            operation=operation,
            resource_ref=resource_ref,
        ),
        deny_permissions=_placeholder_permissions(
            count=deny_permissions_count,
            effect=PermissionEffect.DENY,
            operation=operation,
            resource_ref=resource_ref,
        ),
        break_glass_permissions=_placeholder_permissions(
            count=break_glass_permissions_count,
            effect=PermissionEffect.ALLOW,
            operation=operation,
            resource_ref=resource_ref,
        ),
        break_glass_required=bool(payload.get("break_glass_required", False)),
        break_glass_used=bool(payload.get("break_glass_used", False)),
        reason=str(payload.get("reason") or "no_matching_permission"),
    )


def _deserialize_transition_evaluation(payload: Mapping[str, Any], *, operation: str) -> CompiledTransitionEvaluation:
    permission_payload = payload.get("permission_match") if isinstance(payload.get("permission_match"), Mapping) else {}
    receipt_payload = payload.get("receipt") if isinstance(payload.get("receipt"), Mapping) else {}
    trust_gap_codes = payload.get("trust_gap_codes") if isinstance(payload.get("trust_gap_codes"), list) else []
    trust_gaps = tuple(
        CompiledTrustGap(
            code=str(item.get("code") or code),
            message=str(item.get("message") or code),
            details=dict(item.get("details") or {}),
        )
        for code, item in [
            (
                gap,
                gap if isinstance(gap, Mapping) else {"code": gap, "message": gap, "details": {}},
            )
            for gap in trust_gap_codes
        ]
    )
    permission_match = _deserialize_permission_match(
        permission_payload,
        operation=operation,
        resource_ref=payload.get("resource_ref"),
    )
    receipt = GovernedDecisionReceipt(
        decision_hash=str(receipt_payload.get("decision_hash") or ""),
        disposition=AuthzDecisionDisposition(str(receipt_payload.get("disposition") or payload.get("disposition") or "deny")),
        snapshot_ref=str(receipt_payload.get("snapshot_ref") or ""),
        snapshot_id=receipt_payload.get("snapshot_id"),
        snapshot_version=receipt_payload.get("snapshot_version"),
        principal_ref=str(receipt_payload.get("principal_ref") or ""),
        operation=str(receipt_payload.get("operation") or operation),
        asset_ref=receipt_payload.get("asset_ref"),
        resource_ref=receipt_payload.get("resource_ref"),
        twin_ref=receipt_payload.get("twin_ref"),
        reason=str(receipt_payload.get("reason") or payload.get("reason") or ""),
        generated_at=str(receipt_payload.get("generated_at") or datetime.now(timezone.utc).isoformat()),
        custody_proof=tuple(receipt_payload.get("custody_proof") or ()),
        evidence_refs=tuple(receipt_payload.get("evidence_refs") or ()),
        trust_gap_codes=tuple(receipt_payload.get("trust_gap_codes") or ()),
        provenance_sources=tuple(receipt_payload.get("provenance_sources") or ()),
        advisory=dict(receipt_payload.get("advisory") or {}),
    )
    return CompiledTransitionEvaluation(
        disposition=AuthzDecisionDisposition(str(payload.get("disposition") or "deny")),
        reason=str(payload.get("reason") or ""),
        permission_match=permission_match,
        receipt=receipt,
        asset_ref=payload.get("asset_ref"),
        resource_ref=payload.get("resource_ref"),
        current_custodian=payload.get("current_custodian"),
        trust_gaps=trust_gaps,
        restricted_token_recommended=bool(payload.get("restricted_token_recommended", False)),
    )


def evaluate_authz_with_ray_cache(
    *,
    snapshot_id: int | None,
    snapshot_version: str | None,
    snapshot_ref: str | None,
    payload: Mapping[str, Any],
    transitions: bool,
    timeout_seconds: float = 1.0,
) -> Dict[str, Any] | None:
    actor = _get_or_create_authz_graph_cache_actor()
    if actor is None:
        return None
    try:
        status = ray.get(actor.get_status.remote(), timeout=timeout_seconds)
        loaded_snapshot_id = status.get("snapshot_id") if isinstance(status, Mapping) else None
        loaded_snapshot_version = status.get("snapshot_version") if isinstance(status, Mapping) else None
        if loaded_snapshot_id != snapshot_id or loaded_snapshot_version != snapshot_version:
            status = ray.get(
                actor.load_snapshot.remote(
                    snapshot_id=snapshot_id,
                    snapshot_version=snapshot_version,
                    snapshot_ref=snapshot_ref,
                ),
                timeout=timeout_seconds,
            )
        operation = str(payload.get("operation") or "")
        if transitions:
            raw = ray.get(actor.evaluate_transition.remote(payload), timeout=timeout_seconds)
            evaluation = _deserialize_transition_evaluation(raw, operation=operation)
            return {
                "source": "ray_actor",
                "status": dict(status or {}),
                "match": evaluation.permission_match,
                "transition_evaluation": evaluation,
            }
        raw = ray.get(actor.can_access.remote(payload), timeout=timeout_seconds)
        match = _deserialize_permission_match(
            raw,
            operation=operation,
            resource_ref=payload.get("resource_ref"),
        )
        return {
            "source": "ray_actor",
            "status": dict(status or {}),
            "match": match,
            "transition_evaluation": None,
        }
    except Exception:
        return None


@ray.remote(num_cpus=0.05, max_restarts=0)
class AuthzGraphCacheActor:
    """Experimental Ray-backed cache for a compiled authz graph index."""

    def __init__(self) -> None:
        self._projection_service = AuthzGraphProjectionService()
        self._projector = AuthzGraphProjector()
        self._compiled_index: CompiledAuthzIndex | None = None
        self._status: Dict[str, Any] = {"loaded": False, "source": None}

    async def load_snapshot(
        self,
        *,
        snapshot_id: int | None = None,
        snapshot_version: str | None = None,
        snapshot_ref: str | None = None,
    ) -> Dict[str, Any]:
        effective_ref = snapshot_ref or f"authz_graph@{snapshot_version or snapshot_id}"
        compiled, result = await self._projection_service.build_compiled_index(
            snapshot_ref=effective_ref,
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
        )
        self._compiled_index = compiled
        self._status = _index_status(compiled, source="snapshot")
        self._status.update(
            {
                "graph_nodes_count": result.stats.get("graph_nodes_count", 0),
                "graph_edges_count": result.stats.get("graph_edges_count", 0),
            }
        )
        return dict(self._status)

    async def load_fixture(
        self,
        *,
        snapshot_ref: str,
        snapshot_id: int | None = None,
        snapshot_version: str | None = None,
        facts: Iterable[Mapping[str, Any]] = (),
        registrations: Iterable[Mapping[str, Any]] = (),
        tracking_events: Iterable[Mapping[str, Any]] = (),
        graph_manifests: Iterable[Mapping[str, Any]] = (),
    ) -> Dict[str, Any]:
        snapshot = self._projector.project_snapshot(
            snapshot_ref=snapshot_ref,
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            facts=list(facts),
            registrations=list(registrations),
            tracking_events=list(tracking_events),
            policy_edge_manifests=list(graph_manifests),
        )
        compiled = self._projection_service.compiler.compile(snapshot)
        self._compiled_index = compiled
        self._status = _index_status(compiled, source="fixture")
        self._status.update(
            {
                "graph_nodes_count": len(snapshot.nodes),
                "graph_edges_count": len(snapshot.edges),
            }
        )
        return dict(self._status)

    def get_status(self) -> Dict[str, Any]:
        return dict(self._status)

    def can_access(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        if self._compiled_index is None:
            raise RuntimeError("No compiled authz index loaded")
        match = self._compiled_index.can_access(
            principal_ref=str(payload["principal_ref"]),
            operation=str(payload["operation"]),
            resource_ref=str(payload["resource_ref"]),
            zone_ref=payload.get("zone_ref"),
            network_ref=payload.get("network_ref"),
            resource_state_hash=payload.get("resource_state_hash"),
            at=_parse_optional_datetime(payload.get("at")),
            break_glass=bool(payload.get("break_glass", False)),
        )
        return _serialize_permission_match(match)

    def evaluate_transition(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        if self._compiled_index is None:
            raise RuntimeError("No compiled authz index loaded")
        request = AuthzTransitionRequest(
            principal_ref=str(payload["principal_ref"]),
            operation=str(payload["operation"]),
            resource_ref=payload.get("resource_ref"),
            asset_ref=payload.get("asset_ref"),
            zone_ref=payload.get("zone_ref"),
            network_ref=payload.get("network_ref"),
            custody_point_ref=payload.get("custody_point_ref"),
            resource_state_hash=payload.get("resource_state_hash"),
            expected_custodian_ref=payload.get("expected_custodian_ref"),
            require_current_custodian=bool(payload.get("require_current_custodian", False)),
            require_transferable_state=bool(payload.get("require_transferable_state", False)),
            max_telemetry_age_seconds=payload.get("max_telemetry_age_seconds"),
            max_inspection_age_seconds=payload.get("max_inspection_age_seconds"),
            require_attestation=bool(payload.get("require_attestation", False)),
            require_seal=bool(payload.get("require_seal", False)),
            allow_quarantine=bool(payload.get("allow_quarantine", True)),
            break_glass=bool(payload.get("break_glass", False)),
            at=_parse_optional_datetime(payload.get("at")),
        )
        evaluation = self._compiled_index.evaluate_transition(request)
        return _serialize_transition_evaluation(evaluation)
