from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from seedcore.models.action_intent import ActionIntent
from seedcore.models.fact import Fact
from seedcore.models.source_registration import SourceRegistration, SourceRegistrationStatus
from seedcore.ops.pkg.authz_graph import (
    AuthzGraphCompiler,
    AuthzGraphProjector,
    EdgeKind,
    NodeKind,
)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def test_projector_projects_action_intent_into_requested_subgraph() -> None:
    now = datetime.now(timezone.utc)
    intent = ActionIntent(
        intent_id=str(uuid4()),
        timestamp=_iso(now),
        valid_until=_iso(now + timedelta(seconds=30)),
        principal={
            "agent_id": "agent-alpha",
            "role_profile": "warehouse_operator",
            "actor_token": "seedcore_hmac_v1.test.payload.sig",
        },
        action={
            "type": "pick",
            "parameters": {"max_compute_cycles": 500},
            "security_contract": {"hash": "abc123", "version": "rules@2.0.0"},
        },
        resource={
            "asset_id": "asset-42",
            "resource_uri": "seedcore://cluster-a/memory-bank/42",
            "resource_state_hash": "state-hash-1",
            "target_zone": "cold-room",
            "provenance_hash": "prov-1",
        },
        environment={"origin_network": "plant-a"},
    )

    snapshot = AuthzGraphProjector().project_snapshot(
        snapshot_ref="pkg-authz@test",
        snapshot_version="rules@2.0.0",
        action_intents=[intent],
    )

    node_kinds = {node.ref: node.kind for node in snapshot.nodes}
    edge_kinds = {(edge.kind, edge.src, edge.dst) for edge in snapshot.edges}

    assert node_kinds["principal:agent-alpha"] == NodeKind.PRINCIPAL
    assert node_kinds["role:warehouse_operator"] == NodeKind.ROLE_PROFILE
    assert node_kinds["seedcore://cluster-a/memory-bank/42"] == NodeKind.RESOURCE
    assert node_kinds["zone:cold-room"] == NodeKind.ZONE
    assert (EdgeKind.HAS_ROLE, "principal:agent-alpha", "role:warehouse_operator") in edge_kinds
    assert (EdgeKind.REQUESTED, "principal:agent-alpha", "seedcore://cluster-a/memory-bank/42") in edge_kinds


def test_compiler_materializes_role_based_permission_index() -> None:
    now = datetime.now(timezone.utc)
    projector = AuthzGraphProjector()
    facts = [
        Fact(
            id=uuid4(),
            text="agent role",
            snapshot_id=7,
            namespace="authz",
            subject="agent-alpha",
            predicate="hasRole",
            object_data={"role": "warehouse_operator"},
            valid_from=now - timedelta(minutes=5),
            valid_to=now + timedelta(minutes=5),
            created_by="test",
        ),
        Fact(
            id=uuid4(),
            text="resource zone",
            snapshot_id=7,
            namespace="authz",
            subject="asset-42",
            predicate="locatedInZone",
            object_data={"zone": "cold-room"},
            created_by="test",
        ),
        Fact(
            id=uuid4(),
            text="role permission",
            snapshot_id=7,
            namespace="authz",
            subject="role:warehouse_operator",
            predicate="allowedOperation",
            object_data={
                "operation": "PICK",
                "resource": "asset-42",
                "zones": ["cold-room"],
                "networks": ["plant-a"],
            },
            valid_from=now - timedelta(minutes=5),
            valid_to=now + timedelta(minutes=5),
            created_by="test",
        ),
    ]

    graph = projector.project_snapshot(
        snapshot_ref="pkg-authz@test",
        snapshot_id=7,
        snapshot_version="rules@2.0.0",
        facts=facts,
    )
    compiled = AuthzGraphCompiler().compile(graph)

    allow_match = compiled.can_access(
        principal_ref="principal:agent-alpha",
        operation="PICK",
        resource_ref="resource:asset-42",
        zone_ref="zone:cold-room",
        network_ref="network:plant-a",
    )
    wrong_network = compiled.can_access(
        principal_ref="principal:agent-alpha",
        operation="PICK",
        resource_ref="resource:asset-42",
        zone_ref="zone:cold-room",
        network_ref="network:plant-b",
    )
    wrong_operation = compiled.can_access(
        principal_ref="principal:agent-alpha",
        operation="RELEASE",
        resource_ref="resource:asset-42",
        zone_ref="zone:cold-room",
        network_ref="network:plant-a",
    )

    assert allow_match.allowed is True
    assert allow_match.reason == "matched_allow_permission"
    assert "role:warehouse_operator" in allow_match.matched_subjects
    assert wrong_network.allowed is False
    assert wrong_network.reason == "no_matching_permission"
    assert wrong_operation.allowed is False


def test_projector_projects_source_registration_backing_edges() -> None:
    registration = SourceRegistration(
        id=uuid4(),
        lot_id="lot-2026-01",
        producer_id="producer-7",
        status=SourceRegistrationStatus.APPROVED,
        claimed_origin={"country": "TH"},
        collection_site={"site_id": "farm-9"},
    )

    snapshot = AuthzGraphProjector().project_snapshot(
        snapshot_ref="pkg-authz@test",
        registrations=[registration],
    )

    refs = {node.ref for node in snapshot.nodes}
    edge_kinds = {(edge.kind, edge.src, edge.dst) for edge in snapshot.edges}

    assert f"registration:{registration.id}" in refs
    assert "principal:producer-7" in refs
    assert "resource:lot:lot-2026-01" in refs
    assert (EdgeKind.RECORDED_BY, f"registration:{registration.id}", "principal:producer-7") in edge_kinds
