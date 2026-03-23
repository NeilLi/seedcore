from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from seedcore.models.action_intent import ActionIntent
from seedcore.models.fact import Fact
from seedcore.models.source_registration import SourceRegistration, TrackingEvent

from .ontology import (
    AuthzEdge,
    AuthzGraphSnapshot,
    AuthzNode,
    EdgeKind,
    GraphProvenance,
    NodeKind,
    PermissionEffect,
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _value_from(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _principal_ref(value: str) -> str:
    value = str(value).strip()
    return value if value.startswith("principal:") else f"principal:{value}"


def _role_ref(value: str) -> str:
    value = str(value).strip()
    return value if value.startswith("role:") else f"role:{value}"


def _resource_ref(value: str) -> str:
    value = str(value).strip()
    if "://" in value or value.startswith("resource:"):
        return value
    return f"resource:{value}"


def _zone_ref(value: str) -> str:
    value = str(value).strip()
    return value if value.startswith("zone:") else f"zone:{value}"


def _network_ref(value: str) -> str:
    value = str(value).strip()
    return value if value.startswith("network:") else f"network:{value}"


def _freeze_value(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple((key, _freeze_value(val)) for key, val in sorted(value.items()))
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    return value


class _ProjectionBuffer:
    def __init__(self) -> None:
        self.nodes: Dict[str, AuthzNode] = {}
        self.edges: Dict[tuple[Any, ...], AuthzEdge] = {}

    def add_node(self, node: AuthzNode) -> None:
        self.nodes[node.ref] = node

    def add_edge(self, edge: AuthzEdge) -> None:
        key = (
            edge.kind.value,
            edge.src,
            edge.dst,
            edge.operation,
            edge.effect.value,
            edge.valid_from,
            edge.valid_to,
            _freeze_value(edge.constraints),
        )
        self.edges[key] = edge


class AuthzGraphProjector:
    """
    Deterministic projector from current SeedCore governance objects into the
    authorization graph ontology.
    """

    def project_snapshot(
        self,
        *,
        snapshot_ref: str,
        snapshot_id: Optional[int] = None,
        snapshot_version: Optional[str] = None,
        action_intents: Optional[Iterable[ActionIntent]] = None,
        facts: Optional[Iterable[Fact | Dict[str, Any]]] = None,
        registrations: Optional[Iterable[SourceRegistration | Dict[str, Any]]] = None,
        tracking_events: Optional[Iterable[TrackingEvent | Dict[str, Any]]] = None,
    ) -> AuthzGraphSnapshot:
        buffer = _ProjectionBuffer()

        for intent in action_intents or []:
            self._project_action_intent(intent, buffer, snapshot_id=snapshot_id, snapshot_version=snapshot_version)
        for fact in facts or []:
            self._project_fact(fact, buffer, snapshot_id=snapshot_id, snapshot_version=snapshot_version)
        for registration in registrations or []:
            self._project_registration(registration, buffer, snapshot_id=snapshot_id, snapshot_version=snapshot_version)
        for tracking_event in tracking_events or []:
            self._project_tracking_event(tracking_event, buffer, snapshot_id=snapshot_id, snapshot_version=snapshot_version)

        return AuthzGraphSnapshot(
            snapshot_ref=snapshot_ref,
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            generated_at=_utcnow_iso(),
            nodes=list(buffer.nodes.values()),
            edges=list(buffer.edges.values()),
        ).deduplicated()

    def _project_action_intent(
        self,
        intent: ActionIntent,
        buffer: _ProjectionBuffer,
        *,
        snapshot_id: Optional[int],
        snapshot_version: Optional[str],
    ) -> None:
        provenance = GraphProvenance(
            source_type="action_intent",
            source_ref=intent.intent_id,
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
        )
        principal_ref = _principal_ref(intent.principal.agent_id)
        role_ref = _role_ref(intent.principal.role_profile)
        resource_ref = intent.resource.resource_uri or _resource_ref(intent.resource.asset_id)

        buffer.add_node(
            AuthzNode(
                kind=NodeKind.PRINCIPAL,
                ref=principal_ref,
                display_name=intent.principal.agent_id,
                provenance=provenance,
            )
        )
        buffer.add_node(
            AuthzNode(
                kind=NodeKind.ROLE_PROFILE,
                ref=role_ref,
                display_name=intent.principal.role_profile,
                provenance=provenance,
            )
        )
        buffer.add_node(
            AuthzNode(
                kind=NodeKind.RESOURCE,
                ref=resource_ref,
                display_name=intent.resource.asset_id,
                attributes={
                    "asset_id": intent.resource.asset_id,
                    "resource_state_hash": intent.resource.resource_state_hash,
                    "provenance_hash": intent.resource.provenance_hash,
                },
                provenance=provenance,
            )
        )
        buffer.add_edge(
            AuthzEdge(
                kind=EdgeKind.HAS_ROLE,
                src=principal_ref,
                dst=role_ref,
                provenance=provenance,
                valid_from=intent.timestamp,
                valid_to=intent.valid_until,
            )
        )
        buffer.add_edge(
            AuthzEdge(
                kind=EdgeKind.REQUESTED,
                src=principal_ref,
                dst=resource_ref,
                operation=intent.action.operation.value if intent.action.operation else intent.action.type,
                attributes={
                    "intent_id": intent.intent_id,
                    "contract_version": intent.action.security_contract.version,
                    "origin_network": intent.environment.origin_network,
                },
                provenance=provenance,
                valid_from=intent.timestamp,
                valid_to=intent.valid_until,
            )
        )
        if intent.resource.target_zone:
            zone_ref = _zone_ref(intent.resource.target_zone)
            buffer.add_node(AuthzNode(kind=NodeKind.ZONE, ref=zone_ref, display_name=intent.resource.target_zone, provenance=provenance))
            buffer.add_edge(AuthzEdge(kind=EdgeKind.LOCATED_IN, src=resource_ref, dst=zone_ref, provenance=provenance))
        if intent.environment.origin_network:
            network_ref = _network_ref(intent.environment.origin_network)
            buffer.add_node(
                AuthzNode(
                    kind=NodeKind.NETWORK_SEGMENT,
                    ref=network_ref,
                    display_name=intent.environment.origin_network,
                    provenance=provenance,
                )
            )

    def _project_fact(
        self,
        fact: Fact | Dict[str, Any],
        buffer: _ProjectionBuffer,
        *,
        snapshot_id: Optional[int],
        snapshot_version: Optional[str],
    ) -> None:
        subject = _value_from(fact, "subject")
        predicate = _value_from(fact, "predicate")
        object_data = _value_from(fact, "object_data", {}) or {}
        if not subject or not predicate:
            return

        fact_id = _value_from(fact, "id", f"{subject}:{predicate}")
        provenance = GraphProvenance(
            source_type="fact",
            source_ref=str(fact_id),
            snapshot_id=snapshot_id or _value_from(fact, "snapshot_id"),
            snapshot_version=snapshot_version,
            metadata={"predicate": predicate},
        )

        fact_ref = f"fact:{fact_id}"
        buffer.add_node(
            AuthzNode(
                kind=NodeKind.FACT,
                ref=fact_ref,
                display_name=str(predicate),
                attributes={
                    "subject": subject,
                    "predicate": predicate,
                    "object_data": object_data,
                    "namespace": _value_from(fact, "namespace", "default"),
                },
                valid_from=_serialize_datetime(_value_from(fact, "valid_from")),
                valid_to=_serialize_datetime(_value_from(fact, "valid_to")),
                provenance=provenance,
            )
        )

        predicate_lower = str(predicate).strip().lower()
        if predicate_lower == "hasrole":
            principal_ref = _principal_ref(subject)
            role_value = object_data.get("role") or object_data.get("role_profile")
            if not role_value:
                return
            role_ref = _role_ref(role_value)
            buffer.add_node(AuthzNode(kind=NodeKind.PRINCIPAL, ref=principal_ref, provenance=provenance))
            buffer.add_node(AuthzNode(kind=NodeKind.ROLE_PROFILE, ref=role_ref, provenance=provenance))
            buffer.add_edge(
                AuthzEdge(
                    kind=EdgeKind.HAS_ROLE,
                    src=principal_ref,
                    dst=role_ref,
                    provenance=provenance,
                    valid_from=_serialize_datetime(_value_from(fact, "valid_from")),
                    valid_to=_serialize_datetime(_value_from(fact, "valid_to")),
                )
            )
            return

        if predicate_lower == "delegatedto":
            principal_ref = _principal_ref(subject)
            delegate_ref = _principal_ref(object_data.get("principal") or object_data.get("delegate"))
            buffer.add_node(AuthzNode(kind=NodeKind.PRINCIPAL, ref=principal_ref, provenance=provenance))
            buffer.add_node(AuthzNode(kind=NodeKind.PRINCIPAL, ref=delegate_ref, provenance=provenance))
            buffer.add_edge(
                AuthzEdge(
                    kind=EdgeKind.DELEGATED_TO,
                    src=principal_ref,
                    dst=delegate_ref,
                    provenance=provenance,
                    valid_from=_serialize_datetime(_value_from(fact, "valid_from")),
                    valid_to=_serialize_datetime(_value_from(fact, "valid_to")),
                )
            )
            return

        if predicate_lower == "allowedoperation":
            src_ref = _normalize_permission_subject(subject)
            operation = str(object_data.get("operation") or "").strip().upper()
            resource_value = object_data.get("resource") or object_data.get("resource_uri") or object_data.get("asset_id")
            if not src_ref or not operation or not resource_value:
                return
            resource_ref = resource_value if "://" in str(resource_value) else _resource_ref(resource_value)
            buffer.add_node(AuthzNode(kind=_infer_subject_kind(src_ref), ref=src_ref, provenance=provenance))
            buffer.add_node(AuthzNode(kind=NodeKind.RESOURCE, ref=resource_ref, provenance=provenance))

            zones = [_zone_ref(value) for value in object_data.get("zones", []) if str(value).strip()]
            networks = [_network_ref(value) for value in object_data.get("networks", []) if str(value).strip()]
            for zone_ref in zones:
                buffer.add_node(AuthzNode(kind=NodeKind.ZONE, ref=zone_ref, provenance=provenance))
            for network_ref in networks:
                buffer.add_node(AuthzNode(kind=NodeKind.NETWORK_SEGMENT, ref=network_ref, provenance=provenance))

            buffer.add_edge(
                AuthzEdge(
                    kind=EdgeKind.CAN,
                    src=src_ref,
                    dst=resource_ref,
                    operation=operation,
                    effect=PermissionEffect(str(object_data.get("effect", "allow")).lower()),
                    constraints={
                        "zones": zones,
                        "networks": networks,
                        "resource_state_hash": object_data.get("resource_state_hash"),
                    },
                    provenance=provenance,
                    valid_from=_serialize_datetime(_value_from(fact, "valid_from")),
                    valid_to=_serialize_datetime(_value_from(fact, "valid_to")),
                )
            )
            return

        if predicate_lower == "locatedinzone":
            resource_ref = _resource_ref(subject)
            zone_value = object_data.get("zone") or object_data.get("target_zone")
            if not zone_value:
                return
            zone_ref = _zone_ref(zone_value)
            buffer.add_node(AuthzNode(kind=NodeKind.RESOURCE, ref=resource_ref, provenance=provenance))
            buffer.add_node(AuthzNode(kind=NodeKind.ZONE, ref=zone_ref, provenance=provenance))
            buffer.add_edge(AuthzEdge(kind=EdgeKind.LOCATED_IN, src=resource_ref, dst=zone_ref, provenance=provenance))

    def _project_registration(
        self,
        registration: SourceRegistration | Dict[str, Any],
        buffer: _ProjectionBuffer,
        *,
        snapshot_id: Optional[int],
        snapshot_version: Optional[str],
    ) -> None:
        registration_id = _value_from(registration, "id")
        lot_id = _value_from(registration, "lot_id")
        producer_id = _value_from(registration, "producer_id")
        if registration_id is None or lot_id is None or producer_id is None:
            return

        provenance = GraphProvenance(
            source_type="source_registration",
            source_ref=str(registration_id),
            snapshot_id=snapshot_id or _value_from(registration, "snapshot_id"),
            snapshot_version=snapshot_version,
            metadata={"status": _value_from(registration, "status")},
        )
        registration_ref = f"registration:{registration_id}"
        producer_ref = _principal_ref(producer_id)
        lot_ref = _resource_ref(f"lot:{lot_id}")

        buffer.add_node(AuthzNode(kind=NodeKind.REGISTRATION, ref=registration_ref, provenance=provenance))
        buffer.add_node(AuthzNode(kind=NodeKind.PRINCIPAL, ref=producer_ref, provenance=provenance))
        buffer.add_node(
            AuthzNode(
                kind=NodeKind.RESOURCE,
                ref=lot_ref,
                display_name=str(lot_id),
                attributes={"lot_id": lot_id},
                provenance=provenance,
            )
        )
        buffer.add_edge(AuthzEdge(kind=EdgeKind.RECORDED_BY, src=registration_ref, dst=producer_ref, provenance=provenance))
        buffer.add_edge(AuthzEdge(kind=EdgeKind.BACKED_BY, src=lot_ref, dst=registration_ref, provenance=provenance))

    def _project_tracking_event(
        self,
        tracking_event: TrackingEvent | Dict[str, Any],
        buffer: _ProjectionBuffer,
        *,
        snapshot_id: Optional[int],
        snapshot_version: Optional[str],
    ) -> None:
        event_id = _value_from(tracking_event, "id")
        registration_id = _value_from(tracking_event, "registration_id")
        producer_id = _value_from(tracking_event, "producer_id")
        if event_id is None:
            return
        provenance = GraphProvenance(
            source_type="tracking_event",
            source_ref=str(event_id),
            snapshot_id=snapshot_id or _value_from(tracking_event, "snapshot_id"),
            snapshot_version=snapshot_version,
        )
        event_ref = f"tracking_event:{event_id}"
        buffer.add_node(AuthzNode(kind=NodeKind.TRACKING_EVENT, ref=event_ref, provenance=provenance))
        if registration_id is not None:
            registration_ref = f"registration:{registration_id}"
            buffer.add_node(AuthzNode(kind=NodeKind.REGISTRATION, ref=registration_ref, provenance=provenance))
            buffer.add_edge(AuthzEdge(kind=EdgeKind.BACKED_BY, src=registration_ref, dst=event_ref, provenance=provenance))
        if producer_id:
            producer_ref = _principal_ref(producer_id)
            buffer.add_node(AuthzNode(kind=NodeKind.PRINCIPAL, ref=producer_ref, provenance=provenance))
            buffer.add_edge(AuthzEdge(kind=EdgeKind.RECORDED_BY, src=event_ref, dst=producer_ref, provenance=provenance))


def _serialize_datetime(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _normalize_permission_subject(subject: str) -> str:
    subject = str(subject).strip()
    if not subject:
        return ""
    if subject.startswith("role:"):
        return _role_ref(subject)
    return _principal_ref(subject)


def _infer_subject_kind(subject_ref: str) -> NodeKind:
    if subject_ref.startswith("role:"):
        return NodeKind.ROLE_PROFILE
    return NodeKind.PRINCIPAL
