#!/usr/bin/env python3
"""
Unit tests for HolonFabric.

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
from unittest.mock import Mock, AsyncMock, MagicMock, patch
import numpy as np

from src.seedcore.memory.backends.pgvector_backend import PgVectorStore, Holon
from src.seedcore.memory.backends.neo4j_graph import Neo4jGraph
from src.seedcore.memory.holon_fabric import HolonFabric, uuid_vec


class TestHolonFabric:
    """Tests for HolonFabric class."""
    
    @pytest.fixture
    def mock_vec_store(self):
        """Create a mock PgVectorStore."""
        vec_store = Mock(spec=PgVectorStore)
        vec_store.upsert = AsyncMock(return_value=True)
        vec_store.search = AsyncMock(return_value=[])
        vec_store.get_count = AsyncMock(return_value=100)
        vec_store.execute_scalar_query = AsyncMock(return_value=1024000)
        return vec_store
    
    @pytest.fixture
    def mock_graph(self):
        """Create a mock Neo4jGraph."""
        graph = Mock(spec=Neo4jGraph)
        graph.neighbors = AsyncMock(return_value=[])
        graph.upsert_edge = AsyncMock()
        graph.get_count = AsyncMock(return_value=50)
        return graph
    
    @pytest.fixture
    def fabric(self, mock_vec_store, mock_graph):
        """Create a HolonFabric instance with mocked backends."""
        return HolonFabric(mock_vec_store, mock_graph)
    
    @pytest.mark.asyncio
    async def test_insert_holon(self, fabric, mock_vec_store):
        """Test inserting a holon."""
        embedding = np.random.randn(768).astype(np.float32)
        holon = Holon(
            uuid="test-uuid",
            embedding=embedding,
            meta={"key": "value"}
        )
        
        await fabric.insert_holon(holon)
        
        mock_vec_store.upsert.assert_called_once_with(holon)
    
    @pytest.mark.asyncio
    async def test_query_exact_found(self, fabric, mock_vec_store, mock_graph):
        """Test query_exact when holon is found."""
        # Mock vector search result
        mock_record = Mock()
        mock_record.__getitem__ = Mock(side_effect=lambda k: {
            "uuid": "test-uuid",
            "meta": {"key": "value"},
            "dist": 0.5
        }.get(k))
        mock_vec_store.search = AsyncMock(return_value=[mock_record])
        mock_graph.neighbors = AsyncMock(return_value=["neighbor1", "neighbor2"])
        
        result = await fabric.query_exact("test-uuid")
        
        assert "meta" in result
        assert "neighbors" in result
        assert result["meta"]["uuid"] == "test-uuid"
        assert len(result["neighbors"]) == 2
    
    @pytest.mark.asyncio
    async def test_query_exact_not_found(self, fabric, mock_vec_store, mock_graph):
        """Test query_exact when holon is not found."""
        mock_vec_store.search = AsyncMock(return_value=[])
        mock_graph.neighbors = AsyncMock(return_value=[])
        
        result = await fabric.query_exact("non-existent-uuid")
        
        assert result["meta"] is None
        assert result["neighbors"] == []
    
    @pytest.mark.asyncio
    async def test_query_exact_handles_inf_dist(self, fabric, mock_vec_store, mock_graph):
        """Test query_exact handles infinite distance values."""
        mock_record = Mock()
        mock_record.__getitem__ = Mock(side_effect=lambda k: {
            "uuid": "test-uuid",
            "meta": {"key": "value"},
            "dist": np.inf
        }.get(k))
        mock_vec_store.search = AsyncMock(return_value=[mock_record])
        mock_graph.neighbors = AsyncMock(return_value=[])
        
        result = await fabric.query_exact("test-uuid")
        
        assert result["meta"]["dist"] == 0.0
    
    @pytest.mark.asyncio
    async def test_query_exact_error_handling(self, fabric, mock_vec_store, mock_graph):
        """Test query_exact handles errors gracefully."""
        mock_vec_store.search = AsyncMock(side_effect=Exception("DB error"))
        mock_graph.neighbors = AsyncMock(return_value=[])
        
        result = await fabric.query_exact("test-uuid")
        
        assert result["meta"] is None
        assert result["neighbors"] == []
        assert "error" in result
    
    @pytest.mark.asyncio
    async def test_query_fuzzy(self, fabric, mock_vec_store, mock_graph):
        """Test fuzzy query with hop expansion."""
        # Mock vector search results
        mock_record1 = Mock()
        mock_record1.__getitem__ = Mock(side_effect=lambda k: {"uuid": "uuid1"}.get(k))
        mock_record2 = Mock()
        mock_record2.__getitem__ = Mock(side_effect=lambda k: {"uuid": "uuid2"}.get(k))
        mock_vec_store.search = AsyncMock(return_value=[mock_record1, mock_record2])
        mock_graph.neighbors = AsyncMock(side_effect=[
            ["neighbor1", "neighbor2"],  # neighbors for uuid1
            ["neighbor3"]  # neighbors for uuid2
        ])
        
        embedding = np.random.randn(768).astype(np.float32)
        result = await fabric.query_fuzzy(embedding, k=10)
        
        assert "uuid1" in result
        assert "uuid2" in result
        assert "neighbor1" in result
        assert "neighbor2" in result
        assert "neighbor3" in result
    
    @pytest.mark.asyncio
    async def test_create_relationship(self, fabric, mock_graph):
        """Test creating a relationship between holons."""
        await fabric.create_relationship("src-uuid", "RELATED_TO", "dst-uuid")
        
        mock_graph.upsert_edge.assert_called_once_with("src-uuid", "RELATED_TO", "dst-uuid")
    
    @pytest.mark.asyncio
    async def test_get_stats_success(self, fabric, mock_vec_store, mock_graph):
        """Test get_stats returns correct statistics."""
        mock_vec_store.get_count = AsyncMock(return_value=100)
        mock_vec_store.execute_scalar_query = AsyncMock(return_value=1024000)
        mock_graph.get_count = AsyncMock(return_value=50)
        
        stats = await fabric.get_stats()
        
        assert stats["total_holons"] == 100
        assert stats["total_relationships"] == 50
        assert stats["bytes_used"] == 1024000
        assert stats["vector_dimensions"] == 768
        assert stats["status"] == "healthy"
    
    @pytest.mark.asyncio
    async def test_get_stats_error_handling(self, fabric, mock_vec_store, mock_graph):
        """Test get_stats handles errors gracefully."""
        mock_vec_store.get_count = AsyncMock(side_effect=Exception("DB error"))
        mock_graph.get_count = AsyncMock(return_value=0)
        
        stats = await fabric.get_stats()
        
        assert stats["status"] == "unhealthy"
        assert "error" in stats
        assert stats["total_holons"] == 0
        assert stats["total_relationships"] == 0


class TestUuidVec:
    """Tests for uuid_vec helper function."""
    
    def test_uuid_vec_returns_array(self):
        """Test that uuid_vec returns a numpy array."""
        result = uuid_vec("test-uuid-123")
        
        assert isinstance(result, np.ndarray)
        assert result.dtype == np.float32
    
    def test_uuid_vec_has_correct_dimensions(self):
        """Test that uuid_vec returns 768-dimensional vector."""
        result = uuid_vec("test-uuid-123")
        
        assert result.shape == (768,)
    
    def test_uuid_vec_deterministic(self):
        """Test that uuid_vec returns the same result for same input."""
        uuid = "test-uuid-123"
        result1 = uuid_vec(uuid)
        result2 = uuid_vec(uuid)
        
        np.testing.assert_array_equal(result1, result2)
    
    def test_uuid_vec_different_for_different_uuids(self):
        """Test that uuid_vec returns different results for different UUIDs."""
        result1 = uuid_vec("uuid-1")
        result2 = uuid_vec("uuid-2")
        
        # Should be different (very unlikely to be the same)
        assert not np.array_equal(result1, result2)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
