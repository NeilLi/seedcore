from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from seedcore.models.action_intent import ActionIntent
from seedcore.models.fact import Fact
from seedcore.models.source_registration import RegistrationDecision, SourceRegistration, TrackingEvent

from .manifest import PolicyEdgeManifest
from .ontology import (
    AuthzEdge,
    AuthzGraphSnapshot,
    AuthzNode,
    EdgeKind,
    GraphProvenance,
    NodeKind,
    PermissionEffect,
)

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _value_from(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _principal_ref(value: str) -> str:
    value = str(value).strip()
    return value if value.startswith("principal:") else f"principal:{value}"


def _org_ref(value: str) -> str:
    value = str(value).strip()
    return value if value.startswith("org:") else f"org:{value}"


def _role_ref(value: str) -> str:
    value = str(value).strip()
    return value if value.startswith("role:") else f"role:{value}"


def _device_ref(value: str) -> str:
    value = str(value).strip()
    return value if value.startswith("device:") else f"device:{value}"


def _facility_ref(value: str) -> str:
    value = str(value).strip()
    return value if value.startswith("facility:") else f"facility:{value}"


def _certification_ref(value: str) -> str:
    value = str(value).strip()
    return value if value.startswith("certification:") else f"certification:{value}"


def _product_ref(value: str) -> str:
    value = str(value).strip()
    return value if value.startswith("product:") else f"product:{value}"


def _workflow_stage_ref(value: str) -> str:
    value = str(value).strip()
    return value if value.startswith("workflow_stage:") else f"workflow_stage:{value}"


def _registration_ref(value: str) -> str:
    value = str(value).strip()
    return value if value.startswith("registration:") else f"registration:{value}"


def _registration_decision_ref(value: str) -> str:
    value = str(value).strip()
    return value if value.startswith("registration_decision:") else f"registration_decision:{value}"


def _resource_ref(value: str) -> str:
    value = str(value).strip()
    if "://" in value or value.startswith("resource:"):
        return value
    return f"resource:{value}"


def _asset_ref(value: str) -> str:
    value = str(value).strip()
    return value if value.startswith("asset:") else f"asset:{value}"


def _asset_batch_ref(value: str) -> str:
    value = str(value).strip()
    return value if value.startswith("asset_batch:") else f"asset_batch:{value}"


def _zone_ref(value: str) -> str:
    value = str(value).strip()
    return value if value.startswith("zone:") else f"zone:{value}"


def _network_ref(value: str) -> str:
    value = str(value).strip()
    return value if value.startswith("network:") else f"network:{value}"


def _custody_point_ref(value: str) -> str:
    value = str(value).strip()
    return value if value.startswith("custody_point:") else f"custody_point:{value}"


def _attestation_ref(value: str) -> str:
    value = str(value).strip()
    return value if value.startswith("attestation:") else f"attestation:{value}"


def _inspection_ref(value: str) -> str:
    value = str(value).strip()
    return value if value.startswith("inspection:") else f"inspection:{value}"


def _sensor_observation_ref(value: str) -> str:
    value = str(value).strip()
    if value.startswith("sensor_observation:"):
        return value
    return f"sensor_observation:{value}"


def _handshake_intent_ref(value: str) -> str:
    value = str(value).strip()
    return value if value.startswith("handshake_intent:") else f"handshake_intent:{value}"


def _passport_fragment_ref(value: str) -> str:
    value = str(value).strip()
    if value.startswith("digital_passport_fragment:"):
        return value
    return f"digital_passport_fragment:{value}"


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
        self.legacy_predicates_warned: set[str] = set()

    def add_node(self, node: AuthzNode) -> None:
        existing = self.nodes.get(node.ref)
        if existing is None:
            self.nodes[node.ref] = node
            return
        if existing.kind != node.kind:
            self.nodes[node.ref] = node
            return
        merged_attributes = dict(existing.attributes)
        merged_attributes.update(node.attributes)
        self.nodes[node.ref] = existing.model_copy(
            update={
                "display_name": node.display_name or existing.display_name,
                "attributes": merged_attributes,
                "valid_from": node.valid_from or existing.valid_from,
                "valid_to": node.valid_to or existing.valid_to,
                "provenance": node.provenance or existing.provenance,
            }
        )

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
        policy_edge_manifests: Optional[Iterable[PolicyEdgeManifest | Dict[str, Any]]] = None,
        action_intents: Optional[Iterable[ActionIntent]] = None,
        facts: Optional[Iterable[Fact | Dict[str, Any]]] = None,
        registrations: Optional[Iterable[SourceRegistration | Dict[str, Any]]] = None,
        registration_decisions: Optional[Iterable[RegistrationDecision | Dict[str, Any]]] = None,
        tracking_events: Optional[Iterable[TrackingEvent | Dict[str, Any]]] = None,
    ) -> AuthzGraphSnapshot:
        buffer = _ProjectionBuffer()

        for manifest in policy_edge_manifests or []:
            self._project_policy_edge_manifest(
                manifest,
                buffer,
                snapshot_id=snapshot_id,
                snapshot_version=snapshot_version,
            )
        for intent in action_intents or []:
            self._project_action_intent(intent, buffer, snapshot_id=snapshot_id, snapshot_version=snapshot_version)
        for fact in facts or []:
            self._project_fact(fact, buffer, snapshot_id=snapshot_id, snapshot_version=snapshot_version)
        for registration in registrations or []:
            self._project_registration(registration, buffer, snapshot_id=snapshot_id, snapshot_version=snapshot_version)
        for registration_decision in registration_decisions or []:
            self._project_registration_decision(
                registration_decision,
                buffer,
                snapshot_id=snapshot_id,
                snapshot_version=snapshot_version,
            )
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

    def _project_policy_edge_manifest(
        self,
        manifest: PolicyEdgeManifest | Dict[str, Any],
        buffer: _ProjectionBuffer,
        *,
        snapshot_id: Optional[int],
        snapshot_version: Optional[str],
    ) -> None:
        resolved = manifest if isinstance(manifest, PolicyEdgeManifest) else PolicyEdgeManifest(**manifest)
        if resolved.relationship not in {"can", "can_bypass"}:
            return

        provenance = GraphProvenance(
            source_type="snapshot_rule_manifest",
            source_ref=resolved.rule_id or resolved.rule_name or resolved.source_selector,
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            metadata={
                "rule_name": resolved.rule_name,
                "relationship": resolved.relationship,
                **resolved.metadata,
            },
        )
        source_ref = _normalize_selector_ref(resolved.source_selector)
        target_ref = _normalize_selector_ref(resolved.target_selector)
        if not source_ref or not target_ref:
            return

        buffer.add_node(
            AuthzNode(
                kind=_infer_selector_kind(source_ref),
                ref=source_ref,
                provenance=provenance,
            )
        )
        buffer.add_node(
            AuthzNode(
                kind=_infer_selector_kind(target_ref),
                ref=target_ref,
                provenance=provenance,
            )
        )
        conditions = dict(resolved.conditions or {})
        zones = [_zone_ref(value) for value in conditions.get("zones", []) if str(value).strip()]
        networks = [_network_ref(value) for value in conditions.get("networks", []) if str(value).strip()]
        custody_points = [
            _custody_point_ref(value)
            for value in conditions.get("custody_points", [])
            if str(value).strip()
        ]
        workflow_stages = [
            _workflow_stage_ref(value)
            for value in conditions.get("workflow_stages", [])
            if str(value).strip()
        ]
        for zone_ref in zones:
            buffer.add_node(AuthzNode(kind=NodeKind.ZONE, ref=zone_ref, provenance=provenance))
        for network_ref in networks:
            buffer.add_node(AuthzNode(kind=NodeKind.NETWORK_SEGMENT, ref=network_ref, provenance=provenance))
        for custody_point_ref in custody_points:
            buffer.add_node(AuthzNode(kind=NodeKind.CUSTODY_POINT, ref=custody_point_ref, provenance=provenance))
        for workflow_stage_ref in workflow_stages:
            buffer.add_node(AuthzNode(kind=NodeKind.WORKFLOW_STAGE, ref=workflow_stage_ref, provenance=provenance))

        buffer.add_edge(
            AuthzEdge(
                kind=EdgeKind.CAN,
                src=source_ref,
                dst=target_ref,
                operation=resolved.operation,
                effect=resolved.effect,
                constraints={
                    "zones": zones,
                    "networks": networks,
                    "custody_points": custody_points,
                    "resource_state_hash": conditions.get("resource_state_hash"),
                    "requires_break_glass": resolved.requires_break_glass,
                    "bypass_deny": resolved.bypass_deny,
                    "required_current_custodian": bool(conditions.get("required_current_custodian")),
                    "required_transferable_state": bool(conditions.get("required_transferable_state")),
                    "max_telemetry_age_seconds": conditions.get("max_telemetry_age_seconds"),
                    "max_inspection_age_seconds": conditions.get("max_inspection_age_seconds"),
                    "require_attestation": bool(conditions.get("require_attestation")),
                    "require_seal": bool(conditions.get("require_seal")),
                    "workflow_stages": workflow_stages,
                    "require_approved_source_registration": bool(
                        conditions.get("require_approved_source_registration")
                    ),
                    "allow_quarantine": conditions.get("allow_quarantine", True),
                },
                attributes={
                    "relationship": resolved.relationship,
                    "rule_id": resolved.rule_id,
                    "rule_name": resolved.rule_name,
                    **resolved.metadata,
                },
                valid_from=_serialize_datetime(conditions.get("valid_from")),
                valid_to=_serialize_datetime(conditions.get("valid_to")),
                provenance=provenance,
            )
        )

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
        handshake_ref = _handshake_intent_ref(intent.intent_id)
        principal_ref = _principal_ref(intent.principal.agent_id)
        role_ref = _role_ref(intent.principal.role_profile)
        asset_ref = _asset_ref(intent.resource.asset_id)
        resource_ref = intent.resource.resource_uri or _resource_ref(intent.resource.asset_id)
        twin_ref = (
            f"twin:{intent.resource.batch_twin_id}"
            if intent.resource.batch_twin_id and not str(intent.resource.batch_twin_id).startswith("twin:")
            else intent.resource.batch_twin_id
        )
        batch_ref = _asset_batch_ref(intent.resource.lot_id) if intent.resource.lot_id else None
        product_ref = _product_ref(intent.resource.product_id) if intent.resource.product_id else None
        source_registration_ref = (
            _registration_ref(intent.resource.source_registration_id)
            if intent.resource.source_registration_id
            else None
        )
        registration_decision_ref = (
            _registration_decision_ref(intent.resource.registration_decision_id)
            if intent.resource.registration_decision_id
            else None
        )
        action_parameters = intent.action.parameters if isinstance(intent.action.parameters, dict) else {}
        workflow_stage_value = (
            action_parameters.get("workflow_stage")
            or action_parameters.get("stage")
            or action_parameters.get("workflow_step")
            or action_parameters.get("step")
        )
        workflow_stage_ref = _workflow_stage_ref(workflow_stage_value) if workflow_stage_value else None

        buffer.add_node(
            AuthzNode(
                kind=NodeKind.HANDSHAKE_INTENT,
                ref=handshake_ref,
                display_name=intent.intent_id,
                attributes={
                    "intent_id": intent.intent_id,
                    "operation": intent.action.operation.value if intent.action.operation else intent.action.type,
                    "security_contract_version": intent.action.security_contract.version,
                },
                valid_from=intent.timestamp,
                valid_to=intent.valid_until,
                provenance=provenance,
            )
        )

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
                kind=NodeKind.ASSET,
                ref=asset_ref,
                display_name=intent.resource.asset_id,
                attributes={
                    "asset_id": intent.resource.asset_id,
                    "lot_id": intent.resource.lot_id,
                    "batch_twin_id": intent.resource.batch_twin_id,
                    "source_registration_id": intent.resource.source_registration_id,
                    "registration_decision_id": intent.resource.registration_decision_id,
                    "product_id": intent.resource.product_id,
                },
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
                    "asset_ref": asset_ref,
                    "resource_state_hash": intent.resource.resource_state_hash,
                    "provenance_hash": intent.resource.provenance_hash,
                    "batch_twin_id": intent.resource.batch_twin_id,
                    "lot_id": intent.resource.lot_id,
                },
                provenance=provenance,
            )
        )
        if twin_ref:
            buffer.add_node(
                AuthzNode(
                    kind=NodeKind.TWIN,
                    ref=twin_ref,
                    display_name=intent.resource.batch_twin_id,
                    provenance=provenance,
                )
            )
            buffer.add_edge(AuthzEdge(kind=EdgeKind.BACKED_BY, src=asset_ref, dst=twin_ref, provenance=provenance))
        if batch_ref:
            buffer.add_node(
                AuthzNode(
                    kind=NodeKind.ASSET_BATCH,
                    ref=batch_ref,
                    display_name=intent.resource.lot_id,
                    provenance=provenance,
                )
            )
            buffer.add_edge(AuthzEdge(kind=EdgeKind.BACKED_BY, src=asset_ref, dst=batch_ref, provenance=provenance))
        if product_ref:
            buffer.add_node(
                AuthzNode(
                    kind=NodeKind.PRODUCT,
                    ref=product_ref,
                    display_name=intent.resource.product_id,
                    attributes={"product_id": intent.resource.product_id},
                    provenance=provenance,
                )
            )
            if batch_ref:
                buffer.add_edge(AuthzEdge(kind=EdgeKind.PART_OF, src=batch_ref, dst=product_ref, provenance=provenance))
            else:
                buffer.add_edge(AuthzEdge(kind=EdgeKind.PART_OF, src=asset_ref, dst=product_ref, provenance=provenance))
        if source_registration_ref:
            buffer.add_node(
                AuthzNode(
                    kind=NodeKind.REGISTRATION,
                    ref=source_registration_ref,
                    display_name=intent.resource.source_registration_id,
                    attributes={
                        "registration_id": intent.resource.source_registration_id,
                        "registration_decision_id": intent.resource.registration_decision_id,
                    },
                    provenance=provenance,
                )
            )
            buffer.add_edge(AuthzEdge(kind=EdgeKind.BACKED_BY, src=asset_ref, dst=source_registration_ref, provenance=provenance))
            if batch_ref:
                buffer.add_edge(AuthzEdge(kind=EdgeKind.BACKED_BY, src=batch_ref, dst=source_registration_ref, provenance=provenance))
        if registration_decision_ref:
            buffer.add_node(
                AuthzNode(
                    kind=NodeKind.REGISTRATION_DECISION,
                    ref=registration_decision_ref,
                    display_name=intent.resource.registration_decision_id,
                    attributes={"registration_decision_id": intent.resource.registration_decision_id},
                    provenance=provenance,
                )
            )
            if source_registration_ref:
                buffer.add_edge(
                    AuthzEdge(kind=EdgeKind.BACKED_BY, src=source_registration_ref, dst=registration_decision_ref, provenance=provenance)
                )
        if workflow_stage_ref:
            buffer.add_node(
                AuthzNode(
                    kind=NodeKind.WORKFLOW_STAGE,
                    ref=workflow_stage_ref,
                    display_name=str(workflow_stage_value),
                    provenance=provenance,
                )
            )
            buffer.add_edge(AuthzEdge(kind=EdgeKind.AT_STAGE, src=handshake_ref, dst=workflow_stage_ref, provenance=provenance))
        buffer.add_edge(AuthzEdge(kind=EdgeKind.BACKED_BY, src=asset_ref, dst=resource_ref, provenance=provenance))
        buffer.add_edge(
            AuthzEdge(
                kind=EdgeKind.REQUESTED,
                src=handshake_ref,
                dst=asset_ref,
                operation=intent.action.operation.value if intent.action.operation else intent.action.type,
                attributes={
                    "intent_id": intent.intent_id,
                    "principal_ref": principal_ref,
                },
                provenance=provenance,
                valid_from=intent.timestamp,
                valid_to=intent.valid_until,
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
            buffer.add_edge(AuthzEdge(kind=EdgeKind.LOCATED_IN, src=asset_ref, dst=zone_ref, provenance=provenance))
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
        if predicate_lower in {
            "hasrole",
            "delegatedto",
            "delegatedby",
            "allowedoperation",
            "locatedinzone",
        }:
            self._warn_legacy_inferred_predicate(predicate_lower, buffer)
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

        if predicate_lower == "memberof":
            principal_ref = _principal_ref(subject)
            org_value = object_data.get("org") or object_data.get("organization") or object_data.get("member_of")
            if not org_value:
                return
            org_ref = _org_ref(org_value)
            buffer.add_node(AuthzNode(kind=NodeKind.PRINCIPAL, ref=principal_ref, provenance=provenance))
            buffer.add_node(AuthzNode(kind=NodeKind.ORG, ref=org_ref, provenance=provenance))
            buffer.add_edge(
                AuthzEdge(
                    kind=EdgeKind.MEMBER_OF,
                    src=principal_ref,
                    dst=org_ref,
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

        if predicate_lower == "delegatedby":
            principal_ref = _principal_ref(subject)
            delegator_value = (
                object_data.get("org")
                or object_data.get("organization")
                or object_data.get("principal")
                or object_data.get("delegator")
                or object_data.get("delegated_by")
            )
            if not delegator_value:
                return
            delegator_text = str(delegator_value).strip()
            if delegator_text.startswith("org:") or object_data.get("org") or object_data.get("organization"):
                delegator_ref = _org_ref(delegator_text)
                delegator_kind = NodeKind.ORG
            else:
                delegator_ref = _principal_ref(delegator_text)
                delegator_kind = NodeKind.PRINCIPAL
            buffer.add_node(AuthzNode(kind=NodeKind.PRINCIPAL, ref=principal_ref, provenance=provenance))
            buffer.add_node(AuthzNode(kind=delegator_kind, ref=delegator_ref, provenance=provenance))
            buffer.add_edge(
                AuthzEdge(
                    kind=EdgeKind.DELEGATED_BY,
                    src=principal_ref,
                    dst=delegator_ref,
                    provenance=provenance,
                    valid_from=_serialize_datetime(_value_from(fact, "valid_from")),
                    valid_to=_serialize_datetime(_value_from(fact, "valid_to")),
                )
            )
            return

        if predicate_lower == "boundtodevice":
            principal_ref = _principal_ref(subject)
            device_value = object_data.get("device") or object_data.get("device_id") or object_data.get("bound_device")
            if not device_value:
                return
            device_ref = _device_ref(device_value)
            buffer.add_node(AuthzNode(kind=NodeKind.PRINCIPAL, ref=principal_ref, provenance=provenance))
            buffer.add_node(AuthzNode(kind=NodeKind.DEVICE, ref=device_ref, provenance=provenance))
            buffer.add_edge(
                AuthzEdge(
                    kind=EdgeKind.BOUND_TO_DEVICE,
                    src=principal_ref,
                    dst=device_ref,
                    provenance=provenance,
                    valid_from=_serialize_datetime(_value_from(fact, "valid_from")),
                    valid_to=_serialize_datetime(_value_from(fact, "valid_to")),
                )
            )
            return

        if predicate_lower == "operates":
            src_ref = _normalize_permission_subject(subject)
            target_value = (
                object_data.get("facility")
                or object_data.get("facility_id")
                or object_data.get("device")
                or object_data.get("device_id")
                or object_data.get("target")
                or object_data.get("resource")
            )
            if not src_ref or not target_value:
                return
            target_text = str(target_value).strip()
            if target_text.startswith("device:"):
                target_ref = _device_ref(target_text)
                target_kind = NodeKind.DEVICE
            elif target_text.startswith("facility:") or object_data.get("facility") or object_data.get("facility_id"):
                target_ref = _facility_ref(target_text)
                target_kind = NodeKind.FACILITY
            elif target_text.startswith("resource:") or "://" in target_text:
                target_ref = _resource_ref(target_text)
                target_kind = NodeKind.RESOURCE
            else:
                target_ref = _facility_ref(target_text)
                target_kind = NodeKind.FACILITY
            buffer.add_node(AuthzNode(kind=_infer_subject_kind(src_ref), ref=src_ref, provenance=provenance))
            buffer.add_node(AuthzNode(kind=target_kind, ref=target_ref, provenance=provenance))
            buffer.add_edge(
                AuthzEdge(
                    kind=EdgeKind.OPERATES,
                    src=src_ref,
                    dst=target_ref,
                    provenance=provenance,
                    valid_from=_serialize_datetime(_value_from(fact, "valid_from")),
                    valid_to=_serialize_datetime(_value_from(fact, "valid_to")),
                )
            )
            return

        if predicate_lower in {"approvedforfacility", "approvedfor"}:
            src_ref = _normalize_permission_subject(subject)
            facility_value = (
                object_data.get("facility")
                or object_data.get("facility_id")
                or object_data.get("approved_for")
            )
            if not src_ref or not facility_value:
                return
            facility_ref = _facility_ref(facility_value)
            buffer.add_node(AuthzNode(kind=_infer_subject_kind(src_ref), ref=src_ref, provenance=provenance))
            buffer.add_node(AuthzNode(kind=NodeKind.FACILITY, ref=facility_ref, provenance=provenance))
            buffer.add_edge(
                AuthzEdge(
                    kind=EdgeKind.APPROVED_FOR,
                    src=src_ref,
                    dst=facility_ref,
                    provenance=provenance,
                    valid_from=_serialize_datetime(_value_from(fact, "valid_from")),
                    valid_to=_serialize_datetime(_value_from(fact, "valid_to")),
                )
            )
            return

        if predicate_lower == "controlszone":
            src_ref = _normalize_permission_subject(subject)
            zone_value = object_data.get("zone") or object_data.get("target_zone") or object_data.get("controls")
            if not src_ref or not zone_value:
                return
            zone_ref = _zone_ref(zone_value)
            buffer.add_node(AuthzNode(kind=_infer_subject_kind(src_ref), ref=src_ref, provenance=provenance))
            buffer.add_node(AuthzNode(kind=NodeKind.ZONE, ref=zone_ref, provenance=provenance))
            buffer.add_edge(
                AuthzEdge(
                    kind=EdgeKind.CONTROLS,
                    src=src_ref,
                    dst=zone_ref,
                    provenance=provenance,
                    valid_from=_serialize_datetime(_value_from(fact, "valid_from")),
                    valid_to=_serialize_datetime(_value_from(fact, "valid_to")),
                )
            )
            return

        if predicate_lower == "certifiedfor":
            src_ref = _normalize_permission_subject(subject)
            certification_value = (
                object_data.get("certification")
                or object_data.get("certification_id")
                or object_data.get("certified_for")
            )
            if not src_ref or not certification_value:
                return
            certification_ref = _certification_ref(certification_value)
            buffer.add_node(AuthzNode(kind=_infer_subject_kind(src_ref), ref=src_ref, provenance=provenance))
            buffer.add_node(
                AuthzNode(
                    kind=NodeKind.CERTIFICATION,
                    ref=certification_ref,
                    attributes={"status": object_data.get("status")},
                    provenance=provenance,
                )
            )
            buffer.add_edge(
                AuthzEdge(
                    kind=EdgeKind.CERTIFIED_FOR,
                    src=src_ref,
                    dst=certification_ref,
                    provenance=provenance,
                    valid_from=_serialize_datetime(object_data.get("valid_from") or _value_from(fact, "valid_from")),
                    valid_to=_serialize_datetime(object_data.get("valid_to") or _value_from(fact, "valid_to")),
                )
            )
            return

        if predicate_lower == "allowedoperation":
            src_ref = _normalize_permission_subject(subject)
            operation = str(object_data.get("operation") or "").strip().upper()
            resource_value = object_data.get("resource") or object_data.get("resource_uri") or object_data.get("asset_id")
            if not src_ref or not operation or not resource_value:
                return
            resource_text = str(resource_value)
            resource_ref = resource_value if "://" in resource_text else _resource_ref(resource_text)
            asset_ref = None if "://" in resource_text else _asset_ref(resource_text.removeprefix("resource:"))
            buffer.add_node(AuthzNode(kind=_infer_subject_kind(src_ref), ref=src_ref, provenance=provenance))
            buffer.add_node(
                AuthzNode(
                    kind=NodeKind.RESOURCE,
                    ref=resource_ref,
                    attributes={
                        "asset_id": resource_text.removeprefix("resource:") if asset_ref else None,
                        "asset_ref": asset_ref,
                    },
                    provenance=provenance,
                )
            )
            if asset_ref:
                buffer.add_node(AuthzNode(kind=NodeKind.ASSET, ref=asset_ref, provenance=provenance))
                buffer.add_edge(AuthzEdge(kind=EdgeKind.BACKED_BY, src=asset_ref, dst=resource_ref, provenance=provenance))

            zones = [_zone_ref(value) for value in object_data.get("zones", []) if str(value).strip()]
            networks = [_network_ref(value) for value in object_data.get("networks", []) if str(value).strip()]
            custody_points = [
                _custody_point_ref(value)
                for value in object_data.get("custody_points", [])
                if str(value).strip()
            ]
            for zone_ref in zones:
                buffer.add_node(AuthzNode(kind=NodeKind.ZONE, ref=zone_ref, provenance=provenance))
            for network_ref in networks:
                buffer.add_node(AuthzNode(kind=NodeKind.NETWORK_SEGMENT, ref=network_ref, provenance=provenance))
            for custody_point_ref in custody_points:
                buffer.add_node(AuthzNode(kind=NodeKind.CUSTODY_POINT, ref=custody_point_ref, provenance=provenance))

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
                        "custody_points": custody_points,
                        "resource_state_hash": object_data.get("resource_state_hash"),
                        "required_current_custodian": bool(object_data.get("required_current_custodian")),
                        "required_transferable_state": bool(object_data.get("required_transferable_state")),
                        "max_telemetry_age_seconds": object_data.get("max_telemetry_age_seconds"),
                        "max_inspection_age_seconds": object_data.get("max_inspection_age_seconds"),
                        "require_attestation": bool(object_data.get("require_attestation")),
                        "require_seal": bool(object_data.get("require_seal")),
                        "workflow_stages": [
                            _workflow_stage_ref(value)
                            for value in object_data.get("workflow_stages", [])
                            if str(value).strip()
                        ],
                        "require_approved_source_registration": bool(
                            object_data.get("require_approved_source_registration")
                        ),
                        "allow_quarantine": object_data.get("allow_quarantine", True),
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
            return

        if predicate_lower == "heldby":
            asset_ref = _asset_ref(subject)
            custodian_value = object_data.get("principal") or object_data.get("custodian") or object_data.get("held_by")
            if not custodian_value:
                return
            custodian_ref = _principal_ref(custodian_value)
            buffer.add_node(
                AuthzNode(
                    kind=NodeKind.ASSET,
                    ref=asset_ref,
                    display_name=str(object_data.get("asset_id") or subject),
                    attributes={
                        "asset_id": str(subject),
                        "batch_twin_id": object_data.get("batch_twin_id"),
                        "lot_id": object_data.get("lot_id"),
                        "transferable": object_data.get("transferable"),
                        "restricted": object_data.get("restricted"),
                        "state": object_data.get("state"),
                    },
                    provenance=provenance,
                )
            )
            buffer.add_node(AuthzNode(kind=NodeKind.PRINCIPAL, ref=custodian_ref, provenance=provenance))
            buffer.add_edge(
                AuthzEdge(
                    kind=EdgeKind.HELD_BY,
                    src=asset_ref,
                    dst=custodian_ref,
                    attributes={
                        "state": object_data.get("state"),
                        "transferable": object_data.get("transferable"),
                        "restricted": object_data.get("restricted"),
                    },
                    provenance=provenance,
                    valid_from=_serialize_datetime(_value_from(fact, "valid_from")),
                    valid_to=_serialize_datetime(_value_from(fact, "valid_to")),
                )
            )
            custody_point = object_data.get("custody_point")
            if custody_point:
                custody_point_ref = _custody_point_ref(custody_point)
                buffer.add_node(AuthzNode(kind=NodeKind.CUSTODY_POINT, ref=custody_point_ref, provenance=provenance))
                buffer.add_edge(AuthzEdge(kind=EdgeKind.LOCATED_IN, src=asset_ref, dst=custody_point_ref, provenance=provenance))
            zone = object_data.get("zone") or object_data.get("target_zone")
            if zone:
                zone_ref = _zone_ref(zone)
                buffer.add_node(AuthzNode(kind=NodeKind.ZONE, ref=zone_ref, provenance=provenance))
                buffer.add_edge(AuthzEdge(kind=EdgeKind.LOCATED_IN, src=asset_ref, dst=zone_ref, provenance=provenance))
            twin_id = object_data.get("batch_twin_id") or object_data.get("twin_id")
            if twin_id:
                twin_ref = twin_id if str(twin_id).startswith("twin:") else f"twin:{twin_id}"
                buffer.add_node(AuthzNode(kind=NodeKind.TWIN, ref=twin_ref, provenance=provenance))
                buffer.add_edge(AuthzEdge(kind=EdgeKind.BACKED_BY, src=asset_ref, dst=twin_ref, provenance=provenance))
            return

        if predicate_lower == "transferredfrom":
            asset_ref = _asset_ref(subject)
            previous_custodian = object_data.get("principal") or object_data.get("custodian") or object_data.get("transferred_from")
            if not previous_custodian:
                return
            previous_ref = _principal_ref(previous_custodian)
            buffer.add_node(AuthzNode(kind=NodeKind.ASSET, ref=asset_ref, provenance=provenance))
            buffer.add_node(AuthzNode(kind=NodeKind.PRINCIPAL, ref=previous_ref, provenance=provenance))
            buffer.add_edge(
                AuthzEdge(
                    kind=EdgeKind.TRANSFERRED_FROM,
                    src=asset_ref,
                    dst=previous_ref,
                    provenance=provenance,
                    valid_from=_serialize_datetime(_value_from(fact, "valid_from")),
                    valid_to=_serialize_datetime(_value_from(fact, "valid_to")),
                )
            )
            return

        if predicate_lower == "attestedby":
            asset_ref = _asset_ref(subject)
            attestation_id = object_data.get("attestation_id") or f"{subject}:{fact_id}"
            attestation_ref = _attestation_ref(attestation_id)
            attestor = object_data.get("principal") or object_data.get("attestor") or object_data.get("issuer")
            buffer.add_node(AuthzNode(kind=NodeKind.ASSET, ref=asset_ref, provenance=provenance))
            buffer.add_node(
                AuthzNode(
                    kind=NodeKind.ATTESTATION,
                    ref=attestation_ref,
                    attributes={
                        "attestation_type": object_data.get("attestation_type"),
                        "status": object_data.get("status"),
                        "authority": object_data.get("authority"),
                        "evidence_ref": object_data.get("evidence_ref"),
                    },
                    valid_from=_serialize_datetime(object_data.get("valid_from") or _value_from(fact, "valid_from")),
                    valid_to=_serialize_datetime(object_data.get("valid_to") or _value_from(fact, "valid_to")),
                    provenance=provenance,
                )
            )
            buffer.add_edge(
                AuthzEdge(
                    kind=EdgeKind.ATTESTED_BY,
                    src=asset_ref,
                    dst=attestation_ref,
                    provenance=provenance,
                    valid_from=_serialize_datetime(object_data.get("valid_from") or _value_from(fact, "valid_from")),
                    valid_to=_serialize_datetime(object_data.get("valid_to") or _value_from(fact, "valid_to")),
                )
            )
            if attestor:
                attestor_ref = _principal_ref(attestor)
                buffer.add_node(AuthzNode(kind=NodeKind.PRINCIPAL, ref=attestor_ref, provenance=provenance))
                buffer.add_edge(AuthzEdge(kind=EdgeKind.RECORDED_BY, src=attestation_ref, dst=attestor_ref, provenance=provenance))
            return

        if predicate_lower == "observedin":
            asset_ref = _asset_ref(subject)
            observation_id = object_data.get("observation_id") or f"{subject}:{fact_id}"
            observation_ref = _sensor_observation_ref(observation_id)
            observed_at = _serialize_datetime(
                object_data.get("observed_at")
                or object_data.get("captured_at")
                or _value_from(fact, "valid_from")
            )
            buffer.add_node(AuthzNode(kind=NodeKind.ASSET, ref=asset_ref, provenance=provenance))
            buffer.add_node(
                AuthzNode(
                    kind=NodeKind.SENSOR_OBSERVATION,
                    ref=observation_ref,
                    attributes={
                        "measurement_type": object_data.get("measurement_type"),
                        "quality_score": object_data.get("quality_score"),
                        "value": object_data.get("value"),
                        "unit": object_data.get("unit"),
                        "custody_point": object_data.get("custody_point"),
                    },
                    valid_from=observed_at,
                    valid_to=observed_at,
                    provenance=provenance,
                )
            )
            buffer.add_edge(
                AuthzEdge(
                    kind=EdgeKind.OBSERVED_IN,
                    src=asset_ref,
                    dst=observation_ref,
                    attributes={
                        "measurement_type": object_data.get("measurement_type"),
                        "quality_score": object_data.get("quality_score"),
                    },
                    provenance=provenance,
                    valid_from=observed_at,
                    valid_to=observed_at,
                )
            )
            custody_point = object_data.get("custody_point")
            if custody_point:
                custody_point_ref = _custody_point_ref(custody_point)
                buffer.add_node(AuthzNode(kind=NodeKind.CUSTODY_POINT, ref=custody_point_ref, provenance=provenance))
                buffer.add_edge(AuthzEdge(kind=EdgeKind.LOCATED_IN, src=asset_ref, dst=custody_point_ref, provenance=provenance))
            return

        if predicate_lower == "sealedwith":
            asset_ref = _asset_ref(subject)
            seal_value = object_data.get("seal_id") or object_data.get("nfc_uid") or object_data.get("uid")
            if not seal_value:
                return
            seal_ref = f"registration:seal:{seal_value}"
            buffer.add_node(AuthzNode(kind=NodeKind.ASSET, ref=asset_ref, provenance=provenance))
            buffer.add_node(
                AuthzNode(
                    kind=NodeKind.REGISTRATION,
                    ref=seal_ref,
                    attributes={
                        "seal_id": seal_value,
                        "seal_kind": object_data.get("seal_kind", "anti_counterfeit"),
                    },
                    provenance=provenance,
                )
            )
            buffer.add_edge(AuthzEdge(kind=EdgeKind.SEALED_WITH, src=asset_ref, dst=seal_ref, provenance=provenance))

    def _warn_legacy_inferred_predicate(self, predicate: str, buffer: _ProjectionBuffer) -> None:
        if predicate in buffer.legacy_predicates_warned:
            return
        buffer.legacy_predicates_warned.add(predicate)
        logger.warning(
            "Authz graph is deriving edges from legacy fact predicate '%s'. "
            "Migrate this relationship into snapshot rule metadata authz_graph.edge_manifests.",
            predicate,
        )

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
        registration_ref = _registration_ref(str(registration_id))
        producer_ref = _principal_ref(producer_id)
        lot_ref = _resource_ref(f"lot:{lot_id}")
        batch_ref = _asset_batch_ref(lot_id)

        buffer.add_node(
            AuthzNode(
                kind=NodeKind.REGISTRATION,
                ref=registration_ref,
                attributes={
                    "registration_id": str(registration_id),
                    "status": str(_value_from(registration, "status") or ""),
                    "lot_id": lot_id,
                    "producer_id": producer_id,
                },
                provenance=provenance,
            )
        )
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
        buffer.add_node(
            AuthzNode(
                kind=NodeKind.ASSET_BATCH,
                ref=batch_ref,
                display_name=str(lot_id),
                attributes={
                    "lot_id": lot_id,
                    "rare_grade_profile_id": _value_from(registration, "rare_grade_profile_id"),
                    "status": str(_value_from(registration, "status") or ""),
                },
                provenance=provenance,
            )
        )
        buffer.add_edge(AuthzEdge(kind=EdgeKind.RECORDED_BY, src=registration_ref, dst=producer_ref, provenance=provenance))
        buffer.add_edge(AuthzEdge(kind=EdgeKind.BACKED_BY, src=lot_ref, dst=registration_ref, provenance=provenance))
        buffer.add_edge(AuthzEdge(kind=EdgeKind.BACKED_BY, src=batch_ref, dst=registration_ref, provenance=provenance))

    def _project_registration_decision(
        self,
        registration_decision: RegistrationDecision | Dict[str, Any],
        buffer: _ProjectionBuffer,
        *,
        snapshot_id: Optional[int],
        snapshot_version: Optional[str],
    ) -> None:
        decision_id = _value_from(registration_decision, "id")
        registration_id = _value_from(registration_decision, "registration_id")
        if decision_id is None or registration_id is None:
            return

        provenance = GraphProvenance(
            source_type="registration_decision",
            source_ref=str(decision_id),
            snapshot_id=snapshot_id or _value_from(registration_decision, "policy_snapshot_id"),
            snapshot_version=snapshot_version,
            metadata={"decision": _value_from(registration_decision, "decision")},
        )
        decision_ref = _registration_decision_ref(str(decision_id))
        registration_ref = _registration_ref(str(registration_id))

        buffer.add_node(
            AuthzNode(
                kind=NodeKind.REGISTRATION_DECISION,
                ref=decision_ref,
                attributes={
                    "registration_id": str(registration_id),
                    "decision": str(_value_from(registration_decision, "decision") or ""),
                    "confidence": _value_from(registration_decision, "confidence"),
                    "grade_result": _value_from(registration_decision, "grade_result"),
                },
                valid_from=_serialize_datetime(_value_from(registration_decision, "decided_at")),
                valid_to=_serialize_datetime(_value_from(registration_decision, "decided_at")),
                provenance=provenance,
            )
        )
        buffer.add_node(AuthzNode(kind=NodeKind.REGISTRATION, ref=registration_ref, provenance=provenance))
        buffer.add_edge(AuthzEdge(kind=EdgeKind.BACKED_BY, src=registration_ref, dst=decision_ref, provenance=provenance))

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
        payload = _value_from(tracking_event, "payload", {}) or {}
        captured_at = _serialize_datetime(_value_from(tracking_event, "captured_at"))
        subject_id = _value_from(tracking_event, "subject_id")
        subject_type = str(_value_from(tracking_event, "subject_type") or "").strip().lower()
        buffer.add_node(
            AuthzNode(
                kind=NodeKind.TRACKING_EVENT,
                ref=event_ref,
                attributes={
                    "event_type": _value_from(tracking_event, "event_type"),
                    "source_kind": _value_from(tracking_event, "source_kind"),
                    "subject_type": subject_type,
                    "subject_id": subject_id,
                    "sha256": _value_from(tracking_event, "sha256"),
                },
                valid_from=captured_at,
                valid_to=captured_at,
                provenance=provenance,
            )
        )
        if registration_id is not None:
            registration_ref = f"registration:{registration_id}"
            buffer.add_node(AuthzNode(kind=NodeKind.REGISTRATION, ref=registration_ref, provenance=provenance))
            buffer.add_edge(AuthzEdge(kind=EdgeKind.BACKED_BY, src=registration_ref, dst=event_ref, provenance=provenance))
        if producer_id:
            producer_ref = _principal_ref(producer_id)
            buffer.add_node(AuthzNode(kind=NodeKind.PRINCIPAL, ref=producer_ref, provenance=provenance))
            buffer.add_edge(AuthzEdge(kind=EdgeKind.RECORDED_BY, src=event_ref, dst=producer_ref, provenance=provenance))
        asset_key = payload.get("asset_id") or subject_id
        if asset_key and subject_type in {"asset", "lot", "batch", ""}:
            asset_ref = _asset_ref(asset_key)
            buffer.add_node(
                AuthzNode(
                    kind=NodeKind.ASSET,
                    ref=asset_ref,
                    display_name=str(asset_key),
                    attributes={"asset_id": asset_key},
                    provenance=provenance,
                )
            )
            buffer.add_edge(AuthzEdge(kind=EdgeKind.BACKED_BY, src=asset_ref, dst=event_ref, provenance=provenance))

            custody_point = payload.get("custody_point") or payload.get("facility_id") or payload.get("warehouse_id")
            if custody_point:
                custody_point_ref = _custody_point_ref(custody_point)
                buffer.add_node(AuthzNode(kind=NodeKind.CUSTODY_POINT, ref=custody_point_ref, provenance=provenance))
                buffer.add_edge(AuthzEdge(kind=EdgeKind.LOCATED_IN, src=asset_ref, dst=custody_point_ref, provenance=provenance))

            zone = payload.get("zone")
            if zone:
                zone_ref = _zone_ref(zone)
                buffer.add_node(AuthzNode(kind=NodeKind.ZONE, ref=zone_ref, provenance=provenance))
                buffer.add_edge(AuthzEdge(kind=EdgeKind.LOCATED_IN, src=asset_ref, dst=zone_ref, provenance=provenance))

            seal_value = payload.get("seal_id") or payload.get("nfc_uid")
            if seal_value:
                seal_ref = f"registration:seal:{seal_value}"
                buffer.add_node(
                    AuthzNode(
                        kind=NodeKind.REGISTRATION,
                        ref=seal_ref,
                        attributes={"seal_id": seal_value, "source_event_id": str(event_id)},
                        provenance=provenance,
                    )
                )
                buffer.add_edge(AuthzEdge(kind=EdgeKind.SEALED_WITH, src=asset_ref, dst=seal_ref, provenance=provenance))

            if payload.get("measurement_type") or payload.get("sensor_id"):
                observation_ref = _sensor_observation_ref(str(event_id))
                buffer.add_node(
                    AuthzNode(
                        kind=NodeKind.SENSOR_OBSERVATION,
                        ref=observation_ref,
                        attributes={
                            "measurement_type": payload.get("measurement_type"),
                            "quality_score": payload.get("quality_score"),
                            "value": payload.get("value"),
                            "unit": payload.get("unit"),
                            "sensor_id": payload.get("sensor_id"),
                        },
                        valid_from=captured_at,
                        valid_to=captured_at,
                        provenance=provenance,
                    )
                )
                buffer.add_edge(
                    AuthzEdge(
                        kind=EdgeKind.OBSERVED_IN,
                        src=asset_ref,
                        dst=observation_ref,
                        attributes={"quality_score": payload.get("quality_score")},
                        valid_from=captured_at,
                        valid_to=captured_at,
                        provenance=provenance,
                    )
                )

            if payload.get("decision_hash"):
                fragment_ref = _passport_fragment_ref(str(event_id))
                buffer.add_node(
                    AuthzNode(
                        kind=NodeKind.DIGITAL_PASSPORT_FRAGMENT,
                        ref=fragment_ref,
                        attributes={
                            "decision_hash": payload.get("decision_hash"),
                            "decision": payload.get("decision"),
                        },
                        valid_from=captured_at,
                        valid_to=captured_at,
                        provenance=provenance,
                    )
                )
                buffer.add_edge(AuthzEdge(kind=EdgeKind.BACKED_BY, src=asset_ref, dst=fragment_ref, provenance=provenance))


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
    if subject.startswith("org:"):
        return _org_ref(subject)
    if subject.startswith("role:"):
        return _role_ref(subject)
    if subject.startswith("device:"):
        return _device_ref(subject)
    if subject.startswith("facility:"):
        return _facility_ref(subject)
    if subject.startswith("certification:"):
        return _certification_ref(subject)
    if subject.startswith("product:"):
        return _product_ref(subject)
    if subject.startswith("workflow_stage:"):
        return _workflow_stage_ref(subject)
    if subject.startswith("registration_decision:"):
        return _registration_decision_ref(subject)
    if subject.startswith("registration:"):
        return _registration_ref(subject)
    if subject.startswith("zone:"):
        return _zone_ref(subject)
    if subject.startswith("network:"):
        return _network_ref(subject)
    if subject.startswith("custody_point:"):
        return _custody_point_ref(subject)
    return _principal_ref(subject)


def _infer_subject_kind(subject_ref: str) -> NodeKind:
    if subject_ref.startswith("org:"):
        return NodeKind.ORG
    if subject_ref.startswith("role:"):
        return NodeKind.ROLE_PROFILE
    if subject_ref.startswith("device:"):
        return NodeKind.DEVICE
    if subject_ref.startswith("facility:"):
        return NodeKind.FACILITY
    if subject_ref.startswith("certification:"):
        return NodeKind.CERTIFICATION
    if subject_ref.startswith("product:"):
        return NodeKind.PRODUCT
    if subject_ref.startswith("workflow_stage:"):
        return NodeKind.WORKFLOW_STAGE
    if subject_ref.startswith("registration_decision:"):
        return NodeKind.REGISTRATION_DECISION
    if subject_ref.startswith("registration:"):
        return NodeKind.REGISTRATION
    if subject_ref.startswith("zone:"):
        return NodeKind.ZONE
    if subject_ref.startswith("network:"):
        return NodeKind.NETWORK_SEGMENT
    if subject_ref.startswith("custody_point:"):
        return NodeKind.CUSTODY_POINT
    return NodeKind.PRINCIPAL


def _normalize_selector_ref(selector: str) -> str:
    selector = str(selector).strip()
    if not selector:
        return ""
    if selector.startswith("principal:"):
        return _principal_ref(selector)
    if selector.startswith("org:"):
        return _org_ref(selector)
    if selector.startswith("role:"):
        return _role_ref(selector)
    if selector.startswith("device:"):
        return _device_ref(selector)
    if selector.startswith("facility:"):
        return _facility_ref(selector)
    if selector.startswith("certification:"):
        return _certification_ref(selector)
    if selector.startswith("product:"):
        return _product_ref(selector)
    if selector.startswith("workflow_stage:"):
        return _workflow_stage_ref(selector)
    if selector.startswith("registration_decision:"):
        return _registration_decision_ref(selector)
    if selector.startswith("registration:"):
        return _registration_ref(selector)
    if selector.startswith("asset:"):
        return _asset_ref(selector)
    if selector.startswith("asset_batch:"):
        return _asset_batch_ref(selector)
    if selector.startswith("custody_point:"):
        return _custody_point_ref(selector)
    if selector.startswith("attestation:"):
        return _attestation_ref(selector)
    if selector.startswith("inspection:"):
        return _inspection_ref(selector)
    if selector.startswith("sensor_observation:"):
        return _sensor_observation_ref(selector)
    if selector.startswith("handshake_intent:"):
        return _handshake_intent_ref(selector)
    if selector.startswith("zone:"):
        return _zone_ref(selector)
    if selector.startswith("network:"):
        return _network_ref(selector)
    return _resource_ref(selector)


def _infer_selector_kind(selector_ref: str) -> NodeKind:
    if selector_ref.startswith("principal:"):
        return NodeKind.PRINCIPAL
    if selector_ref.startswith("org:"):
        return NodeKind.ORG
    if selector_ref.startswith("role:"):
        return NodeKind.ROLE_PROFILE
    if selector_ref.startswith("device:"):
        return NodeKind.DEVICE
    if selector_ref.startswith("facility:"):
        return NodeKind.FACILITY
    if selector_ref.startswith("certification:"):
        return NodeKind.CERTIFICATION
    if selector_ref.startswith("product:"):
        return NodeKind.PRODUCT
    if selector_ref.startswith("workflow_stage:"):
        return NodeKind.WORKFLOW_STAGE
    if selector_ref.startswith("registration_decision:"):
        return NodeKind.REGISTRATION_DECISION
    if selector_ref.startswith("registration:"):
        return NodeKind.REGISTRATION
    if selector_ref.startswith("asset:"):
        return NodeKind.ASSET
    if selector_ref.startswith("asset_batch:"):
        return NodeKind.ASSET_BATCH
    if selector_ref.startswith("custody_point:"):
        return NodeKind.CUSTODY_POINT
    if selector_ref.startswith("attestation:"):
        return NodeKind.ATTESTATION
    if selector_ref.startswith("inspection:"):
        return NodeKind.INSPECTION
    if selector_ref.startswith("sensor_observation:"):
        return NodeKind.SENSOR_OBSERVATION
    if selector_ref.startswith("handshake_intent:"):
        return NodeKind.HANDSHAKE_INTENT
    if selector_ref.startswith("zone:"):
        return NodeKind.ZONE
    if selector_ref.startswith("network:"):
        return NodeKind.NETWORK_SEGMENT
    return NodeKind.RESOURCE
