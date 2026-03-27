from __future__ import annotations

import os
import sys
import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401
import mock_eventizer_dependencies  # noqa: F401

from seedcore.coordinator.core.governance import evaluate_intent
from seedcore.ops.pkg.authz_graph import AuthzGraphManager, AuthzGraphProjectionService
from seedcore.ops.pkg.authz_graph.ray_cache import _authz_graph_cache_actor_name, _payload_shard_key
import seedcore.ops.pkg.manager as pkg_manager_mod
from seedcore.ops.pkg.manager import PKGManager
from seedcore.ops.pkg.dao import PKGSnapshotData


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _base_payload() -> dict:
    return {
        "task_id": "task-1",
        "type": "action",
        "params": {
            "interaction": {"assigned_agent_id": "agent-1"},
            "resource": {"asset_id": "asset-1"},
            "intent": "transport",
            "governance": {
                "action_intent": {
                    "intent_id": "intent-1",
                    "timestamp": "2099-03-20T12:00:00+00:00",
                    "valid_until": "2099-03-20T12:10:00+00:00",
                    "principal": {
                        "agent_id": "agent-1",
                        "role_profile": "ROBOT_OPERATOR",
                        "session_token": "sess-1",
                    },
                    "action": {
                        "type": "MOVE",
                        "parameters": {},
                        "security_contract": {"hash": "h-1", "version": "snapshot:1"},
                    },
                    "resource": {
                        "asset_id": "asset-1",
                        "resource_uri": "seedcore://zones/vault-a/assets/asset-1",
                        "target_zone": "vault-a",
                        "provenance_hash": "prov-1",
                    },
                }
            },
        },
    }


def _compiled_service() -> AuthzGraphProjectionService:
    facts = [
        {
            "id": "fact-role",
            "snapshot_id": 1,
            "namespace": "authz",
            "subject": "agent-1",
            "predicate": "hasRole",
            "object_data": {"role": "ROBOT_OPERATOR"},
            "valid_from": "2099-03-20T11:50:00+00:00",
            "valid_to": "2099-03-20T12:20:00+00:00",
        },
        {
            "id": "fact-zone",
            "snapshot_id": 1,
            "namespace": "authz",
            "subject": "seedcore://zones/vault-a/assets/asset-1",
            "predicate": "locatedInZone",
            "object_data": {"zone": "vault-a"},
        },
        {
            "id": "fact-allow",
            "snapshot_id": 1,
            "namespace": "authz",
            "subject": "role:ROBOT_OPERATOR",
            "predicate": "allowedOperation",
            "object_data": {
                "operation": "MUTATE",
                "resource": "seedcore://zones/vault-a/assets/asset-1",
                "zones": ["vault-a"],
            },
            "valid_from": "2099-03-20T11:50:00+00:00",
            "valid_to": "2099-03-20T12:20:00+00:00",
        },
    ]

    class FakePKGClient:
        async def get_active_governed_facts(self, **kwargs):
            return list(facts)

    async def _empty(**kwargs):
        return []

    return AuthzGraphProjectionService(
        pkg_client=FakePKGClient(),
        registrations_loader=_empty,
        tracking_events_loader=_empty,
    )


@pytest.mark.asyncio
async def test_authz_graph_manager_activates_compiled_snapshot() -> None:
    manager = AuthzGraphManager(_compiled_service())

    compiled = await manager.activate_snapshot(
        snapshot_id=1,
        snapshot_version="snapshot:1",
        snapshot_ref="authz_graph@snapshot:1",
    )
    status = manager.get_status()

    assert compiled.snapshot_version == "snapshot:1"
    assert status["healthy"] is True
    assert status["active_snapshot_version"] == "snapshot:1"
    assert status["snapshot_hash"] == compiled.snapshot_hash
    assert status["restricted_transfer_ready"] is False
    assert status["graph_edges_count"] > 0
    assert "enrichment_graph_nodes_count" in status


@pytest.mark.asyncio
async def test_pkg_manager_metadata_exposes_authz_graph_status() -> None:
    rules = [{"id": "r1", "priority": 1}]
    checksum = hashlib.sha256(
        json.dumps(rules, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    mock_pkg_client = AsyncMock()
    mock_pkg_client.get_active_snapshot.return_value = PKGSnapshotData(
        id=1,
        version="snapshot:1",
        engine="native",
        wasm_artifact=None,
        checksum=checksum,
        rules=rules,
    )
    mock_pkg_client._sf = None
    mock_pkg_client.get_active_governed_facts = AsyncMock(return_value=[])
    mock_pkg_client.get_subtask_types = AsyncMock(return_value=[])

    authz_graph_manager = AuthzGraphManager(_compiled_service())
    pkg_manager = PKGManager(mock_pkg_client, redis_client=None, authz_graph_manager=authz_graph_manager)

    await pkg_manager.start()
    metadata = pkg_manager.get_metadata()

    assert "authz_graph" in metadata
    assert metadata["authz_graph"]["active_snapshot_version"] == "snapshot:1"
    assert metadata["authz_graph"]["snapshot_hash"] is not None
    assert pkg_manager.get_active_compiled_authz_index() is not None


def test_evaluate_intent_uses_global_active_authz_graph_when_enabled(monkeypatch) -> None:
    manager = AuthzGraphManager(_compiled_service())
    asyncio.run(
        manager.activate_snapshot(
            snapshot_id=1,
            snapshot_version="snapshot:1",
            snapshot_ref="authz_graph@snapshot:1",
        )
    )
    monkeypatch.setenv("SEEDCORE_PDP_USE_ACTIVE_AUTHZ_GRAPH", "true")
    monkeypatch.setattr(
        pkg_manager_mod,
        "get_global_pkg_manager",
        lambda: type(
            "_ManagerStub",
            (),
            {"get_active_compiled_authz_index": lambda self: manager.get_active_compiled_index()},
        )(),
    )

    decision = evaluate_intent(_base_payload())

    assert decision.allowed is True
    assert decision.execution_token is not None


def test_ray_cache_uses_shard_scoped_actor_names() -> None:
    assert _authz_graph_cache_actor_name("facility:vault-hub").endswith("__facility_vault_hub")
    assert _authz_graph_cache_actor_name("global").endswith("seedcore_authz_graph_cache")
    assert _payload_shard_key({"facility_ref": "facility:vault-hub"}) == "facility:vault-hub"
    assert _payload_shard_key({"zone_ref": "zone:vault-a"}) == "zone:vault-a"
