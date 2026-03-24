from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from seedcore.models.action_intent import ActionIntent
from seedcore.ops.pkg.authz_graph import AuthzGraphProjectionService


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


class _FakeSnapshot:
    def __init__(self, snapshot_id: int, version: str, graph_manifests: list[dict] | None = None) -> None:
        self.id = snapshot_id
        self.version = version
        self.graph_manifests = list(graph_manifests or [])


class _FakePKGClient:
    def __init__(
        self,
        facts: list[dict],
        snapshot_id: int = 9,
        version: str = "rules@9.0.0",
        graph_manifests: list[dict] | None = None,
    ) -> None:
        self._facts = facts
        self._snapshot = _FakeSnapshot(snapshot_id, version, graph_manifests=graph_manifests)

    async def get_active_governed_facts(self, **kwargs):
        snapshot_id = kwargs.get("snapshot_id")
        if snapshot_id != self._snapshot.id:
            return []
        return list(self._facts)

    async def get_snapshot_by_version(self, version: str):
        if version != self._snapshot.version:
            return None
        return self._snapshot

    async def get_snapshot_by_id(self, snapshot_id: int):
        if snapshot_id != self._snapshot.id:
            return None
        return self._snapshot


def _build_intent() -> ActionIntent:
    now = datetime.now(timezone.utc)
    return ActionIntent(
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
            "parameters": {},
            "security_contract": {"hash": "abc123", "version": "rules@9.0.0"},
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


@pytest.mark.asyncio
async def test_projection_service_builds_snapshot_from_snapshot_scoped_sources() -> None:
    snapshot_id = 9
    facts = [
        {
            "id": str(uuid4()),
            "snapshot_id": snapshot_id,
            "namespace": "authz",
            "subject": "agent-alpha",
            "predicate": "hasRole",
            "object_data": {"role": "warehouse_operator"},
            "valid_from": _iso(datetime.now(timezone.utc) - timedelta(minutes=5)),
            "valid_to": _iso(datetime.now(timezone.utc) + timedelta(minutes=5)),
        },
        {
            "id": str(uuid4()),
            "snapshot_id": snapshot_id,
            "namespace": "authz",
            "subject": "role:warehouse_operator",
            "predicate": "allowedOperation",
            "object_data": {
                "operation": "PICK",
                "resource": "asset-42",
                "zones": ["cold-room"],
                "networks": ["plant-a"],
            },
            "valid_from": _iso(datetime.now(timezone.utc) - timedelta(minutes=5)),
            "valid_to": _iso(datetime.now(timezone.utc) + timedelta(minutes=5)),
        },
    ]
    registrations = [
        {
            "id": str(uuid4()),
            "snapshot_id": snapshot_id,
            "lot_id": "lot-2026-01",
            "producer_id": "producer-7",
            "status": "approved",
        }
    ]
    tracking_events = [
        {
            "id": str(uuid4()),
            "snapshot_id": snapshot_id,
            "registration_id": registrations[0]["id"],
            "producer_id": "producer-7",
        }
    ]

    async def _load_registrations(*, snapshot_id: int):
        return list(registrations) if snapshot_id == 9 else []

    async def _load_tracking_events(*, snapshot_id: int):
        return list(tracking_events) if snapshot_id == 9 else []

    service = AuthzGraphProjectionService(
        pkg_client=_FakePKGClient(facts=facts, snapshot_id=snapshot_id),
        facts_loader=None,
        registrations_loader=_load_registrations,
        tracking_events_loader=_load_tracking_events,
    )

    result = await service.build_snapshot(
        snapshot_ref="pkg-authz@phase2",
        snapshot_id=snapshot_id,
        snapshot_version="rules@9.0.0",
        action_intents=[_build_intent()],
    )

    assert result.stats["facts_count"] == 2
    assert result.stats["registrations_count"] == 1
    assert result.stats["tracking_events_count"] == 1
    assert result.stats["action_intents_count"] == 1
    assert result.snapshot.snapshot_id == snapshot_id
    assert any(node.ref == "principal:agent-alpha" for node in result.snapshot.nodes)
    assert any(edge.src == "role:warehouse_operator" and edge.dst == "resource:asset-42" for edge in result.snapshot.edges)
    assert all(node.kind != "tracking_event" for node in result.snapshot.nodes)
    assert any(node.kind.value == "tracking_event" for node in result.enrichment_snapshot.nodes)
    assert result.stats["decision_graph_nodes_count"] == len(result.snapshot.nodes)
    assert result.stats["enrichment_graph_nodes_count"] == len(result.enrichment_snapshot.nodes)


@pytest.mark.asyncio
async def test_projection_service_resolves_snapshot_version_and_compiles_index() -> None:
    snapshot_id = 9
    facts = [
        {
            "id": str(uuid4()),
            "snapshot_id": snapshot_id,
            "namespace": "authz",
            "subject": "agent-alpha",
            "predicate": "hasRole",
            "object_data": {"role": "warehouse_operator"},
            "valid_from": _iso(datetime.now(timezone.utc) - timedelta(minutes=5)),
            "valid_to": _iso(datetime.now(timezone.utc) + timedelta(minutes=5)),
        },
        {
            "id": str(uuid4()),
            "snapshot_id": snapshot_id,
            "namespace": "authz",
            "subject": "role:warehouse_operator",
            "predicate": "allowedOperation",
            "object_data": {
                "operation": "PICK",
                "resource": "asset-42",
                "zones": ["cold-room"],
                "networks": ["plant-a"],
            },
            "valid_from": _iso(datetime.now(timezone.utc) - timedelta(minutes=5)),
            "valid_to": _iso(datetime.now(timezone.utc) + timedelta(minutes=5)),
        },
        {
            "id": str(uuid4()),
            "snapshot_id": snapshot_id,
            "namespace": "authz",
            "subject": "asset-42",
            "predicate": "locatedInZone",
            "object_data": {"zone": "cold-room"},
        },
    ]
    service = AuthzGraphProjectionService(
        pkg_client=_FakePKGClient(facts=facts, snapshot_id=snapshot_id, version="rules@9.0.0"),
        registrations_loader=lambda **kwargs: _empty_async_list(),
        tracking_events_loader=lambda **kwargs: _empty_async_list(),
    )

    compiled, result = await service.build_compiled_index(
        snapshot_ref="pkg-authz@phase2",
        snapshot_version="rules@9.0.0",
    )
    match = compiled.can_access(
        principal_ref="principal:agent-alpha",
        operation="PICK",
        resource_ref="resource:asset-42",
        zone_ref="zone:cold-room",
        network_ref="network:plant-a",
    )

    assert result.snapshot.snapshot_version == "rules@9.0.0"
    assert compiled.snapshot_id == snapshot_id
    assert match.allowed is True


@pytest.mark.asyncio
async def test_projection_service_rebuilds_snapshot_deterministically() -> None:
    snapshot_id = 9
    facts = [
        {
            "id": "fact-role",
            "snapshot_id": snapshot_id,
            "namespace": "authz",
            "subject": "agent-alpha",
            "predicate": "hasRole",
            "object_data": {"role": "warehouse_operator"},
            "valid_from": _iso(datetime.now(timezone.utc) - timedelta(minutes=5)),
            "valid_to": _iso(datetime.now(timezone.utc) + timedelta(minutes=5)),
        },
        {
            "id": "fact-allow",
            "snapshot_id": snapshot_id,
            "namespace": "authz",
            "subject": "role:warehouse_operator",
            "predicate": "allowedOperation",
            "object_data": {
                "operation": "PICK",
                "resource": "asset-42",
                "zones": ["cold-room"],
                "networks": ["plant-a"],
            },
            "valid_from": _iso(datetime.now(timezone.utc) - timedelta(minutes=5)),
            "valid_to": _iso(datetime.now(timezone.utc) + timedelta(minutes=5)),
        },
        {
            "id": "fact-zone",
            "snapshot_id": snapshot_id,
            "namespace": "authz",
            "subject": "asset-42",
            "predicate": "locatedInZone",
            "object_data": {"zone": "cold-room"},
        },
    ]

    service = AuthzGraphProjectionService(
        pkg_client=_FakePKGClient(facts=facts, snapshot_id=snapshot_id, version="rules@9.0.0"),
        registrations_loader=lambda **kwargs: _empty_async_list(),
        tracking_events_loader=lambda **kwargs: _empty_async_list(),
    )

    first = await service.build_compiled_index(
        snapshot_ref="pkg-authz@phase0",
        snapshot_version="rules@9.0.0",
    )
    second = await service.build_compiled_index(
        snapshot_ref="pkg-authz@phase0",
        snapshot_version="rules@9.0.0",
    )
    first_compiled, first_result = first
    second_compiled, second_result = second

    first_nodes = sorted(
        (node.kind.value, node.ref, node.display_name, tuple(sorted(node.attributes.items())))
        for node in first_result.snapshot.nodes
    )
    second_nodes = sorted(
        (node.kind.value, node.ref, node.display_name, tuple(sorted(node.attributes.items())))
        for node in second_result.snapshot.nodes
    )
    first_edges = sorted(
        (
            edge.kind.value,
            edge.src,
            edge.dst,
            edge.operation,
            edge.effect.value,
            tuple(sorted(edge.constraints.items())),
        )
        for edge in first_result.snapshot.edges
    )
    second_edges = sorted(
        (
            edge.kind.value,
            edge.src,
            edge.dst,
            edge.operation,
            edge.effect.value,
            tuple(sorted(edge.constraints.items())),
        )
        for edge in second_result.snapshot.edges
    )

    assert first_nodes == second_nodes
    assert first_edges == second_edges
    assert first_result.stats["graph_nodes_count"] == second_result.stats["graph_nodes_count"]
    assert first_result.stats["graph_edges_count"] == second_result.stats["graph_edges_count"]
    assert first_compiled.permissions_by_subject == second_compiled.permissions_by_subject


@pytest.mark.asyncio
async def test_projection_service_splits_decision_and_enrichment_graphs() -> None:
    snapshot_id = 11
    facts = [
        {
            "id": "fact-role",
            "snapshot_id": snapshot_id,
            "namespace": "authz",
            "subject": "agent-alpha",
            "predicate": "hasRole",
            "object_data": {"role": "warehouse_operator"},
        },
        {
            "id": "fact-allow",
            "snapshot_id": snapshot_id,
            "namespace": "authz",
            "subject": "role:warehouse_operator",
            "predicate": "allowedOperation",
            "object_data": {"operation": "PICK", "resource": "asset-42"},
        },
    ]
    tracking_events = [
        {
            "id": "track-1",
            "snapshot_id": snapshot_id,
            "registration_id": "reg-1",
            "producer_id": "producer-1",
            "subject_id": "asset-42",
            "subject_type": "asset",
        }
    ]

    async def _load_tracking_events(*, snapshot_id: int):
        return list(tracking_events) if snapshot_id == 11 else []

    service = AuthzGraphProjectionService(
        pkg_client=_FakePKGClient(facts=facts, snapshot_id=snapshot_id, version="rules@11.0.0"),
        registrations_loader=lambda **kwargs: _empty_async_list(),
        tracking_events_loader=_load_tracking_events,
    )

    compiled, result = await service.build_compiled_index(
        snapshot_ref="pkg-authz@phase4",
        snapshot_version="rules@11.0.0",
    )

    assert compiled.snapshot_version == "rules@11.0.0"
    assert all(node.kind.value != "tracking_event" for node in result.snapshot.nodes)
    assert any(node.kind.value == "tracking_event" for node in result.enrichment_snapshot.nodes)
    assert result.stats["combined_graph_nodes_count"] >= result.stats["decision_graph_nodes_count"]
    assert result.stats["combined_graph_nodes_count"] >= result.stats["enrichment_graph_nodes_count"]


@pytest.mark.asyncio
async def test_projection_service_projects_snapshot_graph_manifests() -> None:
    snapshot_id = 9
    graph_manifests = [
        {
            "source_selector": "role:warehouse_operator",
            "target_selector": "resource:asset-42",
            "relationship": "can",
            "operation": "PICK",
            "conditions": {"zones": ["cold-room"], "networks": ["plant-a"]},
            "rule_id": "rule-authz-1",
            "rule_name": "warehouse_pick_allow",
        }
    ]
    service = AuthzGraphProjectionService(
        pkg_client=_FakePKGClient(
            facts=[],
            snapshot_id=snapshot_id,
            version="rules@9.0.0",
            graph_manifests=graph_manifests,
        ),
        registrations_loader=lambda **kwargs: _empty_async_list(),
        tracking_events_loader=lambda **kwargs: _empty_async_list(),
    )

    compiled, result = await service.build_compiled_index(
        snapshot_ref="pkg-authz@phase2",
        snapshot_id=snapshot_id,
    )
    match = compiled.can_access(
        principal_ref="role:warehouse_operator",
        operation="PICK",
        resource_ref="resource:asset-42",
        zone_ref="zone:cold-room",
        network_ref="network:plant-a",
    )

    assert result.stats["graph_manifests_count"] == 1
    assert match.allowed is True


async def _empty_async_list():
    return []
