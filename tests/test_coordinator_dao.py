"""
Unit tests for coordinator.dao module.

Tests DAO classes for telemetry, outbox, and proto plan persistence.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from seedcore.coordinator.dao import (
    GovernedExecutionAuditDAO,
    TaskRouterTelemetryDAO,
    TaskOutboxDAO,
    TaskProtoPlanDAO,
)


class TestTaskRouterTelemetryDAO:
    """Tests for TaskRouterTelemetryDAO."""
    
    @pytest.mark.asyncio
    async def test_insert_telemetry(self):
        """Test inserting router telemetry."""
        dao = TaskRouterTelemetryDAO()
        session = AsyncMock()
        session.execute = AsyncMock()
        
        await dao.insert(
            session,
            task_id="123",
            surprise_score=0.75,
            x_vector=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
            weights=[0.25, 0.20, 0.15, 0.20, 0.10, 0.10],
            ocps_metadata={"p_fast": 0.5},
            chosen_route="fast"
        )
        
        assert session.execute.called
        call_args = session.execute.call_args
        assert call_args is not None
    
    @pytest.mark.asyncio
    async def test_insert_with_custom_table(self):
        """Test inserting with custom table name."""
        dao = TaskRouterTelemetryDAO(table_name="custom_telemetry")
        session = AsyncMock()
        session.execute = AsyncMock()
        
        await dao.insert(
            session,
            task_id="123",
            surprise_score=0.5,
            x_vector=[0.1, 0.2],
            weights=[0.5, 0.5],
            ocps_metadata={},
            chosen_route="planner"
        )
        
        assert session.execute.called


class TestTaskOutboxDAO:
    """Tests for TaskOutboxDAO."""
    
    @pytest.mark.asyncio
    async def test_enqueue_nim_task_embed(self):
        """Test enqueuing a task embedding event."""
        dao = TaskOutboxDAO()
        session = AsyncMock()
        
        # Mock execute to return a result indicating insert succeeded
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.id = 1
        mock_result.fetchone.return_value = mock_row
        session.execute = AsyncMock(return_value=mock_result)
        
        result = await dao.enqueue_nim_task_embed(
            session,
            task_id="123",
            reason="coordinator"
        )
        
        assert result is True
        assert session.execute.called
    
    @pytest.mark.asyncio
    async def test_enqueue_with_dedupe_key(self):
        """Test enqueuing with deduplication key."""
        dao = TaskOutboxDAO()
        session = AsyncMock()
        
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.id = 1
        mock_result.fetchone.return_value = mock_row
        session.execute = AsyncMock(return_value=mock_result)
        
        result = await dao.enqueue_nim_task_embed(
            session,
            task_id="123",
            reason="coordinator",
            dedupe_key="unique-key-123"
        )
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_enqueue_duplicate_returns_false(self):
        """Test enqueuing duplicate returns False."""
        dao = TaskOutboxDAO()
        session = AsyncMock()
        
        # Mock execute to return None (duplicate)
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        session.execute = AsyncMock(return_value=mock_result)
        
        result = await dao.enqueue_nim_task_embed(
            session,
            task_id="123",
            reason="coordinator"
        )
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_claim_pending_nim_task_embeds(self):
        """Test claiming pending task embedding events."""
        dao = TaskOutboxDAO()
        session = AsyncMock()
        
        # Mock result with rows
        mock_result = MagicMock()
        mock_row1 = {"id": 1, "payload": json.dumps({"task_id": "123", "reason": "coordinator"})}
        mock_row2 = {"id": 2, "payload": json.dumps({"task_id": "456", "reason": "coordinator"})}
        mock_result.fetchall = AsyncMock(return_value=[mock_row1, mock_row2])
        session.execute = AsyncMock(return_value=mock_result)
        
        rows = await dao.claim_pending_nim_task_embeds(session, limit=10)
        
        assert len(rows) == 2
        assert rows[0]["id"] == 1
        assert rows[1]["id"] == 2
    
    @pytest.mark.asyncio
    async def test_delete(self):
        """Test deleting an outbox event."""
        dao = TaskOutboxDAO()
        session = AsyncMock()
        session.execute = AsyncMock()
        
        await dao.delete(session, event_id=1)
        
        assert session.execute.called
    
    @pytest.mark.asyncio
    async def test_backoff(self):
        """Test backing off a failed event."""
        dao = TaskOutboxDAO()
        session = AsyncMock()
        session.execute = AsyncMock()
        
        await dao.backoff(session, event_id=1)
        
        assert session.execute.called


class TestTaskProtoPlanDAO:
    """Tests for TaskProtoPlanDAO."""
    
    @pytest.mark.asyncio
    async def test_upsert_proto_plan(self):
        """Test upserting a proto plan."""
        dao = TaskProtoPlanDAO()
        session = AsyncMock()
        
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.truncated = False
        mock_result.fetchone.return_value = mock_row
        session.execute = AsyncMock(return_value=mock_result)
        
        proto_plan = {
            "steps": [
                {"organ_id": "organ-1", "task": {"type": "test"}},
                {"organ_id": "organ-2", "task": {"type": "test2"}}
            ]
        }
        
        result = await dao.upsert(
            session,
            task_id="123",
            route="fast",
            proto_plan=proto_plan
        )
        
        assert result["id"] == 1
        assert result["truncated"] is False
        assert session.execute.called
    
    @pytest.mark.asyncio
    async def test_upsert_truncates_large_plan(self):
        """Test upserting a proto plan that exceeds size limit."""
        dao = TaskProtoPlanDAO()
        session = AsyncMock()
        
        # Create a large proto plan
        large_plan = {
            "steps": [{"organ_id": f"organ-{i}"} for i in range(10000)]
        }
        large_json = json.dumps(large_plan)
        
        # Mock result indicating truncation
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.truncated = True
        mock_result.fetchone.return_value = mock_row
        session.execute = AsyncMock(return_value=mock_result)
        
        result = await dao.upsert(
            session,
            task_id="123",
            route="fast",
            proto_plan=large_plan
        )
        
        assert result["truncated"] is True
    
    @pytest.mark.asyncio
    async def test_get_by_task_id(self):
        """Test getting proto plan by task id."""
        dao = TaskProtoPlanDAO()
        session = AsyncMock()
        
        mock_result = MagicMock()
        mock_row = {
            "id": 1,
            "task_id": "123",
            "route": "fast",
            "proto_plan": json.dumps({"steps": []})
        }
        mock_result.fetchone = AsyncMock(return_value=mock_row)
        session.execute = AsyncMock(return_value=mock_result)
        
        result = await dao.get_by_task_id(session, task_id="123")
        
        assert result is not None
        assert result["task_id"] == "123"
        assert result["route"] == "fast"
    
    @pytest.mark.asyncio
    async def test_get_by_task_id_not_found(self):
        """Test getting proto plan when not found."""
        dao = TaskProtoPlanDAO()
        session = AsyncMock()
        
        mock_result = MagicMock()
        mock_result.fetchone = AsyncMock(return_value=None)
        session.execute = AsyncMock(return_value=mock_result)
        
        result = await dao.get_by_task_id(session, task_id="123")
        
        assert result is None


class TestGovernedExecutionAuditDAO:
    @pytest.mark.asyncio
    async def test_append_record_computes_hashes_and_returns_entry(self):
        dao = GovernedExecutionAuditDAO()
        session = AsyncMock()

        mock_result = MagicMock()
        mappings = MagicMock()
        mappings.one.return_value = {
            "id": "audit-1",
            "recorded_at": MagicMock(isoformat=MagicMock(return_value="2026-03-16T10:00:00+00:00")),
        }
        mock_result.mappings.return_value = mappings
        session.execute = AsyncMock(return_value=mock_result)

        result = await dao.append_record(
            session,
            task_id="123e4567-e89b-12d3-a456-426614174000",
            record_type="execution_receipt",
            intent_id="intent-1",
            token_id="token-1",
            policy_snapshot="snapshot:1",
            policy_decision={"allowed": True},
            action_intent={"intent_id": "intent-1"},
            policy_case={"action_intent": {"intent_id": "intent-1"}},
            evidence_bundle={"intent_ref": "governance://action-intent/intent-1"},
            actor_agent_id="agent-1",
            actor_organ_id="organ-1",
        )

        assert result["entry_id"] == "audit-1"
        assert result["recorded_at"] == "2026-03-16T10:00:00+00:00"
        assert isinstance(result["input_hash"], str)
        assert len(result["input_hash"]) == 64
        assert isinstance(result["evidence_hash"], str)
        assert len(result["evidence_hash"]) == 64

    @pytest.mark.asyncio
    async def test_list_for_task_returns_normalized_rows(self):
        dao = GovernedExecutionAuditDAO()
        session = AsyncMock()

        mock_result = MagicMock()
        mappings = MagicMock()
        mappings.all.return_value = [
            {
                "id": "audit-1",
                "task_id": "123e4567-e89b-12d3-a456-426614174000",
                "record_type": "policy_decision",
                "intent_id": "intent-1",
                "token_id": "token-1",
                "policy_snapshot": "snapshot:1",
                "policy_decision": {"allowed": True},
                "action_intent": {"intent_id": "intent-1"},
                "policy_case": {"action_intent": {"intent_id": "intent-1"}},
                "evidence_bundle": {},
                "actor_agent_id": None,
                "actor_organ_id": None,
                "input_hash": "a" * 64,
                "evidence_hash": None,
                "recorded_at": MagicMock(isoformat=MagicMock(return_value="2026-03-16T10:00:00+00:00")),
            }
        ]
        mock_result.mappings.return_value = mappings
        session.execute = AsyncMock(return_value=mock_result)

        rows = await dao.list_for_task(
            session,
            task_id="123e4567-e89b-12d3-a456-426614174000",
            limit=10,
        )

        assert len(rows) == 1
        assert rows[0]["record_type"] == "policy_decision"
        assert rows[0]["intent_id"] == "intent-1"

    @pytest.mark.asyncio
    async def test_get_latest_for_intent_returns_first_row(self):
        dao = GovernedExecutionAuditDAO()
        session = AsyncMock()

        mock_result = MagicMock()
        mappings = MagicMock()
        mappings.all.return_value = [
            {
                "id": "audit-2",
                "task_id": "123e4567-e89b-12d3-a456-426614174000",
                "record_type": "execution_receipt",
                "intent_id": "intent-2",
                "token_id": "token-2",
                "policy_snapshot": "snapshot:2",
                "policy_decision": {"allowed": True},
                "action_intent": {"intent_id": "intent-2"},
                "policy_case": {},
                "policy_receipt": {"receipt_id": "policy-r-2"},
                "evidence_bundle": {"intent_ref": "governance://action-intent/intent-2"},
                "actor_agent_id": "agent-2",
                "actor_organ_id": "organ-2",
                "input_hash": "b" * 64,
                "evidence_hash": "c" * 64,
                "recorded_at": MagicMock(isoformat=MagicMock(return_value="2026-03-16T11:00:00+00:00")),
            }
        ]
        mock_result.mappings.return_value = mappings
        session.execute = AsyncMock(return_value=mock_result)

        row = await dao.get_latest_for_intent(session, intent_id="intent-2")

        assert row is not None
        assert row["intent_id"] == "intent-2"
        assert row["policy_receipt"]["receipt_id"] == "policy-r-2"

    @pytest.mark.asyncio
    async def test_get_by_entry_id_returns_row(self):
        dao = GovernedExecutionAuditDAO()
        session = AsyncMock()

        mock_result = MagicMock()
        mappings = MagicMock()
        mappings.one_or_none.return_value = {
            "id": "audit-3",
            "task_id": "123e4567-e89b-12d3-a456-426614174000",
            "record_type": "policy_decision",
            "intent_id": "intent-3",
            "token_id": "token-3",
            "policy_snapshot": "snapshot:3",
            "policy_decision": {"allowed": False},
            "action_intent": {"intent_id": "intent-3"},
            "policy_case": {},
            "policy_receipt": {"receipt_id": "policy-r-3"},
            "evidence_bundle": {},
            "actor_agent_id": "agent-3",
            "actor_organ_id": "organ-3",
            "input_hash": "d" * 64,
            "evidence_hash": None,
            "recorded_at": MagicMock(isoformat=MagicMock(return_value="2026-03-16T12:00:00+00:00")),
        }
        mock_result.mappings.return_value = mappings
        session.execute = AsyncMock(return_value=mock_result)

        row = await dao.get_by_entry_id(
            session,
            entry_id="123e4567-e89b-12d3-a456-426614174000",
        )

        assert row is not None
        assert row["id"] == "audit-3"
        assert row["policy_receipt"]["receipt_id"] == "policy-r-3"

    @pytest.mark.asyncio
    async def test_search_transition_records_uses_current_filters_and_normalizes_rows(self):
        dao = GovernedExecutionAuditDAO()
        session = AsyncMock()

        mock_result = MagicMock()
        mappings = MagicMock()
        mappings.all.return_value = [
            {
                "id": "audit-4",
                "task_id": "123e4567-e89b-12d3-a456-426614174000",
                "record_type": "policy_decision",
                "intent_id": "intent-4",
                "token_id": "token-4",
                "policy_snapshot": "snapshot:4",
                "policy_decision": {
                    "disposition": "quarantine",
                    "authz_graph": {"disposition": "quarantine", "reason": "trust_gap_quarantine"},
                    "governed_receipt": {"decision_hash": "receipt-4", "asset_ref": "asset-4", "trust_gap_codes": ["stale_telemetry"]},
                },
                "action_intent": {"intent_id": "intent-4", "resource": {"asset_id": "asset-4"}},
                "policy_case": {},
                "policy_receipt": {"asset_ref": "asset-4"},
                "evidence_bundle": {},
                "actor_agent_id": "agent-4",
                "actor_organ_id": "organ-4",
                "input_hash": "e" * 64,
                "evidence_hash": None,
                "recorded_at": MagicMock(isoformat=MagicMock(return_value="2026-03-16T13:00:00+00:00")),
            }
        ]
        mock_result.mappings.return_value = mappings
        session.execute = AsyncMock(return_value=mock_result)

        rows = await dao.search_transition_records(
            session,
            asset_id="asset-4",
            disposition="quarantine",
            trust_gap_code="stale_telemetry",
            current_only=True,
            limit=10,
            offset=2,
        )

        assert len(rows) == 1
        assert rows[0]["policy_decision"]["governed_receipt"]["decision_hash"] == "receipt-4"
        stmt, params = session.execute.await_args.args
        assert "ROW_NUMBER() OVER" in str(stmt)
        assert "row_num = 1" in str(stmt)
        assert params["asset_id"] == "asset-4"
        assert params["disposition"] == "quarantine"
        assert params["trust_gap_code"] == "stale_telemetry"
        assert params["limit"] == 10
        assert params["offset"] == 2

    @pytest.mark.asyncio
    async def test_summarize_transition_records_returns_disposition_and_trust_gap_facets(self):
        dao = GovernedExecutionAuditDAO()
        session = AsyncMock()

        summary_result = MagicMock()
        summary_mappings = MagicMock()
        summary_mappings.one.return_value = {
            "total": 3,
            "allow_count": 1,
            "deny_count": 1,
            "quarantine_count": 1,
        }
        summary_result.mappings.return_value = summary_mappings

        trust_gap_result = MagicMock()
        trust_gap_mappings = MagicMock()
        trust_gap_mappings.all.return_value = [
            {"trust_gap_code": "stale_telemetry", "count": 2},
            {"trust_gap_code": "route_violation", "count": 1},
        ]
        trust_gap_result.mappings.return_value = trust_gap_mappings
        session.execute = AsyncMock(side_effect=[summary_result, trust_gap_result])

        facets = await dao.summarize_transition_records(
            session,
            disposition="quarantine",
            trust_gap_code="stale_telemetry",
            current_only=True,
        )

        assert facets["total"] == 3
        assert facets["restricted_count"] == 2
        assert facets["dispositions"] == [
            {"value": "allow", "count": 1},
            {"value": "deny", "count": 1},
            {"value": "quarantine", "count": 1},
        ]
        assert facets["trust_gap_codes"] == [
            {"value": "stale_telemetry", "count": 2},
            {"value": "route_violation", "count": 1},
        ]
        assert session.execute.await_count == 2
