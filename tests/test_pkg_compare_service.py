#!/usr/bin/env python3
"""
Unit tests for PKG snapshot comparison service and API route.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock
from typing import Optional

import seedcore.api.routers.pkg_router as pkg_router_module
from seedcore.ops.pkg.compare_service import PKGSnapshotCompareService
from seedcore.ops.pkg.dao import PKGSnapshotData
from seedcore.ops.pkg.evaluator import PKGEvaluator
from seedcore.ops.pkg.manager import PKGMode


def make_snapshot(
    snapshot_id: int,
    version: str,
    rules,
) -> PKGSnapshotData:
    return PKGSnapshotData(
        id=snapshot_id,
        version=version,
        engine="native",
        wasm_artifact=None,
        checksum=f"checksum-{snapshot_id}",
        rules=rules,
    )


def make_single_rule_snapshot(
    snapshot_id: int,
    version: str,
    *,
    desk: str = "gold",
    include_extra_rule: bool = False,
    replace_rule: bool = False,
    dag_mode: Optional[str] = None,
) -> PKGSnapshotData:
    base_rule = {
        "id": f"rule-{snapshot_id}-vip",
        "rule_name": "vip_route" if not replace_rule else "vip_special",
        "priority": 10,
        "metadata": {"gate_source": "prepare_vip"},
        "conditions": [
            {
                "condition_type": "TAG",
                "condition_key": "vip",
                "operator": "IN",
                "value": "vip",
            }
        ],
        "emissions": [
            {
                "subtask_type": "prepare",
                "subtask_name": "prepare_vip",
                "params": {"desk": desk},
                "relationship_type": "EMITS",
                "position": 0,
            }
        ],
    }

    if dag_mode is not None:
        base_rule["emissions"] = [
            {
                "subtask_type": "prepare",
                "subtask_name": "prepare_vip",
                "params": {"desk": desk},
                "relationship_type": "EMITS",
                "position": 0,
            },
            {
                "subtask_type": "escort",
                "subtask_name": "escort_vip",
                "params": {"channel": "radio"},
                "relationship_type": dag_mode,
                "position": 1,
            },
        ]

    rules = [base_rule]

    if include_extra_rule:
        rules.append(
            {
                "id": f"rule-{snapshot_id}-notify",
                "rule_name": "notify_staff",
                "priority": 8,
                "metadata": {},
                "conditions": [
                    {
                        "condition_type": "TAG",
                        "condition_key": "vip",
                        "operator": "IN",
                        "value": "vip",
                    }
                ],
                "emissions": [
                    {
                        "subtask_type": "notify",
                        "subtask_name": "notify_manager",
                        "params": {"priority": "high"},
                        "relationship_type": "EMITS",
                        "position": 0,
                    }
                ],
            }
        )

    return make_snapshot(snapshot_id, version, rules)


@pytest.fixture
def mock_pkg_client():
    client = AsyncMock()
    client.create_validation_run = AsyncMock(return_value=321)
    client.finish_validation_run = AsyncMock()
    client.get_active_governed_facts = AsyncMock(return_value=[])
    client.get_semantic_context = AsyncMock(return_value=[])
    client.get_validation_fixture_by_id = AsyncMock()
    return client


class TestPKGSnapshotCompareService:
    @pytest.mark.asyncio
    async def test_identical_snapshots_have_no_diff(self, mock_pkg_client):
        baseline = make_single_rule_snapshot(1, "rules@1.0.0")
        candidate = make_single_rule_snapshot(2, "rules@1.0.1")
        mock_pkg_client.get_snapshot_by_id = AsyncMock(side_effect=[baseline, candidate])

        service = PKGSnapshotCompareService(mock_pkg_client)
        result = await service.compare_snapshots(
            baseline_snapshot_id=1,
            candidate_snapshot_id=2,
            task_facts={"tags": ["vip"], "signals": {}, "context": {"subject": "guest:Ben"}},
        )

        assert result["summary"]["behavior_changed"] is False
        assert result["comparison"]["diff"]["emissions"] == []
        assert result["comparison"]["diff"]["dag"] == []
        finish_args = mock_pkg_client.finish_validation_run.await_args.args
        assert finish_args[1] is True

    @pytest.mark.asyncio
    async def test_param_change_becomes_changed_emission(self, mock_pkg_client):
        baseline = make_single_rule_snapshot(1, "rules@1.0.0", desk="gold")
        candidate = make_single_rule_snapshot(2, "rules@1.1.0", desk="platinum")
        mock_pkg_client.get_snapshot_by_id = AsyncMock(side_effect=[baseline, candidate])

        service = PKGSnapshotCompareService(mock_pkg_client)
        result = await service.compare_snapshots(
            baseline_snapshot_id=1,
            candidate_snapshot_id=2,
            task_facts={"tags": ["vip"], "signals": {}, "context": {"subject": "guest:Ben"}},
        )

        assert result["summary"]["behavior_changed"] is True
        assert result["summary"]["emissions"]["changed"] == 1
        diff_item = result["comparison"]["diff"]["emissions"][0]
        assert diff_item["status"] == "changed"
        assert diff_item["baseline"]["params"]["desk"] == "gold"
        assert diff_item["candidate"]["params"]["desk"] == "platinum"

    @pytest.mark.asyncio
    async def test_rule_addition_and_removal_are_summarized(self, mock_pkg_client):
        baseline = make_single_rule_snapshot(1, "rules@1.0.0", include_extra_rule=True)
        candidate = make_single_rule_snapshot(2, "rules@2.0.0", replace_rule=True)
        mock_pkg_client.get_snapshot_by_id = AsyncMock(side_effect=[baseline, candidate])

        service = PKGSnapshotCompareService(mock_pkg_client)
        result = await service.compare_snapshots(
            baseline_snapshot_id=1,
            candidate_snapshot_id=2,
            task_facts={"tags": ["vip"], "signals": {}, "context": {"subject": "guest:Ben"}},
        )

        statuses = [item["status"] for item in result["comparison"]["diff"]["emissions"]]
        assert "added" in statuses
        assert "removed" in statuses
        assert result["summary"]["changed_rule_count"] >= 2

    @pytest.mark.asyncio
    async def test_dag_only_changes_are_reported(self, mock_pkg_client):
        baseline = make_single_rule_snapshot(1, "rules@1.0.0", dag_mode="ORDERS")
        candidate = make_single_rule_snapshot(2, "rules@1.1.0", dag_mode="GATE")
        mock_pkg_client.get_snapshot_by_id = AsyncMock(side_effect=[baseline, candidate])

        service = PKGSnapshotCompareService(mock_pkg_client)
        result = await service.compare_snapshots(
            baseline_snapshot_id=1,
            candidate_snapshot_id=2,
            task_facts={"tags": ["vip"], "signals": {}, "context": {"subject": "guest:Ben"}},
        )

        assert result["comparison"]["diff"]["emissions"] == []
        dag_statuses = [item["status"] for item in result["comparison"]["diff"]["dag"]]
        assert dag_statuses.count("added") == 1
        assert dag_statuses.count("removed") == 1

    @pytest.mark.asyncio
    async def test_fixture_input_is_supported(self, mock_pkg_client):
        baseline = make_single_rule_snapshot(1, "rules@1.0.0")
        candidate = make_single_rule_snapshot(2, "rules@1.0.1")
        mock_pkg_client.get_snapshot_by_id = AsyncMock(side_effect=[baseline, candidate])
        mock_pkg_client.get_validation_fixture_by_id = AsyncMock(
            return_value={
                "id": 9,
                "snapshot_id": 1,
                "name": "vip_fixture",
                "input": {"tags": ["vip"], "signals": {}, "context": {"subject": "guest:Ben"}},
                "expect": {},
            }
        )

        service = PKGSnapshotCompareService(mock_pkg_client)
        result = await service.compare_snapshots(
            baseline_snapshot_id=1,
            candidate_snapshot_id=2,
            fixture_id=9,
        )

        assert result["run_id"] == 321
        mock_pkg_client.get_validation_fixture_by_id.assert_called_once_with(9)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "task_facts,fixture_id",
        [
            (None, None),
            ({"tags": [], "signals": {}, "context": {}}, 9),
        ],
    )
    async def test_invalid_input_source_rejected(self, mock_pkg_client, task_facts, fixture_id):
        service = PKGSnapshotCompareService(mock_pkg_client)

        with pytest.raises(ValueError, match="Exactly one of task_facts or fixture_id"):
            await service.compare_snapshots(
                baseline_snapshot_id=1,
                candidate_snapshot_id=2,
                task_facts=task_facts,
                fixture_id=fixture_id,
            )

        mock_pkg_client.create_validation_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_is_persisted_even_when_behavior_changes(self, mock_pkg_client):
        baseline = make_single_rule_snapshot(1, "rules@1.0.0", desk="gold")
        candidate = make_single_rule_snapshot(2, "rules@1.1.0", desk="silver")
        mock_pkg_client.get_snapshot_by_id = AsyncMock(side_effect=[baseline, candidate])

        service = PKGSnapshotCompareService(mock_pkg_client)
        await service.compare_snapshots(
            baseline_snapshot_id=1,
            candidate_snapshot_id=2,
            task_facts={"tags": ["vip"], "signals": {}, "context": {"subject": "guest:Ben"}},
        )

        finish_args = mock_pkg_client.finish_validation_run.await_args.args
        report = finish_args[2]
        assert finish_args[1] is True
        assert report["summary"]["behavior_changed"] is True

    @pytest.mark.asyncio
    async def test_partial_failure_is_persisted(self, mock_pkg_client, monkeypatch):
        baseline = make_single_rule_snapshot(1, "rules@1.0.0")
        candidate = make_single_rule_snapshot(2, "rules@1.1.0")
        mock_pkg_client.get_snapshot_by_id = AsyncMock(side_effect=[baseline, candidate])

        original_evaluate = PKGEvaluator.evaluate

        def flaky_evaluate(self, task_facts):
            if self.version == "rules@1.1.0":
                raise RuntimeError("candidate failure")
            return original_evaluate(self, task_facts)

        monkeypatch.setattr(PKGEvaluator, "evaluate", flaky_evaluate)

        service = PKGSnapshotCompareService(mock_pkg_client)
        with pytest.raises(RuntimeError, match="candidate failure"):
            await service.compare_snapshots(
                baseline_snapshot_id=1,
                candidate_snapshot_id=2,
                task_facts={"tags": ["vip"], "signals": {}, "context": {"subject": "guest:Ben"}},
            )

        finish_args = mock_pkg_client.finish_validation_run.await_args.args
        report = finish_args[2]
        assert finish_args[1] is False
        assert "baseline_result" in report
        assert report["errors"][0]["message"] == "candidate failure"


def test_compare_endpoint_contract(monkeypatch):
    app = FastAPI()
    app.include_router(pkg_router_module.router, prefix="/api/v1")

    expected_response = {
        "run_id": 321,
        "baseline_snapshot": {"id": 1, "version": "rules@1.0.0", "engine": "native", "checksum": "a"},
        "candidate_snapshot": {"id": 2, "version": "rules@1.1.0", "engine": "native", "checksum": "b"},
        "summary": {"behavior_changed": True, "decision_changed": False, "emissions": {"baseline": 1, "candidate": 1, "added": 0, "removed": 0, "changed": 1}, "dag": {"baseline": 0, "candidate": 0, "added": 0, "removed": 0}, "changed_rule_count": 1},
        "comparison": {
            "baseline": {
                "decision": {"allowed": True, "reason": "vip_route"},
                "emissions": {"subtasks": [], "dag": []},
                "provenance": {"rules": [], "snapshot": "rules@1.0.0"},
                "meta": {"mode": "advisory"},
            },
            "candidate": {
                "decision": {"allowed": True, "reason": "vip_route"},
                "emissions": {"subtasks": [], "dag": []},
                "provenance": {"rules": [], "snapshot": "rules@1.1.0"},
                "meta": {"mode": "advisory"},
            },
            "diff": {"emissions": [], "dag": [], "rules": []},
        },
    }

    class FakeCompareService:
        def __init__(self, pkg_client):
            self.pkg_client = pkg_client

        async def compare_snapshots(self, **kwargs):
            return expected_response

    monkeypatch.setattr(pkg_router_module, "PKGSnapshotCompareService", FakeCompareService)
    monkeypatch.setattr(pkg_router_module, "PKGClient", lambda session_factory: object())
    monkeypatch.setattr(pkg_router_module, "get_async_pg_session_factory", lambda: object())

    client = TestClient(app)
    response = client.post(
        "/api/v1/pkg/snapshots/compare",
        json={
            "baseline_snapshot_id": 1,
            "candidate_snapshot_id": 2,
            "task_facts": {"tags": ["vip"], "signals": {}, "context": {}},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["comparison"]["baseline"]["decision"]["allowed"] is True
    assert "provenance" in payload["comparison"]["baseline"]
    assert "meta" in payload["comparison"]["candidate"]
