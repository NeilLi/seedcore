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
                        "twin_kind": "assistant",
                        "twin_id": "assistant:agent-1",
                        "identity": {"agent_id": "agent-1"},
                        "delegation": {"role_profile": "PERSISTED_ROLE", "revoked": False},
                    }
                },
                ("asset", "asset:asset-1"): {
                    "snapshot": {
                        "twin_kind": "asset",
                        "twin_id": "asset:asset-1",
                        "identity": {"asset_id": "asset-1"},
                        "custody": {"asset_id": "asset-1", "target_zone": "persisted-zone"},
                    }
                },
            }
        )
    )
    session_factory = MagicMock(return_value=_SessionCtx(session))
    service = DigitalTwinService(session_factory=session_factory, dao=dao, event_dao=SimpleNamespace(append_event=AsyncMock()))

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
            "agents": {"agent-1": {"is_revoked": True, "role_profile": "LIVE_ROLE", "risk_score": 0.7}},
            "assets": {"asset-1": {"is_quarantined": True, "current_zone": "live-zone"}},
        },
    )

    assert resolved["assistant"]["delegation"]["role_profile"] == "LIVE_ROLE"
    assert resolved["assistant"]["delegation"]["revoked"] is True
    assert resolved["assistant"]["risk"]["score"] == 0.7
    assert resolved["asset"]["custody"]["target_zone"] == "live-zone"
    assert resolved["asset"]["custody"]["quarantined"] is True


@pytest.mark.asyncio
async def test_persist_relevant_twins_sets_pending_stage_for_policy_events():
    session = MagicMock()
    session.begin = MagicMock(return_value=_BeginCtx())
    captured = []

    async def _capture_upsert(*_args, **kwargs):
        captured.append(kwargs["twin_snapshot"])
        return {"changed": True}

    dao = SimpleNamespace(upsert_snapshot=AsyncMock(side_effect=_capture_upsert))
    event_dao = SimpleNamespace(append_event=AsyncMock(return_value={"id": "evt-1"}))
    session_factory = MagicMock(return_value=_SessionCtx(session))
    service = DigitalTwinService(session_factory=session_factory, dao=dao, event_dao=event_dao)

    result = await service.persist_relevant_twins(
        relevant_twin_snapshot={
            "asset": {
                "twin_kind": "asset",
                "twin_id": "asset:asset-1",
                "identity": {"asset_id": "asset-1"},
            }
        },
        task_id="123e4567-e89b-12d3-a456-426614174000",
        intent_id="intent-123",
        transition_context={"phase": "policy_time", "execution_token": {"token_id": "token-1"}},
    )

    assert result["updated"] == 1
    assert captured[0]["revision_stage"] == "PENDING"
    assert captured[0]["lifecycle_state"] == "IN_TRANSIT"


@pytest.mark.asyncio
async def test_get_twin_ancestry_follows_lineage_refs():
    service = DigitalTwinService(session_factory=MagicMock(), dao=SimpleNamespace(), event_dao=SimpleNamespace())
    service.get_authoritative_twin = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            {"snapshot": {"twin_kind": "asset", "twin_id": "asset:unit-1", "lineage_refs": ["batch:lot-10"]}},
            {"snapshot": {"twin_kind": "batch", "twin_id": "batch:lot-10", "lineage_refs": []}},
        ]
    )

    ancestry = await service.get_twin_ancestry(twin_type="asset", twin_id="asset:unit-1")
    assert len(ancestry) == 2


@pytest.mark.asyncio
async def test_settle_from_evidence_bundle_promotes_to_authoritative():
    session = MagicMock()
    session.begin = MagicMock(return_value=_BeginCtx())
    captured = []

    async def _capture_upsert(*_args, **kwargs):
        captured.append(kwargs["twin_snapshot"])
        return {"changed": True}

    dao = SimpleNamespace(upsert_snapshot=AsyncMock(side_effect=_capture_upsert))
    event_dao = SimpleNamespace(append_event=AsyncMock(return_value={"id": "evt-1"}))
    session_factory = MagicMock(return_value=_SessionCtx(session))
    service = DigitalTwinService(session_factory=session_factory, dao=dao, event_dao=event_dao)

    result = await service.settle_from_evidence_bundle(
        relevant_twin_snapshot={
            "asset": {
                "twin_kind": "asset",
                "twin_id": "asset:asset-1",
                "lifecycle_state": "IN_TRANSIT",
                "revision_stage": "EXECUTED",
            }
        },
        task_id="123e4567-e89b-12d3-a456-426614174000",
        intent_id="intent-123",
        execution_token={"constraints": {"endpoint_id": "node-1"}},
        evidence_bundle={
            "node_id": "node-1",
            "evidence_inputs": {"execution_summary": {"node_id": "node-1"}},
        },
    )

    assert result["updated"] == 1
    assert captured[0]["revision_stage"] == "AUTHORITATIVE"
    assert captured[0]["custody"]["authoritative_node_id"] == "node-1"
