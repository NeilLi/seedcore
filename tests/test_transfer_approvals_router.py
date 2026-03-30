from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401

from fastapi import FastAPI
from fastapi.testclient import TestClient

import seedcore.api.routers.transfer_approvals_router as transfer_approvals_router_module


def _make_client(session: SimpleNamespace) -> TestClient:
    app = FastAPI()
    app.include_router(transfer_approvals_router_module.router)

    async def override_session():
        return session

    app.dependency_overrides[transfer_approvals_router_module.get_async_pg_session] = override_session
    return TestClient(app)


def _session() -> SimpleNamespace:
    return SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())


def test_create_transfer_approval_persists_envelope(monkeypatch) -> None:
    session = _session()
    client = _make_client(session)
    record = {
        "approval_envelope_id": "approval-transfer-001",
        "version": 1,
        "approval_binding_hash": "sha256:approval-binding-transfer-001",
        "envelope": {"approval_envelope_id": "approval-transfer-001"},
    }
    create_or_update = AsyncMock(return_value=record)
    monkeypatch.setattr(transfer_approvals_router_module._DAO, "create_or_update_envelope", create_or_update)

    response = client.post(
        "/transfer-approvals",
        json={"envelope": {"approval_envelope_id": "approval-transfer-001"}},
    )

    assert response.status_code == 200
    assert response.json() == record
    create_or_update.assert_awaited_once()
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


def test_fetch_transfer_approval_returns_current_record(monkeypatch) -> None:
    session = _session()
    client = _make_client(session)
    record = {
        "approval_envelope_id": "approval-transfer-001",
        "version": 2,
        "transition_history": [{"event_id": "approval-transition-event:001"}],
        "approval_transition_head": "sha256:transition-head-001",
    }
    get_current = AsyncMock(return_value=record)
    monkeypatch.setattr(transfer_approvals_router_module._DAO, "get_current_with_history", get_current)

    response = client.get("/transfer-approvals/approval-transfer-001")

    assert response.status_code == 200
    assert response.json() == record
    get_current.assert_awaited_once()


def test_fetch_transfer_approval_version_returns_requested_version(monkeypatch) -> None:
    session = _session()
    client = _make_client(session)
    record = {
        "approval_envelope_id": "approval-transfer-001",
        "version": 1,
        "envelope": {"approval_envelope_id": "approval-transfer-001", "version": 1},
    }
    get_version = AsyncMock(return_value=record)
    monkeypatch.setattr(transfer_approvals_router_module._DAO, "get_version", get_version)

    response = client.get("/transfer-approvals/approval-transfer-001/versions/1")

    assert response.status_code == 200
    assert response.json() == record
    get_version.assert_awaited_once()


def test_apply_transfer_approval_transition_uses_persisted_history(monkeypatch) -> None:
    session = _session()
    client = _make_client(session)
    record = {
        "approval_envelope_id": "approval-transfer-001",
        "version": 2,
        "approval_transition_head": "sha256:transition-head-002",
        "transition_history": [{"event_id": "approval-transition-event:002"}],
    }
    apply_transition = AsyncMock(return_value=record)
    monkeypatch.setattr(transfer_approvals_router_module._DAO, "apply_transition", apply_transition)

    response = client.post(
        "/transfer-approvals/approval-transfer-001/transitions",
        json={
            "transition": {
                "type": "add_approval",
                "role": "QUALITY_INSPECTOR",
                "principal_ref": "principal:quality_insp_017",
            },
            "actor_ref": "principal:facility_mgr_001",
            "occurred_at": "2099-03-20T12:00:03+00:00",
        },
    )

    assert response.status_code == 200
    assert response.json() == record
    apply_transition.assert_awaited_once()
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()
