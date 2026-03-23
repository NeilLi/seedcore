from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies  # noqa: F401
import mock_eventizer_dependencies  # noqa: F401

import seedcore.coordinator.core.governance as governance_mod
from seedcore.ops.pkg.authz_graph import AuthzGraphCompiler, AuthzGraphProjector
from seedcore.ops.pkg.authz_parity_service import AuthzParityFixture, AuthzParityService


def _build_compiled_index():
    canonical_resource_uri = "seedcore://zones/vault-a/assets/asset-1"
    graph = AuthzGraphProjector().project_snapshot(
        snapshot_ref="authz-parity@test",
        snapshot_version="snapshot:1",
        facts=[
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
                "subject": canonical_resource_uri,
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
                    "resource": canonical_resource_uri,
                    "zones": ["vault-a"],
                },
                "valid_from": "2099-03-20T11:50:00+00:00",
                "valid_to": "2099-03-20T12:20:00+00:00",
            },
        ],
    )
    return AuthzGraphCompiler().compile(graph)


def _load_fixture_matrix() -> list[AuthzParityFixture]:
    raw = json.loads(
        Path("tests/fixtures/authz_parity/basic_matrix.json").read_text()
    )
    return [AuthzParityFixture(name=item["name"], payload=item["payload"], metadata=item.get("metadata") or {}) for item in raw]


def test_authz_parity_service_reports_parity_for_shared_behaviors(monkeypatch) -> None:
    compiled = _build_compiled_index()
    fixtures = _load_fixture_matrix()
    stale_now = datetime(2099, 3, 20, 12, 0, 1, tzinfo=timezone.utc)

    monkeypatch.setenv("SEEDCORE_PDP_MAX_INTENT_AGE_MS", "500")
    monkeypatch.setattr(governance_mod, "_utcnow", lambda: stale_now)

    service = AuthzParityService()
    report = service.compare_fixtures(
        compiled_authz_index=compiled,
        fixtures=fixtures,
    )

    assert report.snapshot_version == "snapshot:1"
    assert report.total == 2
    assert report.parity_ok == 2
    assert report.mismatched == 0
    assert all(result.parity_ok for result in report.results)
    assert report.results[1].baseline.deny_code == "stale_intent"
    assert report.results[1].candidate.deny_code == "stale_intent"


def test_authz_parity_service_flags_engine_mismatch() -> None:
    payload = {
        "task_id": "task-parity-mismatch",
        "type": "action",
        "params": {
            "interaction": {"assigned_agent_id": "agent-1"},
            "resource": {"asset_id": "asset-1"},
            "intent": "transport",
            "governance": {
                "action_intent": {
                    "intent_id": "intent-parity-mismatch",
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
    graph = AuthzGraphProjector().project_snapshot(
        snapshot_ref="authz-parity@test",
        snapshot_version="snapshot:1",
        policy_edge_manifests=[
            {
                "source_selector": "role:ROBOT_OPERATOR",
                "target_selector": "seedcore://zones/vault-a/assets/asset-1",
                "operation": "MUTATE",
                "effect": "deny",
                "conditions": {"zones": ["vault-a"]},
                "rule_id": "deny-1",
                "rule_name": "deny_vault_mutation",
            }
        ],
        facts=[
            {
                "id": "fact-role",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "agent-1",
                "predicate": "hasRole",
                "object_data": {"role": "ROBOT_OPERATOR"},
            }
        ],
    )
    compiled = AuthzGraphCompiler().compile(graph)
    service = AuthzParityService()

    report = service.compare_fixtures(
        compiled_authz_index=compiled,
        fixtures=[AuthzParityFixture(name="explicit_deny_mismatch", payload=payload)],
    )

    assert report.total == 1
    assert report.parity_ok == 0
    assert report.mismatched == 1
    assert report.results[0].parity_ok is False
    assert "allowed" in report.results[0].mismatches
    assert "deny_code" in report.results[0].mismatches


@pytest.mark.asyncio
async def test_compare_snapshot_uses_projection_service() -> None:
    compiled = _build_compiled_index()
    fixtures = _load_fixture_matrix()[:1]

    class StubProjectionService:
        async def build_compiled_index(self, **kwargs):
            return compiled, {"kwargs": kwargs}

    service = AuthzParityService(projection_service=StubProjectionService())
    report = await service.compare_snapshot(
        snapshot_ref="authz-parity@test",
        snapshot_version="snapshot:1",
        fixtures=fixtures,
    )

    assert report.total == 1
    assert report.parity_ok == 1
