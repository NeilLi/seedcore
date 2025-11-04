#!/usr/bin/env python3
"""
Unit tests for LongTermMemoryManager.

Tests are independent of Ray and Kubernetes cluster dependencies.
"""

import sys
import os

# Add tests directory to path for mock imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import mocks BEFORE other imports
import mock_database_dependencies
import mock_ray_dependencies

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch, call
import numpy as np

from src.seedcore.memory.long_term_memory import LongTermMemoryManager


class TestLongTermMemoryManager:
    """Tests for LongTermMemoryManager class."""
    
    @pytest.fixture
    def mock_pg_store(self):
        """Create a mock PgVectorStore."""
        pg_store = Mock()
        pg_store.upsert = AsyncMock(return_value=True)
        pg_store.get_by_id = AsyncMock(return_value=None)
        pg_store._get_pool = AsyncMock()
        pg_store.close = AsyncMock()
        return pg_store
    
    @pytest.fixture
    def mock_neo4j_graph(self):
        """Create a mock Neo4jGraph."""
        graph = Mock()
        graph.upsert_edge = AsyncMock()
        graph.close = AsyncMock()
        return graph
    
    @pytest.fixture
    def ltm_manager(self, mock_pg_store, mock_neo4j_graph):
        """Create a LongTermMemoryManager with mocked backends."""
        with patch('src.seedcore.memory.long_term_memory.PgVectorStore') as mock_pg_class, \
             patch('src.seedcore.memory.long_term_memory.Neo4jGraph') as mock_neo4j_class:
            mock_pg_class.return_value = mock_pg_store
            mock_neo4j_class.return_value = mock_neo4j_graph
            
            manager = LongTermMemoryManager()
            manager.pg_store = mock_pg_store
            manager.neo4j_graph = mock_neo4j_graph
            return manager
    
    @pytest.mark.asyncio
    async def test_initialize(self, ltm_manager, mock_pg_store):
        """Test async initialization."""
        mock_pg_store._get_pool = AsyncMock()
        
        await ltm_manager.initialize()
        
        mock_pg_store._get_pool.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_query_holon_by_id_async_found(self, ltm_manager, mock_pg_store):
        """Test query_holon_by_id_async when holon is found."""
        from src.seedcore.memory.backends.pgvector_backend import Holon
        
        holon = Holon(
            uuid="test-uuid-123",
            embedding=np.array([1.0, 2.0, 3.0]),
            meta={"key": "value"}
        )
        mock_pg_store.get_by_id = AsyncMock(return_value=holon)
        
        result = await ltm_manager.query_holon_by_id_async("test-uuid-123")
        
        assert result is not None
        assert result["id"] == "test-uuid-123"
        assert result["meta"] == {"key": "value"}
        assert isinstance(result["embedding"], list)
    
    @pytest.mark.asyncio
    async def test_query_holon_by_id_async_not_found(self, ltm_manager, mock_pg_store):
        """Test query_holon_by_id_async when holon is not found."""
        mock_pg_store.get_by_id = AsyncMock(return_value=None)
        
        result = await ltm_manager.query_holon_by_id_async("non-existent-uuid")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_query_holon_by_id_async_error(self, ltm_manager, mock_pg_store):
        """Test query_holon_by_id_async handles errors gracefully."""
        mock_pg_store.get_by_id = AsyncMock(side_effect=Exception("DB error"))
        
        result = await ltm_manager.query_holon_by_id_async("test-uuid")
        
        assert result is None
    
    def test_query_holon_by_id_sync_found(self, ltm_manager, mock_pg_store):
        """Test query_holon_by_id when holon is found (sync version)."""
        from src.seedcore.memory.backends.pgvector_backend import Holon
        
        holon = Holon(
            uuid="test-uuid-123",
            embedding=np.array([1.0, 2.0, 3.0]),
            meta={"key": "value"}
        )
        
        # Mock async call in sync context
        async def get_by_id_async(uuid):
            return holon
        
        mock_pg_store.get_by_id = AsyncMock(side_effect=get_by_id_async)
        
        result = ltm_manager.query_holon_by_id("test-uuid-123")
        
        assert result is not None
        assert result["id"] == "test-uuid-123"
        assert result["meta"] == {"key": "value"}
    
    def test_query_holon_by_id_sync_not_found(self, ltm_manager, mock_pg_store):
        """Test query_holon_by_id when holon is not found (sync version)."""
        async def get_by_id_async(uuid):
            return None
        
        mock_pg_store.get_by_id = AsyncMock(side_effect=get_by_id_async)
        
        result = ltm_manager.query_holon_by_id("non-existent-uuid")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_insert_holon_async_success(self, ltm_manager, mock_pg_store, mock_neo4j_graph):
        """Test successful async holon insertion."""
        mock_pg_store.upsert = AsyncMock(return_value=True)
        mock_neo4j_graph.upsert_edge = AsyncMock()
        
        holon_data = {
            "vector": {
                "id": "test-uuid-123",
                "embedding": [1.0, 2.0, 3.0],
                "meta": {"key": "value"}
            },
            "graph": {
                "src_uuid": "src-uuid",
                "rel": "RELATED_TO",
                "dst_uuid": "dst-uuid"
            }
        }
        
        result = await ltm_manager.insert_holon_async(holon_data)
        
        assert result is True
        mock_pg_store.upsert.assert_called_once()
        mock_neo4j_graph.upsert_edge.assert_called_once_with(
            "src-uuid", "RELATED_TO", "dst-uuid"
        )
    
    @pytest.mark.asyncio
    async def test_insert_holon_async_no_graph(self, ltm_manager, mock_pg_store, mock_neo4j_graph):
        """Test async holon insertion without graph data."""
        mock_pg_store.upsert = AsyncMock(return_value=True)
        
        holon_data = {
            "vector": {
                "id": "test-uuid-123",
                "embedding": [1.0, 2.0, 3.0],
                "meta": {"key": "value"}
            }
        }
        
        result = await ltm_manager.insert_holon_async(holon_data)
        
        assert result is True
        mock_pg_store.upsert.assert_called_once()
        mock_neo4j_graph.upsert_edge.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_insert_holon_async_failure(self, ltm_manager, mock_pg_store):
        """Test async holon insertion handles failures."""
        mock_pg_store.upsert = AsyncMock(return_value=False)
        
        holon_data = {
            "vector": {
                "id": "test-uuid-123",
                "embedding": [1.0, 2.0, 3.0],
                "meta": {"key": "value"}
            }
        }
        
        result = await ltm_manager.insert_holon_async(holon_data)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_insert_holon_async_error(self, ltm_manager, mock_pg_store):
        """Test async holon insertion handles errors gracefully."""
        mock_pg_store.upsert = AsyncMock(side_effect=Exception("DB error"))
        
        holon_data = {
            "vector": {
                "id": "test-uuid-123",
                "embedding": [1.0, 2.0, 3.0],
                "meta": {"key": "value"}
            }
        }
        
        result = await ltm_manager.insert_holon_async(holon_data)
        
        assert result is False
    
    def test_insert_holon_sync_success(self, ltm_manager, mock_pg_store, mock_neo4j_graph):
        """Test successful sync holon insertion."""
        mock_pg_store.upsert = AsyncMock(return_value=True)
        mock_neo4j_graph.upsert_edge = AsyncMock()
        
        holon_data = {
            "vector": {
                "id": "test-uuid-123",
                "embedding": [1.0, 2.0, 3.0],
                "meta": {"key": "value"}
            },
            "graph": {
                "src_uuid": "src-uuid",
                "rel": "RELATED_TO",
                "dst_uuid": "dst-uuid"
            }
        }
        
        result = ltm_manager.insert_holon(holon_data)
        
        assert result is True
        mock_pg_store.upsert.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_close(self, ltm_manager, mock_pg_store, mock_neo4j_graph):
        """Test close properly closes all connections."""
        await ltm_manager.close()
        
        mock_pg_store.close.assert_called_once()
        mock_neo4j_graph.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_close_no_pg_store(self, ltm_manager, mock_neo4j_graph):
        """Test close handles missing pg_store gracefully."""
        ltm_manager.pg_store = None
        
        await ltm_manager.close()
        
        mock_neo4j_graph.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_close_no_neo4j_graph(self, ltm_manager, mock_pg_store):
        """Test close handles missing neo4j_graph gracefully."""
        ltm_manager.neo4j_graph = None
        
        await ltm_manager.close()
        
        mock_pg_store.close.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
