from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies  # noqa: F401

from seedcore.services.digital_twin_service import DigitalTwinService


class _SessionCtx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _BeginCtx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_resolve_relevant_twins_prefers_persisted_then_applies_live_authoritative_overlays():
    session = MagicMock()
    dao = SimpleNamespace(
        get_authoritative_snapshots=AsyncMock(
            return_value={
                ("assistant", "assistant:agent-1"): {
                    "snapshot": {
                        "twin_type": "assistant",
                        "twin_id": "assistant:agent-1",
                        "identity": {"agent_id": "agent-1"},
                        "delegation": {"role_profile": "PERSISTED_ROLE", "revoked": False},
                    }
                },
                ("asset", "asset:asset-1"): {
                    "snapshot": {
                        "twin_type": "asset",
                        "twin_id": "asset:asset-1",
                        "identity": {"asset_id": "asset-1"},
                        "custody": {"asset_id": "asset-1", "target_zone": "persisted-zone"},
                    }
                },
            }
        )
    )
    session_factory = MagicMock(return_value=_SessionCtx(session))
    service = DigitalTwinService(session_factory=session_factory, dao=dao)

    task_payload = {
        "task_id": "task-1",
        "type": "action",
        "params": {
            "interaction": {"assigned_agent_id": "agent-1"},
            "resource": {"asset_id": "asset-1"},
            "intent": "release",
        },
    }

    resolved = await service.resolve_relevant_twins(
        task_payload,
        authoritative_state={
            "agents": {
                "agent-1": {
                    "is_revoked": True,
                    "role_profile": "LIVE_ROLE",
                }
            },
            "assets": {
                "asset-1": {
                    "is_quarantined": True,
                    "current_zone": "live-zone",
                }
            },
        },
    )

    assert resolved["assistant"]["delegation"]["role_profile"] == "LIVE_ROLE"
    assert resolved["assistant"]["delegation"]["revoked"] is True
    assert resolved["asset"]["custody"]["target_zone"] == "live-zone"
    assert resolved["asset"]["custody"]["quarantined"] is True


@pytest.mark.asyncio
async def test_persist_relevant_twins_tracks_version_bumps():
    session = MagicMock()
    session.begin = MagicMock(return_value=_BeginCtx())
    dao = SimpleNamespace(
        upsert_snapshot=AsyncMock(
            side_effect=[
                {"changed": True},
                {"changed": False},
            ]
        )
    )
    session_factory = MagicMock(return_value=_SessionCtx(session))
    service = DigitalTwinService(session_factory=session_factory, dao=dao)

    summary = await service.persist_relevant_twins(
        relevant_twin_snapshot={
            "assistant": {
                "twin_type": "assistant",
                "twin_id": "assistant:agent-1",
                "identity": {"agent_id": "agent-1"},
            },
            "asset": {
                "twin_type": "asset",
                "twin_id": "asset:asset-1",
                "identity": {"asset_id": "asset-1"},
            },
        },
        task_id="123e4567-e89b-12d3-a456-426614174000",
        intent_id="intent-123",
        authority_source="coordinator.pdp",
        change_reason="policy_case_resolution",
    )

    assert summary["updated"] == 2
    assert summary["version_bumped"] == 1
    assert dao.upsert_snapshot.await_count == 2


@pytest.mark.asyncio
async def test_persist_relevant_twins_infers_in_transit_state_on_execution_token():
    session = MagicMock()
    session.begin = MagicMock(return_value=_BeginCtx())
    captured = []

    async def _capture_upsert(*_args, **kwargs):
        captured.append(kwargs["twin_snapshot"])
        return {"changed": True}

    dao = SimpleNamespace(upsert_snapshot=AsyncMock(side_effect=_capture_upsert))
    session_factory = MagicMock(return_value=_SessionCtx(session))
    service = DigitalTwinService(session_factory=session_factory, dao=dao)

    await service.persist_relevant_twins(
        relevant_twin_snapshot={
            "asset": {
                "twin_type": "asset",
                "twin_id": "asset:asset-1",
                "governed_state": "CERTIFIED",
                "identity": {"asset_id": "asset-1"},
            }
        },
        task_id="123e4567-e89b-12d3-a456-426614174000",
        intent_id="intent-123",
        transition_context={
            "execution_token": {"token_id": "token-1"},
            "policy_receipt": {"execution_token": {"token_id": "token-1"}},
        },
    )

    assert captured[0]["governed_state"] == "IN_TRANSIT"
    assert captured[0]["authority_status"] == "PENDING"


@pytest.mark.asyncio
async def test_get_twin_ancestry_follows_parent_chain():
    dao = SimpleNamespace()
    session_factory = MagicMock()
    service = DigitalTwinService(session_factory=session_factory, dao=dao)

    service.get_authoritative_twin = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            {
                "snapshot": {
                    "twin_type": "asset",
                    "twin_id": "asset:unit-1",
                    "parent_twin_id": "batch:lot-10",
                }
            },
            {
                "snapshot": {
                    "twin_type": "batch",
                    "twin_id": "batch:lot-10",
                }
            },
        ]
    )

    ancestry = await service.get_twin_ancestry(twin_type="asset", twin_id="asset:unit-1")
    assert len(ancestry) == 2


@pytest.mark.asyncio
async def test_settle_from_evidence_bundle_promotes_pending_to_authoritative():
    session = MagicMock()
    session.begin = MagicMock(return_value=_BeginCtx())
    captured = []

    async def _capture_upsert(*_args, **kwargs):
        captured.append(kwargs["twin_snapshot"])
        return {"changed": True}

    dao = SimpleNamespace(upsert_snapshot=AsyncMock(side_effect=_capture_upsert))
    session_factory = MagicMock(return_value=_SessionCtx(session))
    service = DigitalTwinService(session_factory=session_factory, dao=dao)

    result = await service.settle_from_evidence_bundle(
        relevant_twin_snapshot={
            "asset": {
                "twin_type": "asset",
                "twin_id": "asset:asset-1",
                "governed_state": "IN_TRANSIT",
                "authority_status": "PENDING",
            }
        },
        task_id="123e4567-e89b-12d3-a456-426614174000",
        intent_id="intent-123",
        execution_token={"constraints": {"endpoint_id": "node-1"}},
        evidence_bundle={
            "node_id": "node-1",
            "execution_receipt": {"node_id": "node-1"},
        },
    )

    assert result["updated"] == 1
    assert captured[0]["authority_status"] == "AUTHORITATIVE"
    assert captured[0]["custody"]["pending_authority"] is False
    assert captured[0]["custody"]["authoritative_node_id"] == "node-1"


@pytest.mark.asyncio
async def test_settle_from_evidence_bundle_rejects_node_mismatch():
    session = MagicMock()
    session.begin = MagicMock(return_value=_BeginCtx())
    dao = SimpleNamespace(upsert_snapshot=AsyncMock(return_value={"changed": True}))
    session_factory = MagicMock(return_value=_SessionCtx(session))
    service = DigitalTwinService(session_factory=session_factory, dao=dao)

    result = await service.settle_from_evidence_bundle(
        relevant_twin_snapshot={
            "asset": {
                "twin_type": "asset",
                "twin_id": "asset:asset-1",
                "governed_state": "IN_TRANSIT",
                "authority_status": "PENDING",
            }
        },
        task_id="123e4567-e89b-12d3-a456-426614174000",
        intent_id="intent-123",
        execution_token={"constraints": {"endpoint_id": "node-expected"}},
        evidence_bundle={
            "node_id": "node-actual",
            "execution_receipt": {"node_id": "node-actual"},
        },
    )

    assert result["updated"] == 0
    assert result["rejected_reason"] == "node_id_mismatch_expected_endpoint"
    assert dao.upsert_snapshot.await_count == 0
