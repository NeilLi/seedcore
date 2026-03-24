from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from seedcore.models.action_intent import ActionIntent
from seedcore.models.fact import Fact
from seedcore.models.source_registration import SourceRegistration, SourceRegistrationStatus
from seedcore.ops.pkg.authz_graph import (
    AuthzDecisionDisposition,
    AuthzGraphCompiler,
    AuthzGraphProjector,
    AuthzTransitionRequest,
    EdgeKind,
    NodeKind,
    PermissionEffect,
    PolicyEdgeManifest,
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
            "lot_id": "lot-2026-01",
            "batch_twin_id": "batch-42",
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
    assert node_kinds["handshake_intent:" + intent.intent_id] == NodeKind.HANDSHAKE_INTENT
    assert node_kinds["asset:asset-42"] == NodeKind.ASSET
    assert node_kinds["seedcore://cluster-a/memory-bank/42"] == NodeKind.RESOURCE
    assert node_kinds["zone:cold-room"] == NodeKind.ZONE
    assert (EdgeKind.HAS_ROLE, "principal:agent-alpha", "role:warehouse_operator") in edge_kinds
    assert (EdgeKind.REQUESTED, "principal:agent-alpha", "seedcore://cluster-a/memory-bank/42") in edge_kinds
    assert (EdgeKind.BACKED_BY, "asset:asset-42", "twin:batch-42") in edge_kinds


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


def test_compiler_resolves_authority_paths_for_org_and_device_subjects() -> None:
    now = datetime.now(timezone.utc)
    facts = [
        Fact(
            id=uuid4(),
            text="org membership",
            snapshot_id=8,
            namespace="authz",
            subject="agent-alpha",
            predicate="memberOf",
            object_data={"org": "acme-logistics"},
            valid_from=now - timedelta(minutes=5),
            valid_to=now + timedelta(minutes=5),
            created_by="test",
        ),
        Fact(
            id=uuid4(),
            text="device binding",
            snapshot_id=8,
            namespace="authz",
            subject="agent-alpha",
            predicate="boundToDevice",
            object_data={"device_id": "edge-7"},
            valid_from=now - timedelta(minutes=5),
            valid_to=now + timedelta(minutes=5),
            created_by="test",
        ),
        Fact(
            id=uuid4(),
            text="org permission",
            snapshot_id=8,
            namespace="authz",
            subject="org:acme-logistics",
            predicate="allowedOperation",
            object_data={"operation": "MOVE", "resource": "asset-42"},
            valid_from=now - timedelta(minutes=5),
            valid_to=now + timedelta(minutes=5),
            created_by="test",
        ),
        Fact(
            id=uuid4(),
            text="device permission",
            snapshot_id=8,
            namespace="authz",
            subject="device:edge-7",
            predicate="allowedOperation",
            object_data={"operation": "ATTEST", "resource": "asset-42"},
            valid_from=now - timedelta(minutes=5),
            valid_to=now + timedelta(minutes=5),
            created_by="test",
        ),
    ]

    compiled = AuthzGraphCompiler().compile(
        AuthzGraphProjector().project_snapshot(
            snapshot_ref="pkg-authz@authority-paths",
            snapshot_id=8,
            snapshot_version="rules@8.0.0",
            facts=facts,
        )
    )

    move_match = compiled.can_access(
        principal_ref="principal:agent-alpha",
        operation="MOVE",
        resource_ref="resource:asset-42",
    )
    attest_match = compiled.can_access(
        principal_ref="principal:agent-alpha",
        operation="ATTEST",
        resource_ref="resource:asset-42",
    )

    assert move_match.allowed is True
    assert ("principal:agent-alpha", "org:acme-logistics") in move_match.authority_paths
    assert attest_match.allowed is True
    assert ("principal:agent-alpha", "device:edge-7") in attest_match.authority_paths


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


def test_projector_projects_asset_centric_supply_chain_facts() -> None:
    now = datetime.now(timezone.utc)
    facts = [
        Fact(
            id=uuid4(),
            text="custody",
            snapshot_id=11,
            namespace="authz",
            subject="asset-88",
            predicate="heldBy",
            object_data={
                "custodian": "driver-7",
                "custody_point": "vault-a",
                "zone": "bangkok",
                "transferable": True,
                "batch_twin_id": "batch-88",
            },
            valid_from=now - timedelta(minutes=2),
            valid_to=now + timedelta(minutes=5),
            created_by="test",
        ),
        Fact(
            id=uuid4(),
            text="lineage",
            snapshot_id=11,
            namespace="authz",
            subject="asset-88",
            predicate="transferredFrom",
            object_data={"custodian": "harvester-3"},
            valid_from=now - timedelta(hours=1),
            created_by="test",
        ),
        Fact(
            id=uuid4(),
            text="attestation",
            snapshot_id=11,
            namespace="authz",
            subject="asset-88",
            predicate="attestedBy",
            object_data={
                "attestation_id": "lab-cert-88",
                "attestor": "lab-1",
                "attestation_type": "lab_report",
                "valid_from": _iso(now - timedelta(days=1)),
                "valid_to": _iso(now + timedelta(days=1)),
            },
            created_by="test",
        ),
        Fact(
            id=uuid4(),
            text="telemetry",
            snapshot_id=11,
            namespace="authz",
            subject="asset-88",
            predicate="observedIn",
            object_data={
                "observation_id": "obs-88",
                "measurement_type": "temperature",
                "quality_score": 0.97,
                "observed_at": _iso(now - timedelta(minutes=1)),
                "custody_point": "vault-a",
            },
            created_by="test",
        ),
        Fact(
            id=uuid4(),
            text="seal",
            snapshot_id=11,
            namespace="authz",
            subject="asset-88",
            predicate="sealedWith",
            object_data={"nfc_uid": "nfc-88"},
            created_by="test",
        ),
    ]

    snapshot = AuthzGraphProjector().project_snapshot(
        snapshot_ref="pkg-authz@asset-phase1",
        snapshot_id=11,
        snapshot_version="rules@11.0.0",
        facts=facts,
    )

    node_kinds = {node.ref: node.kind for node in snapshot.nodes}
    edge_kinds = {(edge.kind, edge.src, edge.dst) for edge in snapshot.edges}

    assert node_kinds["asset:asset-88"] == NodeKind.ASSET
    assert node_kinds["custody_point:vault-a"] == NodeKind.CUSTODY_POINT
    assert node_kinds["attestation:lab-cert-88"] == NodeKind.ATTESTATION
    assert node_kinds["sensor_observation:obs-88"] == NodeKind.SENSOR_OBSERVATION
    assert (EdgeKind.HELD_BY, "asset:asset-88", "principal:driver-7") in edge_kinds
    assert (EdgeKind.TRANSFERRED_FROM, "asset:asset-88", "principal:harvester-3") in edge_kinds
    assert (EdgeKind.ATTESTED_BY, "asset:asset-88", "attestation:lab-cert-88") in edge_kinds
    assert (EdgeKind.OBSERVED_IN, "asset:asset-88", "sensor_observation:obs-88") in edge_kinds
    assert (EdgeKind.SEALED_WITH, "asset:asset-88", "registration:seal:nfc-88") in edge_kinds


def test_projector_projects_explicit_policy_edge_manifest_before_dynamic_facts() -> None:
    manifest = PolicyEdgeManifest(
        source_selector="role:warehouse_operator",
        target_selector="resource:asset-42",
        operation="PICK",
        conditions={"zones": ["cold-room"], "networks": ["plant-a"]},
        rule_id="rule-authz-1",
        rule_name="warehouse_pick_allow",
    )
    graph = AuthzGraphProjector().project_snapshot(
        snapshot_ref="pkg-authz@test",
        snapshot_id=7,
        snapshot_version="rules@2.1.0",
        policy_edge_manifests=[manifest],
    )
    compiled = AuthzGraphCompiler().compile(graph)

    match = compiled.can_access(
        principal_ref="role:warehouse_operator",
        operation="PICK",
        resource_ref="resource:asset-42",
        zone_ref="zone:cold-room",
        network_ref="network:plant-a",
    )

    assert any(
        edge.kind == EdgeKind.CAN
        and edge.src == "role:warehouse_operator"
        and edge.dst == "resource:asset-42"
        and edge.effect == PermissionEffect.ALLOW
        for edge in graph.edges
    )
    assert match.allowed is True


def test_projector_warns_when_legacy_inferred_permission_fact_is_used(caplog) -> None:
    now = datetime.now(timezone.utc)
    facts = [
        Fact(
            id=uuid4(),
            text="role permission",
            snapshot_id=7,
            namespace="authz",
            subject="role:warehouse_operator",
            predicate="allowedOperation",
            object_data={"operation": "PICK", "resource": "asset-42"},
            valid_from=now - timedelta(minutes=5),
            valid_to=now + timedelta(minutes=5),
            created_by="test",
        )
    ]

    with caplog.at_level("WARNING"):
        AuthzGraphProjector().project_snapshot(
            snapshot_ref="pkg-authz@test",
            snapshot_id=7,
            snapshot_version="rules@2.0.0",
            facts=facts,
        )

    assert any("legacy fact predicate 'allowedoperation'" in message.lower() for message in caplog.messages)


def test_compiler_explicit_deny_overrides_allow() -> None:
    manifests = [
        PolicyEdgeManifest(
            source_selector="role:warehouse_operator",
            target_selector="resource:asset-42",
            operation="PICK",
            conditions={"zones": ["cold-room"]},
            rule_id="allow-1",
            rule_name="warehouse_pick_allow",
        ),
        PolicyEdgeManifest(
            source_selector="role:warehouse_operator",
            target_selector="resource:asset-42",
            operation="PICK",
            effect=PermissionEffect.DENY,
            conditions={"zones": ["cold-room"]},
            rule_id="deny-1",
            rule_name="warehouse_pick_deny",
        ),
    ]

    compiled = AuthzGraphCompiler().compile(
        AuthzGraphProjector().project_snapshot(
            snapshot_ref="pkg-authz@test",
            snapshot_version="rules@2.1.0",
            policy_edge_manifests=manifests,
        )
    )
    match = compiled.can_access(
        principal_ref="role:warehouse_operator",
        operation="PICK",
        resource_ref="resource:asset-42",
        zone_ref="zone:cold-room",
    )

    assert match.allowed is False
    assert match.reason == "explicit_deny"
    assert len(match.deny_permissions) == 1


def test_compiler_requires_break_glass_when_only_bypass_permission_exists() -> None:
    manifests = [
        PolicyEdgeManifest(
            source_selector="role:warehouse_operator",
            target_selector="resource:asset-42",
            relationship="can_bypass",
            operation="PICK",
            conditions={
                "zones": ["cold-room"],
                "requires_break_glass": True,
                "bypass_deny": True,
            },
            rule_id="bg-1",
            rule_name="warehouse_pick_break_glass",
        )
    ]

    compiled = AuthzGraphCompiler().compile(
        AuthzGraphProjector().project_snapshot(
            snapshot_ref="pkg-authz@test",
            snapshot_version="rules@2.1.0",
            policy_edge_manifests=manifests,
        )
    )
    denied = compiled.can_access(
        principal_ref="role:warehouse_operator",
        operation="PICK",
        resource_ref="resource:asset-42",
        zone_ref="zone:cold-room",
    )
    allowed = compiled.can_access(
        principal_ref="role:warehouse_operator",
        operation="PICK",
        resource_ref="resource:asset-42",
        zone_ref="zone:cold-room",
        break_glass=True,
    )

    assert denied.allowed is False
    assert denied.reason == "break_glass_required"
    assert denied.break_glass_required is True
    assert allowed.allowed is True
    assert allowed.reason == "matched_break_glass_permission"


def test_compiler_break_glass_bypass_overrides_explicit_deny() -> None:
    manifests = [
        PolicyEdgeManifest(
            source_selector="role:warehouse_operator",
            target_selector="resource:asset-42",
            operation="PICK",
            effect=PermissionEffect.DENY,
            conditions={"zones": ["cold-room"]},
            rule_id="deny-1",
            rule_name="warehouse_pick_deny",
        ),
        PolicyEdgeManifest(
            source_selector="role:warehouse_operator",
            target_selector="resource:asset-42",
            relationship="can_bypass",
            operation="PICK",
            conditions={
                "zones": ["cold-room"],
                "requires_break_glass": True,
                "bypass_deny": True,
            },
            rule_id="bg-1",
            rule_name="warehouse_pick_break_glass",
        ),
    ]

    compiled = AuthzGraphCompiler().compile(
        AuthzGraphProjector().project_snapshot(
            snapshot_ref="pkg-authz@test",
            snapshot_version="rules@2.1.0",
            policy_edge_manifests=manifests,
        )
    )
    match = compiled.can_access(
        principal_ref="role:warehouse_operator",
        operation="PICK",
        resource_ref="resource:asset-42",
        zone_ref="zone:cold-room",
        break_glass=True,
    )

    assert match.allowed is True
    assert match.reason == "break_glass_override"
    assert match.break_glass_used is True


def test_transition_evaluation_quarantines_when_trust_gap_exists() -> None:
    now = datetime.now(timezone.utc)
    facts = [
        Fact(
            id=uuid4(),
            text="role",
            snapshot_id=12,
            namespace="authz",
            subject="driver-7",
            predicate="hasRole",
            object_data={"role": "carrier"},
            valid_from=now - timedelta(hours=1),
            valid_to=now + timedelta(hours=1),
            created_by="test",
        ),
        Fact(
            id=uuid4(),
            text="move asset",
            snapshot_id=12,
            namespace="authz",
            subject="role:carrier",
            predicate="allowedOperation",
            object_data={
                "operation": "MOVE",
                "resource": "asset-88",
                "required_current_custodian": True,
                "required_transferable_state": True,
                "max_telemetry_age_seconds": 300,
                "require_attestation": True,
                "require_seal": True,
                "allow_quarantine": True,
            },
            valid_from=now - timedelta(hours=1),
            valid_to=now + timedelta(hours=1),
            created_by="test",
        ),
        Fact(
            id=uuid4(),
            text="custody",
            snapshot_id=12,
            namespace="authz",
            subject="asset-88",
            predicate="heldBy",
            object_data={
                "custodian": "driver-7",
                "transferable": True,
                "custody_point": "vault-a",
            },
            valid_from=now - timedelta(minutes=10),
            valid_to=now + timedelta(minutes=10),
            created_by="test",
        ),
        Fact(
            id=uuid4(),
            text="attestation",
            snapshot_id=12,
            namespace="authz",
            subject="asset-88",
            predicate="attestedBy",
            object_data={
                "attestation_id": "lab-cert-88",
                "attestor": "lab-1",
                "valid_from": _iso(now - timedelta(days=1)),
                "valid_to": _iso(now + timedelta(days=1)),
            },
            created_by="test",
        ),
        Fact(
            id=uuid4(),
            text="seal",
            snapshot_id=12,
            namespace="authz",
            subject="asset-88",
            predicate="sealedWith",
            object_data={"seal_id": "seal-88"},
            created_by="test",
        ),
        Fact(
            id=uuid4(),
            text="stale telemetry",
            snapshot_id=12,
            namespace="authz",
            subject="asset-88",
            predicate="observedIn",
            object_data={
                "observation_id": "obs-old-88",
                "measurement_type": "temperature",
                "quality_score": 0.92,
                "observed_at": _iso(now - timedelta(minutes=20)),
            },
            created_by="test",
        ),
    ]

    compiled = AuthzGraphCompiler().compile(
        AuthzGraphProjector().project_snapshot(
            snapshot_ref="pkg-authz@phase1",
            snapshot_id=12,
            snapshot_version="rules@12.0.0",
            facts=facts,
        )
    )
    evaluation = compiled.evaluate_transition(
        AuthzTransitionRequest(
            principal_ref="principal:driver-7",
            operation="MOVE",
            resource_ref="resource:asset-88",
            asset_ref="asset:asset-88",
            custody_point_ref="custody_point:vault-a",
            at=now,
        )
    )

    assert evaluation.disposition == AuthzDecisionDisposition.QUARANTINE
    assert evaluation.quarantined is True
    assert evaluation.restricted_token_recommended is True
    assert any(gap.code == "stale_telemetry" for gap in evaluation.trust_gaps)
    assert evaluation.receipt.disposition == AuthzDecisionDisposition.QUARANTINE
    assert evaluation.receipt.decision_hash


def test_transition_evaluation_allows_when_lineage_and_evidence_are_intact() -> None:
    now = datetime.now(timezone.utc)
    facts = [
        Fact(
            id=uuid4(),
            text="role",
            snapshot_id=13,
            namespace="authz",
            subject="driver-9",
            predicate="hasRole",
            object_data={"role": "carrier"},
            valid_from=now - timedelta(hours=1),
            valid_to=now + timedelta(hours=1),
            created_by="test",
        ),
        Fact(
            id=uuid4(),
            text="move asset",
            snapshot_id=13,
            namespace="authz",
            subject="role:carrier",
            predicate="allowedOperation",
            object_data={
                "operation": "MOVE",
                "resource": "asset-99",
                "required_current_custodian": True,
                "required_transferable_state": True,
                "max_telemetry_age_seconds": 300,
                "max_inspection_age_seconds": 86400,
                "require_attestation": True,
                "require_seal": True,
            },
            valid_from=now - timedelta(hours=1),
            valid_to=now + timedelta(hours=1),
            created_by="test",
        ),
        Fact(
            id=uuid4(),
            text="custody",
            snapshot_id=13,
            namespace="authz",
            subject="asset-99",
            predicate="heldBy",
            object_data={
                "custodian": "driver-9",
                "transferable": True,
                "custody_point": "warehouse-b",
                "batch_twin_id": "batch-99",
            },
            valid_from=now - timedelta(minutes=5),
            valid_to=now + timedelta(minutes=20),
            created_by="test",
        ),
        Fact(
            id=uuid4(),
            text="lineage",
            snapshot_id=13,
            namespace="authz",
            subject="asset-99",
            predicate="transferredFrom",
            object_data={"custodian": "harvester-11"},
            created_by="test",
        ),
        Fact(
            id=uuid4(),
            text="attestation",
            snapshot_id=13,
            namespace="authz",
            subject="asset-99",
            predicate="attestedBy",
            object_data={
                "attestation_id": "lab-cert-99",
                "attestor": "lab-2",
                "valid_from": _iso(now - timedelta(hours=12)),
                "valid_to": _iso(now + timedelta(days=3)),
            },
            created_by="test",
        ),
        Fact(
            id=uuid4(),
            text="telemetry",
            snapshot_id=13,
            namespace="authz",
            subject="asset-99",
            predicate="observedIn",
            object_data={
                "observation_id": "obs-99",
                "measurement_type": "temperature",
                "quality_score": 0.98,
                "observed_at": _iso(now - timedelta(minutes=1)),
                "custody_point": "warehouse-b",
            },
            created_by="test",
        ),
        Fact(
            id=uuid4(),
            text="seal",
            snapshot_id=13,
            namespace="authz",
            subject="asset-99",
            predicate="sealedWith",
            object_data={"nfc_uid": "nfc-99"},
            created_by="test",
        ),
    ]

    compiled = AuthzGraphCompiler().compile(
        AuthzGraphProjector().project_snapshot(
            snapshot_ref="pkg-authz@phase1",
            snapshot_id=13,
            snapshot_version="rules@13.0.0",
            facts=facts,
        )
    )
    evaluation = compiled.evaluate_transition(
        AuthzTransitionRequest(
            principal_ref="principal:driver-9",
            operation="MOVE",
            resource_ref="resource:asset-99",
            asset_ref="asset:asset-99",
            custody_point_ref="custody_point:warehouse-b",
            at=now,
        )
    )

    assert evaluation.disposition == AuthzDecisionDisposition.ALLOW
    assert evaluation.allowed is True
    assert evaluation.current_custodian == "principal:driver-9"
    assert ("principal:driver-9", "role:carrier") in evaluation.permission_match.authority_paths
    assert any(check.code == "current_custodian" and check.outcome == "passed" for check in evaluation.checked_constraints)
    assert any(check.code == "telemetry_freshness" and check.outcome == "passed" for check in evaluation.checked_constraints)
    assert evaluation.receipt.disposition == AuthzDecisionDisposition.ALLOW
    assert "attestation:lab-cert-99" in evaluation.receipt.evidence_refs
    assert any(item.startswith("current_custodian:principal:driver-9") for item in evaluation.receipt.custody_proof)
