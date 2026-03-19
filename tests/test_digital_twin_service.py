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
