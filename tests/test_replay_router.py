from __future__ import annotations

import os
import sys
import importlib
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

from fastapi import FastAPI
from fastapi.testclient import TestClient

import seedcore.api.routers.replay_router as replay_router_module
from seedcore.services.replay_service import ReplayService

sys.modules.pop("seedcore.api.routers.tasks_router", None)
tasks_router_module = importlib.import_module("seedcore.api.routers.tasks_router")

from test_replay_service import _DummySession, _apply_transition_metadata, _build_audit_record


class _FakeRedis:
    def __init__(self) -> None:
        self._values: Dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        return self._values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._values[key] = {"value": value, "ex": ex}
        return True

    async def aclose(self) -> None:
        return None


class _TaskGovernanceSession(_DummySession):
    def __init__(self, task: Any) -> None:
        self._task = task

    async def get(self, model, key):
        return self._task if getattr(self._task, "id", None) == key else None


def _build_service(record: Dict[str, Any]) -> ReplayService:
    return ReplayService(
        governance_audit_dao=type(
            "DAO",
            (),
            {
                "get_by_entry_id": AsyncMock(return_value=record),
                "get_latest_for_intent": AsyncMock(return_value=record),
                "get_latest_for_task": AsyncMock(return_value=record),
            },
        )(),
        digital_twin_dao=type("TwinDAO", (), {"list_history": AsyncMock(return_value=[])})(),
        asset_custody_dao=type("AssetDAO", (), {"get_snapshot": AsyncMock(return_value={"asset_id": "asset-1", "current_zone": "vault-a"})})(),
    )


def _make_client(
    record: Dict[str, Any],
    redis_client: _FakeRedis | None = None,
    *,
    session: Any | None = None,
    governance_entries: list[Dict[str, Any]] | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(replay_router_module.router)
    app.include_router(tasks_router_module.router)

    session = session or _DummySession()

    async def override_replay_session():
        return session

    async def override_tasks_session():
        return session

    app.dependency_overrides[replay_router_module.get_async_pg_session] = override_replay_session
    app.dependency_overrides[tasks_router_module.get_async_pg_session] = override_tasks_session

    replay_router_module.replay_service = _build_service(record)
    tasks_router_module.replay_service = replay_router_module.replay_service
    tasks_router_module.governance_audit_dao = SimpleNamespace(
        list_for_task=AsyncMock(return_value=list(governance_entries or [record]))
    )

    async def fake_get_async_redis_client():
        return redis_client

    replay_router_module.get_async_redis_client = fake_get_async_redis_client
    return TestClient(app)


def test_publish_trust_reference_and_fetch_projection_and_verify() -> None:
    record = _build_audit_record(task_id="task-router-1", intent_id="intent-router-1", asset_id="asset-1")
    client = _make_client(record)

    publish = client.post("/trust/publish", json={"audit_id": record["id"], "ttl_hours": 4})
    assert publish.status_code == 200
    public_id = publish.json()["public_id"]

    trust = client.get(f"/trust/{public_id}")
    assert trust.status_code == 200
    assert trust.json()["subject_title"] == "Asset asset-1"
    assert trust.json()["public_jsonld_ref"].endswith(f"/trust/{public_id}/jsonld")

    verify = client.get(f"/verify/{public_id}")
    assert verify.status_code == 200
    assert verify.json()["verified"] is True
    assert verify.json()["trust_url"].endswith(f"/trust/{public_id}")


def test_revoke_trust_reference_returns_gone_for_trust_surface() -> None:
    record = _build_audit_record(task_id="task-router-2", intent_id="intent-router-2", asset_id="asset-1")
    redis_client = _FakeRedis()
    client = _make_client(record, redis_client=redis_client)

    publish = client.post("/trust/publish", json={"audit_id": record["id"], "ttl_hours": 4})
    public_id = publish.json()["public_id"]

    revoke = client.post("/trust/revoke", json={"public_id": public_id})
    assert revoke.status_code == 200
    assert revoke.json()["revoked"] is True

    trust = client.get(f"/trust/{public_id}")
    assert trust.status_code == 410

    verify = client.get(f"/verify/{public_id}")
    assert verify.status_code == 200
    assert verify.json()["verified"] is False
    assert verify.json()["reason"] == "revoked_reference"


def test_verify_post_requires_exactly_one_lookup() -> None:
    record = _build_audit_record(task_id="task-router-3", intent_id="intent-router-3", asset_id="asset-1")
    client = _make_client(record)

    response = client.post("/verify", json={"audit_id": record["id"], "subject_id": "asset-1"})

    assert response.status_code == 422
    assert "exactly one" in response.json()["detail"]


def test_materialized_custody_event_endpoint_uses_replay_service_jsonld() -> None:
    record = _apply_transition_metadata(
        _build_audit_record(task_id="task-router-4", intent_id="intent-router-4", asset_id="asset-1")
    )
    client = _make_client(record)

    response = client.get("/governance/materialized-custody-event", params={"audit_id": record["id"]})

    assert response.status_code == 200
    body = response.json()
    assert body["retrieval_key"] == "audit_id"
    assert body["audit_record"]["id"] == record["id"]
    assert body["custody_event_jsonld"]["@type"] == "seedcore:SeedCoreCustodyEvent"
    assert body["custody_event_jsonld"]["proof"]["type"] == "SeedCoreReplayProof"
    assert body["custody_event_jsonld"]["policy_verification"]["authz_disposition"] == "quarantine"
    assert body["custody_event_jsonld"]["policy_verification"]["governed_receipt_hash"] == "receipt-intent-router-4"
    assert body["custody_event_jsonld"]["policy_verification"]["trust_gap_codes"] == ["stale_telemetry"]


def test_replay_artifacts_include_authz_transition_metadata() -> None:
    record = _apply_transition_metadata(
        _build_audit_record(task_id="task-router-5", intent_id="intent-router-5", asset_id="asset-1")
    )
    client = _make_client(record)

    response = client.get("/replay/artifacts", params={"audit_id": record["id"], "projection": "internal"})

    assert response.status_code == 200
    body = response.json()
    assert body["authz_graph"]["reason"] == "trust_gap_quarantine"
    assert body["governed_receipt"]["decision_hash"] == "receipt-intent-router-5"
    assert body["governed_receipt"]["trust_gap_codes"] == ["stale_telemetry"]


def test_task_governance_endpoint_exposes_authz_transition_summary() -> None:
    task_id = uuid.UUID("00000000-0000-0000-0000-0000000000f5")
    record = _apply_transition_metadata(
        _build_audit_record(task_id=str(task_id), intent_id="intent-router-6", asset_id="asset-1")
    )
    session = _TaskGovernanceSession(task=SimpleNamespace(id=task_id, result=None))
    client = _make_client(record, session=session, governance_entries=[record])

    response = client.get(f"/tasks/{task_id}/governance")

    assert response.status_code == 200
    body = response.json()
    assert body["latest"]["authz_transition_summary"]["reason"] == "trust_gap_quarantine"
    assert body["latest"]["authz_transition_summary"]["governed_receipt_hash"] == "receipt-intent-router-6"
    assert body["entries"][0]["authz_transition_summary"]["trust_gap_codes"] == ["stale_telemetry"]
