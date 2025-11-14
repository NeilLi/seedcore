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

