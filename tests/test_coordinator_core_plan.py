"""
Unit tests for coordinator.core.plan module.

Tests plan persistence and dependency registration functionality.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock
from seedcore.coordinator.core.plan import (
    persist_and_register_dependencies,
    _read_task_id,
)


class TestReadTaskId:
    """Tests for _read_task_id function."""
    
    def test_read_from_dict(self):
        """Test reading task id from dictionary."""
        task = {"id": "123"}
        task_id = _read_task_id(task)
        assert task_id == "123"
    
    def test_read_from_object(self):
        """Test reading task id from object."""
        task = Mock()
        task.id = "123"
        task_id = _read_task_id(task)
        assert task_id == "123"
    
    def test_read_from_task_id_key(self):
        """Test reading task id from task_id key."""
        task = {"task_id": "456"}
        task_id = _read_task_id(task)
        assert task_id == "456"


@pytest.mark.asyncio
class TestPersistAndRegisterDependencies:
    """Tests for persist_and_register_dependencies function."""
    
    async def test_persist_empty_plan(self):
        """Test persisting empty plan returns empty list."""
        repo = Mock()
        task = {"id": "123"}
        
        result = await persist_and_register_dependencies(
            plan=[],
            repo=repo,
            task=task,
            root_db_id=None
        )
        
        assert result == []
        repo.insert_subtasks.assert_not_called()
    
    async def test_persist_with_repo(self):
        """Test persisting plan with valid repository."""
        repo = Mock()
        repo.insert_subtasks = AsyncMock(return_value=[
            {"id": "subtask-1", "task_id": "sub-1"},
            {"id": "subtask-2", "task_id": "sub-2"}
        ])
        repo.add_dependency = AsyncMock()
        
        plan = [
            {"organ_id": "organ-1", "task": {"type": "test1"}},
            {"organ_id": "organ-2", "task": {"type": "test2"}}
        ]
        task = {"id": "root-123"}
        
        result = await persist_and_register_dependencies(
            plan=plan,
            repo=repo,
            task=task,
            root_db_id="root-db-id"
        )
        
        assert len(result) == 2
        repo.insert_subtasks.assert_called_once()
        # Should add dependencies from root to children
        assert repo.add_dependency.call_count == 2
    
    async def test_persist_without_root_db_id(self):
        """Test persisting plan without root_db_id."""
        repo = Mock()
        repo.insert_subtasks = AsyncMock(return_value=[
            {"id": "subtask-1", "task_id": "sub-1"}
        ])
        repo.add_dependency = AsyncMock()
        
        plan = [{"organ_id": "organ-1", "task": {"type": "test1"}}]
        task = {"id": "root-123"}
        
        result = await persist_and_register_dependencies(
            plan=plan,
            repo=repo,
            task=task,
            root_db_id=None
        )
        
        assert len(result) == 1
        # Should not add dependencies without root_db_id
        repo.add_dependency.assert_not_called()
    
    async def test_persist_with_inter_subtask_dependencies(self):
        """Test persisting plan with inter-subtask dependencies."""
        repo = Mock()
        repo.insert_subtasks = AsyncMock(return_value=[
            {"id": "subtask-1", "task_id": "sub-1"},
            {"id": "subtask-2", "task_id": "sub-2"},
            {"id": "subtask-3", "task_id": "sub-3"}
        ])
        repo.add_dependency = AsyncMock()
        
        plan = [
            {"organ_id": "organ-1", "task": {"type": "test1"}, "depends_on": []},
            {"organ_id": "organ-2", "task": {"type": "test2"}, "depends_on": [0]},
            {"organ_id": "organ-3", "task": {"type": "test3"}, "depends_on": [0, 1]}
        ]
        task = {"id": "root-123"}
        
        result = await persist_and_register_dependencies(
            plan=plan,
            repo=repo,
            task=task,
            root_db_id="root-db-id"
        )
        
        assert len(result) == 3
        # Should add root->child dependencies (3) + inter-subtask dependencies
        # Total calls should be at least 3 (root->child) + inter-subtask edges
        assert repo.add_dependency.call_count >= 3
    
    async def test_persist_repo_insert_failure(self):
        """Test persisting when repo.insert_subtasks fails."""
        repo = Mock()
        repo.insert_subtasks = AsyncMock(side_effect=Exception("DB error"))
        
        plan = [{"organ_id": "organ-1", "task": {"type": "test1"}}]
        task = {"id": "root-123"}
        
        result = await persist_and_register_dependencies(
            plan=plan,
            repo=repo,
            task=task,
            root_db_id=None
        )
        
        assert result == []
    
    async def test_persist_no_repo(self):
        """Test persisting when repository is None."""
        plan = [{"organ_id": "organ-1", "task": {"type": "test1"}}]
        task = {"id": "root-123"}
        
        result = await persist_and_register_dependencies(
            plan=plan,
            repo=None,
            task=task,
            root_db_id=None
        )
        
        assert result == []
    
    async def test_persist_repo_missing_method(self):
        """Test persisting when repository lacks insert_subtasks method."""
        repo = Mock(spec=[])  # No methods
        plan = [{"organ_id": "organ-1", "task": {"type": "test1"}}]
        task = {"id": "root-123"}
        
        result = await persist_and_register_dependencies(
            plan=plan,
            repo=repo,
            task=task,
            root_db_id=None
        )
        
        assert result == []
    
    async def test_persist_sync_repo(self):
        """Test persisting with synchronous repository methods."""
        repo = Mock()
        # Simulate sync method (not async)
        repo.insert_subtasks = Mock(return_value=[
            {"id": "subtask-1", "task_id": "sub-1"}
        ])
        repo.add_dependency = Mock()
        
        plan = [{"organ_id": "organ-1", "task": {"type": "test1"}}]
        task = {"id": "root-123"}
        
        result = await persist_and_register_dependencies(
            plan=plan,
            repo=repo,
            task=task,
            root_db_id="root-db-id"
        )
        
        assert len(result) == 1
        repo.insert_subtasks.assert_called_once()
        repo.add_dependency.assert_called_once()

