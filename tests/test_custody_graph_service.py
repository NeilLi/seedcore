from __future__ import annotations

import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401

import pytest

from seedcore.services.custody_graph_service import CustodyGraphService


class _FakeTransitionDAO:
    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []

    async def get_latest_for_asset(self, session, *, asset_id: str):
        matches = [row for row in self.rows if row["asset_id"] == asset_id]
        return matches[-1] if matches else None

    async def append_transition_event(self, session, **payload: Any):
        row = dict(payload)
        row.setdefault("recorded_at", f"2026-03-20T10:0{len(self.rows)}:00+00:00")
        row.setdefault("id", f"row-{len(self.rows)+1}")
        self.rows.append(row)
        return row

    async def list_for_asset(self, session, *, asset_id: str, limit: int = 100):
        return [row for row in self.rows if row["asset_id"] == asset_id][:limit]

    async def search(self, session, **filters: Any):
        rows = list(self.rows)
        if filters.get("asset_id"):
            rows = [row for row in rows if row["asset_id"] == filters["asset_id"]]
        if filters.get("zone"):
            rows = [row for row in rows if row.get("from_zone") == filters["zone"] or row.get("to_zone") == filters["zone"]]
        return rows


class _FakeGraphDAO:
    def __init__(self) -> None:
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.edges: Dict[str, Dict[str, Any]] = {}

    async def upsert_node(self, session, *, node_id: str, node_kind: str, subject_id: str | None = None, payload: Dict[str, Any] | None = None):
        row = self.nodes.get(node_id, {"node_id": node_id, "node_kind": node_kind, "subject_id": subject_id, "payload": {}})
        row["node_kind"] = node_kind
        row["subject_id"] = subject_id
        row["payload"] = {**row.get("payload", {}), **dict(payload or {})}
        self.nodes[node_id] = row
        return row

    async def append_edge(self, session, *, edge_id: str, edge_kind: str, from_node_id: str, to_node_id: str, source_ref: str | None = None, payload: Dict[str, Any] | None = None):
        row = self.edges.get(
            edge_id,
            {
                "edge_id": edge_id,
                "edge_kind": edge_kind,
                "from_node_id": from_node_id,
                "to_node_id": to_node_id,
                "source_ref": source_ref,
                "payload": dict(payload or {}),
            },
        )
        self.edges[edge_id] = row
        return row

    async def list_nodes(self, session, *, node_ids):
        return [self.nodes[node_id] for node_id in node_ids if node_id in self.nodes]

    async def list_edges_for_nodes(self, session, *, node_ids):
        result = []
        for edge in self.edges.values():
            if edge["from_node_id"] in node_ids or edge["to_node_id"] in node_ids:
                result.append(edge)
        return result


class _FakeDisputeDAO:
    def __init__(self) -> None:
        self.cases: Dict[str, Dict[str, Any]] = {}
        self.events: Dict[str, List[Dict[str, Any]]] = {}

    async def create_case(self, session, **payload: Any):
        row = dict(payload)
        row.setdefault("id", f"case-{len(self.cases)+1}")
        row.setdefault("recorded_at", "2026-03-20T11:00:00+00:00")
        row.setdefault("updated_at", "2026-03-20T11:00:00+00:00")
        row.setdefault("resolved_at", None)
        self.cases[row["dispute_id"]] = row
        self.events.setdefault(row["dispute_id"], [])
        return row

    async def get_case(self, session, *, dispute_id: str):
        return self.cases.get(dispute_id)

    async def list_cases(self, session, *, status=None, asset_id=None, limit: int = 100):
        rows = list(self.cases.values())
        if status:
            rows = [row for row in rows if row["status"] == status]
        if asset_id:
            rows = [row for row in rows if row.get("asset_id") == asset_id]
        return rows[:limit]

    async def append_event(self, session, *, dispute_id: str, event_type: str, actor_id=None, note=None, payload=None, status=None):
        if dispute_id not in self.cases:
            raise ValueError(f"Unknown dispute_id '{dispute_id}'")
        if status is not None:
            self.cases[dispute_id]["status"] = status
        row = {
            "id": f"event-{len(self.events[dispute_id])+1}",
            "dispute_case_id": self.cases[dispute_id]["id"],
            "dispute_id": dispute_id,
            "event_type": event_type,
            "status": status or self.cases[dispute_id]["status"],
            "actor_id": actor_id,
            "note": note,
            "payload": dict(payload or {}),
            "recorded_at": f"2026-03-20T11:0{len(self.events[dispute_id])}:00+00:00",
        }
        self.events[dispute_id].append(row)
        return row

    async def resolve_case(self, session, *, dispute_id: str, status: str, resolved_by: str | None, resolution: str | None):
        row = self.cases.get(dispute_id)
        if row is None:
            return None
        row["status"] = status
        row["resolved_by"] = resolved_by
        row["resolution"] = resolution
        row["resolved_at"] = "2026-03-20T12:00:00+00:00"
        row["updated_at"] = "2026-03-20T12:00:00+00:00"
        return row

    async def list_events(self, session, *, dispute_id: str, limit: int = 100):
        return self.events.get(dispute_id, [])[:limit]


class _FakeDigitalTwinDAO:
    async def list_history(self, session, *, twin_type: str, twin_id: str, limit: int = 5):
        return [{"id": f"{twin_type}-rev-1", "twin_type": twin_type, "twin_id": twin_id, "state_version": 1}]


def _build_record(seq: int) -> Dict[str, Any]:
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


def _build_governance(seq: int) -> Dict[str, Any]:
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
async def test_record_transition_builds_lineage_chain_and_projection():
    service = CustodyGraphService(
        transition_dao=_FakeTransitionDAO(),
        graph_dao=_FakeGraphDAO(),
        dispute_dao=_FakeDisputeDAO(),
        digital_twin_dao=_FakeDigitalTwinDAO(),
    )

    first = await service.record_governed_transition(
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
    second = await service.record_governed_transition(
        object(),
        record=_build_record(2),
        governance_ctx=_build_governance(2),
        custody_update={
            "asset_id": "asset-1",
            "current_zone": "shipping-b",
            "authority_source": "governed_transition_receipt",
            "last_transition_seq": 2,
            "last_receipt_hash": "hash-2",
            "last_receipt_nonce": "nonce-2",
            "last_endpoint_id": "robot_sim://unit-1",
            "source_registration_id": "reg-1",
        },
    )

    assert first is not None
    assert second is not None
    assert second["transition_event"]["previous_transition_event_id"] == "receipt-1"
    assert second["transition_event"]["previous_receipt_hash"] == "hash-1"
    assert "asset:asset-1" in second["projection"]["node_ids"]


@pytest.mark.asyncio
async def test_dispute_workflow_and_lineage_attach_disputes():
    service = CustodyGraphService(
        transition_dao=_FakeTransitionDAO(),
        graph_dao=_FakeGraphDAO(),
        dispute_dao=_FakeDisputeDAO(),
        digital_twin_dao=_FakeDigitalTwinDAO(),
    )
    await service.record_governed_transition(
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

    dispute = await service.open_dispute(
        object(),
        title="Seal mismatch",
        summary="Barcode and seal photo disagree",
        opened_by="auditor:1",
        references={"asset_id": "asset-1", "transition_event_id": "receipt-1"},
        metadata={"severity": "high"},
    )
    await service.append_dispute_event(
        object(),
        dispute_id=dispute["dispute_id"],
        actor_id="auditor:2",
        note="Review started",
        payload={},
        status="UNDER_REVIEW",
    )
    resolved = await service.resolve_dispute(
        object(),
        dispute_id=dispute["dispute_id"],
        status="RESOLVED",
        resolved_by="auditor:3",
        resolution="Photos and receipt reconciled",
    )
    lineage = await service.get_asset_lineage(object(), asset_id="asset-1")
    graph = await service.get_asset_graph(object(), asset_id="asset-1")

    assert resolved is not None
    assert resolved["status"] == "RESOLVED"
    assert lineage["transitions"][0]["disputes"][0]["dispute_id"] == dispute["dispute_id"]
    assert any(node["node_id"].startswith("dispute_case:") for node in graph["nodes"])
