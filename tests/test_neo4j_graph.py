#!/usr/bin/env python3
"""
Unit tests for Neo4jGraph backend.

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
from typing import List

from src.seedcore.memory.backends.neo4j_graph import Neo4jGraph


class TestNeo4jGraph:
    """Tests for Neo4jGraph class."""
    
    @pytest.fixture
    def mock_driver(self):
        """Create a mock Neo4j async driver."""
        driver = AsyncMock()
        driver.session.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        driver.session.return_value.__aexit__ = AsyncMock(return_value=None)
        driver.close = AsyncMock()
        return driver
    
    @pytest.fixture
    def neo4j_graph(self, mock_driver):
        """Create a Neo4jGraph instance with mocked driver."""
        with patch('src.seedcore.memory.backends.neo4j_graph.AsyncGraphDatabase.driver') as mock_driver_factory:
            mock_driver_factory.return_value = mock_driver
            graph = Neo4jGraph(
                uri="bolt://localhost:7687",
                auth=("neo4j", "password")
            )
            graph.driver = mock_driver
            return graph
    
    def test_init(self):
        """Test Neo4jGraph initialization."""
        with patch('src.seedcore.memory.backends.neo4j_graph.AsyncGraphDatabase.driver') as mock_driver_factory:
            mock_driver = AsyncMock()
            mock_driver_factory.return_value = mock_driver
            
            graph = Neo4jGraph(
                uri="bolt://localhost:7687",
                auth=("neo4j", "password")
            )
            
            assert graph.driver == mock_driver
            assert graph.database == "neo4j"
            mock_driver_factory.assert_called_once_with("bolt://localhost:7687", auth=("neo4j", "password"))
    
    @pytest.mark.asyncio
    async def test_upsert_edge_success(self, neo4j_graph, mock_driver):
        """Test successful edge upsert."""
        mock_session = AsyncMock()
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_session.run = AsyncMock()
        
        await neo4j_graph.upsert_edge("src-uuid", "RELATED_TO", "dst-uuid")
        
        mock_session.run.assert_called_once()
        call_args = mock_session.run.call_args
        # Check that the query contains the relationship type
        assert "RELATED_TO" in call_args[0][0]
    
    @pytest.mark.asyncio
    async def test_upsert_edge_invalid_relationship(self, neo4j_graph, mock_driver):
        """Test that invalid relationship types are sanitized."""
        mock_session = AsyncMock()
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_session.run = AsyncMock()
        
        # Use invalid relationship type (lowercase, not alphanumeric)
        await neo4j_graph.upsert_edge("src-uuid", "invalid-rel!", "dst-uuid")
        
        mock_session.run.assert_called_once()
        call_args = mock_session.run.call_args
        # Should default to RELATED_TO
        assert "RELATED_TO" in call_args[0][0]
    
    @pytest.mark.asyncio
    async def test_neighbors_with_relationship(self, neo4j_graph, mock_driver):
        """Test neighbors query with specific relationship type."""
        mock_session = AsyncMock()
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        
        # Mock result
        mock_record1 = Mock()
        mock_record1.__getitem__ = Mock(side_effect=lambda k: {"uuid": "neighbor1"}.get(k))
        mock_record2 = Mock()
        mock_record2.__getitem__ = Mock(side_effect=lambda k: {"uuid": "neighbor2"}.get(k))
        
        async def async_gen():
            yield mock_record1
            yield mock_record2
        
        mock_session.run.return_value = async_gen()
        
        result = await neo4j_graph.neighbors("test-uuid", rel="RELATED_TO", k=10)
        
        assert len(result) == 2
        assert "neighbor1" in result
        assert "neighbor2" in result
    
    @pytest.mark.asyncio
    async def test_neighbors_without_relationship(self, neo4j_graph, mock_driver):
        """Test neighbors query without relationship type."""
        mock_session = AsyncMock()
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        
        # Mock result
        mock_record = Mock()
        mock_record.__getitem__ = Mock(side_effect=lambda k: {"uuid": "neighbor1"}.get(k))
        
        async def async_gen():
            yield mock_record
        
        mock_session.run.return_value = async_gen()
        
        result = await neo4j_graph.neighbors("test-uuid", k=5)
        
        assert len(result) == 1
        assert "neighbor1" in result
    
    @pytest.mark.asyncio
    async def test_neighbors_empty_result(self, neo4j_graph, mock_driver):
        """Test neighbors returns empty list when no neighbors found."""
        mock_session = AsyncMock()
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        
        async def async_gen():
            return
            yield  # Make it an async generator
        
        mock_session.run.return_value = async_gen()
        
        result = await neo4j_graph.neighbors("test-uuid")
        
        assert result == []
    
    @pytest.mark.asyncio
    async def test_neighbors_error_handling(self, neo4j_graph, mock_driver):
        """Test neighbors handles errors gracefully."""
        mock_session = AsyncMock()
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_session.run = AsyncMock(side_effect=Exception("Connection error"))
        
        result = await neo4j_graph.neighbors("test-uuid")
        
        assert result == []
    
    @pytest.mark.asyncio
    async def test_get_neighbors_alias(self, neo4j_graph, mock_driver):
        """Test get_neighbors is an alias for neighbors."""
        mock_session = AsyncMock()
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        
        mock_record = Mock()
        mock_record.__getitem__ = Mock(side_effect=lambda k: {"uuid": "neighbor1"}.get(k))
        
        async def async_gen():
            yield mock_record
        
        mock_session.run.return_value = async_gen()
        
        result = await neo4j_graph.get_neighbors("test-uuid", k=5)
        
        assert len(result) == 1
        assert "neighbor1" in result
    
    @pytest.mark.asyncio
    async def test_get_count(self, neo4j_graph, mock_driver):
        """Test get_count returns relationship count."""
        mock_session = AsyncMock()
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        
        mock_record = Mock()
        mock_record.__getitem__ = Mock(side_effect=lambda k: {"count": 42}.get(k))
        mock_session.run.return_value.single = AsyncMock(return_value=mock_record)
        
        count = await neo4j_graph.get_count()
        
        assert count == 42
    
    @pytest.mark.asyncio
    async def test_get_count_no_record(self, neo4j_graph, mock_driver):
        """Test get_count returns 0 when no record found."""
        mock_session = AsyncMock()
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_session.run.return_value.single = AsyncMock(return_value=None)
        
        count = await neo4j_graph.get_count()
        
        assert count == 0
    
    @pytest.mark.asyncio
    async def test_get_count_error_handling(self, neo4j_graph, mock_driver):
        """Test get_count handles errors gracefully."""
        mock_session = AsyncMock()
        mock_driver.session.return_value.__aenter__.return_value = mock_session
        mock_session.run = AsyncMock(side_effect=Exception("Query error"))
        
        count = await neo4j_graph.get_count()
        
        assert count == 0
    
    @pytest.mark.asyncio
    async def test_close(self, neo4j_graph, mock_driver):
        """Test close properly closes the driver."""
        await neo4j_graph.close()
        
        mock_driver.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_close_no_driver(self, neo4j_graph, mock_driver):
        """Test close handles case when driver doesn't exist."""
        neo4j_graph.driver = None
        
        # Should not raise an exception
        await neo4j_graph.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
