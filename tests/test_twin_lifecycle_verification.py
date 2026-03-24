from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies  # noqa: F401

from seedcore.services.custody_graph_service import CustodyGraphService
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


class _FakeTransitionDAO:
    def __init__(self) -> None:
        self.rows = []

    async def get_latest_for_asset(self, session, *, asset_id: str):
        matches = [row for row in self.rows if row["asset_id"] == asset_id]
        return matches[-1] if matches else None

    async def append_transition_event(self, session, **payload):
        row = dict(payload)
        row.setdefault("recorded_at", f"2026-03-24T10:0{len(self.rows)}:00+00:00")
        self.rows.append(row)
        return row

    async def list_for_asset(self, session, *, asset_id: str, limit: int = 100):
        return [row for row in self.rows if row["asset_id"] == asset_id][:limit]


class _FakeGraphDAO:
    async def upsert_node(self, session, **kwargs):
        return kwargs

    async def append_edge(self, session, **kwargs):
        return kwargs

    async def list_nodes(self, session, *, node_ids):
        return [{"node_id": node_id} for node_id in node_ids]

    async def list_edges_for_nodes(self, session, *, node_ids):
        return []


class _FakeDisputeDAO:
    async def list_cases(self, session, **kwargs):
        return []


class _FakeDigitalTwinDAO:
    def __init__(self) -> None:
        self.history_rows = [
            {
                "id": "asset-rev-1",
                "twin_type": "asset",
                "twin_id": "asset:asset-1",
                "state_version": 1,
                "authority_source": "coordinator.pdp",
            },
            {
                "id": "asset-rev-2",
                "twin_type": "asset",
                "twin_id": "asset:asset-1",
                "state_version": 2,
                "authority_source": "governed_transition_receipt",
            },
        ]

    async def list_history(self, session, *, twin_type: str, twin_id: str, limit: int = 50):
        return [row for row in self.history_rows if row["twin_type"] == twin_type and row["twin_id"] == twin_id][:limit]


def _governed_snapshot() -> dict:
    return {
        "asset": {
            "twin_kind": "asset",
            "twin_id": "asset:asset-1",
            "identity": {"asset_id": "asset-1"},
            "lineage_refs": ["batch:lot-10"],
        }
    }


def _build_record(seq: int) -> dict:
    return {
        "entry_id": f"audit-{seq}",
        "task_id": f"00000000-0000-0000-0000-00000000000{seq}",
        "record_type": "execution_receipt",
        "agent_id": "agent:test",
        "organ_id": "organ:test",
        "evidence_bundle": {
            "evidence_bundle_id": f"bundle-{seq}",
            "evidence_inputs": {
                "transition_receipts": [
                    {
                        "transition_receipt_id": f"receipt-{seq}",
                        "from_zone": "staging-a" if seq == 1 else "vault-a",
                        "to_zone": "vault-a" if seq == 1 else "shipping-b",
                        "endpoint_id": "robot_sim://unit-1",
                    }
                ]
            },
        },
    }


def _build_governance(seq: int) -> dict:
    return {
        "action_intent": {
            "intent_id": f"intent-{seq}",
            "principal": {"owner_id": "did:seedcore:owner:1", "agent_id": "did:seedcore:assistant:1"},
            "resource": {"asset_id": "asset-1", "source_registration_id": "reg-1"},
        },
        "execution_token": {"token_id": f"token-{seq}"},
        "policy_receipt": {"policy_receipt_id": f"policy-{seq}"},
    }


@pytest.mark.asyncio
async def test_execution_time_updates_work() -> None:
    session = MagicMock()
    session.begin = MagicMock(return_value=_BeginCtx())
    captured = []

    async def _capture_upsert(*_args, **kwargs):
        captured.append(kwargs["twin_snapshot"])
        return {"changed": True}

    service = DigitalTwinService(
        session_factory=MagicMock(return_value=_SessionCtx(session)),
        dao=SimpleNamespace(upsert_snapshot=AsyncMock(side_effect=_capture_upsert)),
        event_dao=SimpleNamespace(append_event=AsyncMock(return_value={"id": "evt-1"})),
    )

    result = await service.persist_relevant_twins(
        relevant_twin_snapshot=_governed_snapshot(),
        task_id="task-execution",
        intent_id="intent-execution",
        transition_context={"phase": "execution", "execution_token": {"token_id": "token-1"}},
    )

    assert result["updated"] == 1
    assert captured[0]["revision_stage"] == "EXECUTED"
    assert captured[0]["lifecycle_state"] == "IN_TRANSIT"
    assert captured[0]["custody"]["pending_authority"] is True


@pytest.mark.asyncio
async def test_transitions_are_valid_and_promote_authority() -> None:
    session = MagicMock()
    session.begin = MagicMock(return_value=_BeginCtx())
    captured = []

    async def _capture_upsert(*_args, **kwargs):
        captured.append(kwargs["twin_snapshot"])
        return {"changed": True}

    service = DigitalTwinService(
        session_factory=MagicMock(return_value=_SessionCtx(session)),
        dao=SimpleNamespace(upsert_snapshot=AsyncMock(side_effect=_capture_upsert)),
        event_dao=SimpleNamespace(append_event=AsyncMock(return_value={"id": "evt-1"})),
    )

    result = await service.settle_from_evidence_bundle(
        relevant_twin_snapshot={
            "asset": {
                "twin_kind": "asset",
                "twin_id": "asset:asset-1",
                "lifecycle_state": "IN_TRANSIT",
                "revision_stage": "EXECUTED",
            }
        },
        task_id="task-settlement",
        intent_id="intent-settlement",
        execution_token={"constraints": {"endpoint_id": "robot_sim://unit-1"}},
        evidence_bundle={
            "node_id": "robot_sim://unit-1",
            "evidence_inputs": {"execution_summary": {"node_id": "robot_sim://unit-1"}},
        },
    )

    assert result["updated"] == 1
    assert captured[0]["revision_stage"] == "AUTHORITATIVE"
    assert captured[0]["custody"]["pending_authority"] is False
    assert captured[0]["custody"]["authoritative_node_id"] == "robot_sim://unit-1"


@pytest.mark.asyncio
async def test_history_is_correct() -> None:
    service = DigitalTwinService(
        session_factory=MagicMock(return_value=_SessionCtx(MagicMock())),
        dao=_FakeDigitalTwinDAO(),
        event_dao=SimpleNamespace(),
    )

    history = await service.get_twin_history(twin_type="asset", twin_id="asset:asset-1", limit=10)

    assert [row["state_version"] for row in history] == [1, 2]
    assert history[-1]["authority_source"] == "governed_transition_receipt"


@pytest.mark.asyncio
async def test_lineage_is_consistent_across_ancestry_and_asset_lineage() -> None:
    twin_service = DigitalTwinService(session_factory=MagicMock(), dao=SimpleNamespace(), event_dao=SimpleNamespace())
    twin_service.get_authoritative_twin = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            {"snapshot": {"twin_kind": "asset", "twin_id": "asset:asset-1", "lineage_refs": ["batch:lot-10"]}},
            {"snapshot": {"twin_kind": "batch", "twin_id": "batch:lot-10", "lineage_refs": ["product:sku-77"]}},
            {"snapshot": {"twin_kind": "product", "twin_id": "product:sku-77", "lineage_refs": []}},
        ]
    )
    ancestry = await twin_service.get_twin_ancestry(twin_type="asset", twin_id="asset:asset-1")

    custody_service = CustodyGraphService(
        transition_dao=_FakeTransitionDAO(),
        graph_dao=_FakeGraphDAO(),
        dispute_dao=_FakeDisputeDAO(),
        digital_twin_dao=_FakeDigitalTwinDAO(),
    )
    custody_service._linked_twin_refs = AsyncMock(return_value=[  # type: ignore[method-assign]
        {"id": "asset-rev-2", "twin_type": "asset", "twin_id": "asset:asset-1"},
        {"id": "batch-rev-1", "twin_type": "batch", "twin_id": "batch:lot-10"},
    ])

    await custody_service.record_governed_transition(
        object(),
        record=_build_record(1),
        governance_ctx=_build_governance(1),
        custody_update={
            "asset_id": "asset-1",
            "current_zone": "vault-a",
            "authority_source": "governed_transition_receipt",
            "last_transition_seq": 1,
            "last_receipt_hash": "hash-1",
            "last_receipt_nonce": "nonce-1",
            "last_endpoint_id": "robot_sim://unit-1",
            "source_registration_id": "reg-1",
        },
    )
    lineage = await custody_service.get_asset_lineage(object(), asset_id="asset-1", limit=10)

    assert [row["snapshot"]["twin_id"] for row in ancestry] == ["asset:asset-1", "batch:lot-10", "product:sku-77"]
    assert lineage["transition_count"] == 1
    assert lineage["artifacts"][0]["transition_event_id"] == "receipt-1"
    assert {item["twin_id"] for item in lineage["twin_refs"]} == {"asset:asset-1", "batch:lot-10"}
