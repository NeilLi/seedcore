#!/usr/bin/env python3
"""Verify digital twin lifecycle execution, history, and lineage contracts."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
TESTS_ROOT = PROJECT_ROOT / "tests"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from seedcore.services.custody_graph_service import CustodyGraphService
from seedcore.services.digital_twin_service import DigitalTwinService


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: dict


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
            {"id": "asset-rev-1", "twin_type": "asset", "twin_id": "asset:asset-1", "state_version": 1, "authority_source": "coordinator.pdp"},
            {"id": "asset-rev-2", "twin_type": "asset", "twin_id": "asset:asset-1", "state_version": 2, "authority_source": "governed_transition_receipt"},
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


async def _run() -> int:
    results: list[CheckResult] = []

    session = MagicMock()
    session.begin = MagicMock(return_value=_BeginCtx())
    captured = []

    async def _capture_upsert(*_args, **kwargs):
        captured.append(kwargs["twin_snapshot"])
        return {"changed": True}

    twin_service = DigitalTwinService(
        session_factory=MagicMock(return_value=_SessionCtx(session)),
        dao=SimpleNamespace(upsert_snapshot=AsyncMock(side_effect=_capture_upsert)),
        event_dao=SimpleNamespace(append_event=AsyncMock(return_value={"id": "evt-1"})),
    )

    await twin_service.persist_relevant_twins(
        relevant_twin_snapshot=_governed_snapshot(),
        task_id="task-execution",
        intent_id="intent-execution",
        transition_context={"phase": "execution", "execution_token": {"token_id": "token-1"}},
    )
    results.append(
        CheckResult(
            "twin.execution_time_updates_work",
            captured[0]["revision_stage"] == "EXECUTED"
            and captured[0]["lifecycle_state"] == "IN_TRANSIT"
            and captured[0]["custody"]["pending_authority"] is True,
            {
                "revision_stage": captured[0]["revision_stage"],
                "lifecycle_state": captured[0]["lifecycle_state"],
                "pending_authority": captured[0]["custody"]["pending_authority"],
            },
        )
    )

    captured.clear()
    await twin_service.settle_from_evidence_bundle(
        relevant_twin_snapshot={"asset": {"twin_kind": "asset", "twin_id": "asset:asset-1", "lifecycle_state": "IN_TRANSIT", "revision_stage": "EXECUTED"}},
        task_id="task-settlement",
        intent_id="intent-settlement",
        execution_token={"constraints": {"endpoint_id": "robot_sim://unit-1"}},
        evidence_bundle={"node_id": "robot_sim://unit-1", "evidence_inputs": {"execution_summary": {"node_id": "robot_sim://unit-1"}}},
    )
    results.append(
        CheckResult(
            "twin.transitions_are_valid",
            captured[0]["revision_stage"] == "AUTHORITATIVE"
            and captured[0]["custody"]["authoritative_node_id"] == "robot_sim://unit-1",
            {
                "revision_stage": captured[0]["revision_stage"],
                "authoritative_node_id": captured[0]["custody"].get("authoritative_node_id"),
            },
        )
    )

    history_service = DigitalTwinService(
        session_factory=MagicMock(return_value=_SessionCtx(MagicMock())),
        dao=_FakeDigitalTwinDAO(),
        event_dao=SimpleNamespace(),
    )
    history = await history_service.get_twin_history(twin_type="asset", twin_id="asset:asset-1", limit=10)
    results.append(
        CheckResult(
            "twin.history_is_correct",
            [row["state_version"] for row in history] == [1, 2] and history[-1]["authority_source"] == "governed_transition_receipt",
            {"versions": [row["state_version"] for row in history], "latest_authority": history[-1]["authority_source"]},
        )
    )

    ancestry_service = DigitalTwinService(session_factory=MagicMock(), dao=SimpleNamespace(), event_dao=SimpleNamespace())
    ancestry_service.get_authoritative_twin = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            {"snapshot": {"twin_kind": "asset", "twin_id": "asset:asset-1", "lineage_refs": ["batch:lot-10"]}},
            {"snapshot": {"twin_kind": "batch", "twin_id": "batch:lot-10", "lineage_refs": ["product:sku-77"]}},
            {"snapshot": {"twin_kind": "product", "twin_id": "product:sku-77", "lineage_refs": []}},
        ]
    )
    ancestry = await ancestry_service.get_twin_ancestry(twin_type="asset", twin_id="asset:asset-1")

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
    results.append(
        CheckResult(
            "twin.lineage_is_consistent",
            [row["snapshot"]["twin_id"] for row in ancestry] == ["asset:asset-1", "batch:lot-10", "product:sku-77"]
            and lineage["transition_count"] == 1
            and {item["twin_id"] for item in lineage["twin_refs"]} == {"asset:asset-1", "batch:lot-10"},
            {
                "ancestry_ids": [row["snapshot"]["twin_id"] for row in ancestry],
                "transition_count": lineage["transition_count"],
                "lineage_twin_refs": [item["twin_id"] for item in lineage["twin_refs"]],
            },
        )
    )

    failing = [result for result in results if not result.ok]
    for result in results:
        marker = "PASS" if result.ok else "FAIL"
        print(f"[{marker}] {result.name}: {json.dumps(result.detail, sort_keys=True)}")

    if failing:
        print(f"\nTwin lifecycle verification failed: {len(failing)} checks failed.", file=sys.stderr)
        return 1
    print("\nTwin lifecycle verification passed.")
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(_run()))
