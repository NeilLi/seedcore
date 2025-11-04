#!/usr/bin/env python3
"""
Unit tests for PgVectorStore backend.

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
from uuid import uuid4

from src.seedcore.memory.backends.pgvector_backend import PgVectorStore, Holon


class TestHolon:
    """Tests for Holon Pydantic model."""
    
    def test_holon_creation(self):
        """Test creating a Holon with all fields."""
        embedding = np.random.randn(768).astype(np.float32)
        meta = {"test": "data", "number": 42}
        
        holon = Holon(
            uuid="test-uuid-123",
            embedding=embedding,
            meta=meta
        )
        
        assert holon.uuid == "test-uuid-123"
        np.testing.assert_array_equal(holon.embedding, embedding)
        assert holon.meta == meta
    
    def test_holon_default_uuid(self):
        """Test that Holon generates a UUID if not provided."""
        embedding = np.random.randn(768).astype(np.float32)
        holon = Holon(embedding=embedding, meta={})
        
        assert holon.uuid is not None
        assert isinstance(holon.uuid, str)
        assert len(holon.uuid) > 0


class TestPgVectorStore:
    """Tests for PgVectorStore class."""
    
    @pytest.fixture
    def mock_pool(self):
        """Create a mock asyncpg pool."""
        pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_conn.fetchrow = AsyncMock(return_value=None)
        
        # Create a proper async context manager for acquire()
        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_context.__aexit__ = AsyncMock(return_value=None)
        
        pool.acquire = Mock(return_value=mock_context)
        pool.close = AsyncMock()
        return pool
    
    @pytest.fixture
    def pg_store(self):
        """Create a PgVectorStore instance."""
        return PgVectorStore(
            dsn="postgresql://user:pass@localhost/test",
            pool_size=5,
            pool_min_size=2
        )
    
    @pytest.mark.asyncio
    async def test_get_pool_creates_pool(self, pg_store, mock_pool):
        """Test that _get_pool creates a connection pool."""
        with patch('src.seedcore.memory.backends.pgvector_backend.asyncpg.create_pool', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_pool
            
            pool = await pg_store._get_pool()
            
            assert pool == mock_pool
            mock_create.assert_called_once()
            call_args = mock_create.call_args
            assert call_args[1]['min_size'] == 2
            assert call_args[1]['max_size'] == 5
    
    @pytest.mark.asyncio
    async def test_get_pool_lazy_initialization(self, pg_store, mock_pool):
        """Test that pool is only created once (lazy initialization)."""
        with patch('src.seedcore.memory.backends.pgvector_backend.asyncpg.create_pool', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_pool
            
            pool1 = await pg_store._get_pool()
            pool2 = await pg_store._get_pool()
            
            assert pool1 == pool2 == mock_pool
            # Should only create pool once
            assert mock_create.call_count == 1
    
    @pytest.mark.asyncio
    async def test_upsert_success(self, pg_store, mock_pool):
        """Test successful upsert operation."""
        pg_store._pool = mock_pool
        mock_conn = mock_pool.acquire.return_value.__aenter__.return_value
        
        embedding = np.random.randn(768).astype(np.float32)
        holon = Holon(
            uuid="test-uuid-123",
            embedding=embedding,
            meta={"key": "value"}
        )
        
        result = await pg_store.upsert(holon)
        
        assert result is True
        mock_conn.execute.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_upsert_failure(self, pg_store, mock_pool):
        """Test upsert handles errors gracefully."""
        pg_store._pool = mock_pool
        mock_conn = mock_pool.acquire.return_value.__aenter__.return_value
        mock_conn.execute = AsyncMock(side_effect=Exception("DB error"))
        
        embedding = np.random.randn(768).astype(np.float32)
        holon = Holon(uuid="test-uuid", embedding=embedding, meta={})
        
        result = await pg_store.upsert(holon)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_search(self, pg_store, mock_pool):
        """Test vector similarity search."""
        pg_store._pool = mock_pool
        mock_conn = mock_pool.acquire.return_value.__aenter__.return_value
        
        # Mock fetch results
        mock_record1 = Mock()
        mock_record1.__getitem__ = Mock(side_effect=lambda k: {
            "uuid": "uuid1",
            "meta": {"key": "value1"},
            "dist": 0.5
        }.get(k))
        mock_record2 = Mock()
        mock_record2.__getitem__ = Mock(side_effect=lambda k: {
            "uuid": "uuid2",
            "meta": {"key": "value2"},
            "dist": 0.7
        }.get(k))
        mock_conn.fetch = AsyncMock(return_value=[mock_record1, mock_record2])
        
        embedding = np.random.randn(768).astype(np.float32)
        results = await pg_store.search(embedding, k=10)
        
        assert len(results) == 2
        mock_conn.fetch.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_search_empty_result(self, pg_store, mock_pool):
        """Test search returns empty list when no results."""
        pg_store._pool = mock_pool
        mock_conn = AsyncMock()
        mock_conn = mock_pool.acquire.return_value.__aenter__.return_value
        mock_conn.fetch = AsyncMock(return_value=[])
        
        embedding = np.random.randn(768).astype(np.float32)
        results = await pg_store.search(embedding, k=10)
        
        assert results == []
    
    @pytest.mark.asyncio
    async def test_get_by_id_success(self, pg_store, mock_pool):
        """Test get_by_id returns Holon when found."""
        pg_store._pool = mock_pool
        mock_conn = AsyncMock()
        mock_conn = mock_pool.acquire.return_value.__aenter__.return_value
        
        # Mock fetchrow result
        mock_row = Mock()
        mock_row.__getitem__ = Mock(side_effect=lambda k: {
            "uuid": "test-uuid-123",
            "embedding": np.array([1.0, 2.0, 3.0]),
            "meta": {"key": "value"}
        }.get(k))
        mock_conn.fetchrow = AsyncMock(return_value=mock_row)
        
        result = await pg_store.get_by_id("test-uuid-123")
        
        assert result is not None
        assert isinstance(result, Holon)
        assert result.uuid == "test-uuid-123"
        assert result.meta == {"key": "value"}
    
    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, pg_store, mock_pool):
        """Test get_by_id returns None when not found."""
        pg_store._pool = mock_pool
        mock_conn = AsyncMock()
        mock_conn = mock_pool.acquire.return_value.__aenter__.return_value
        mock_conn.fetchrow = AsyncMock(return_value=None)
        
        result = await pg_store.get_by_id("non-existent-uuid")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_get_by_ids(self, pg_store, mock_pool):
        """Test batch retrieval by UUIDs."""
        pg_store._pool = mock_pool
        mock_conn = AsyncMock()
        mock_conn = mock_pool.acquire.return_value.__aenter__.return_value
        
        # Mock fetch results
        mock_row1 = Mock()
        mock_row1.__getitem__ = Mock(side_effect=lambda k: {
            "uuid": "uuid1",
            "embedding": np.array([1.0, 2.0]),
            "meta": {"key1": "value1"}
        }.get(k))
        mock_row2 = Mock()
        mock_row2.__getitem__ = Mock(side_effect=lambda k: {
            "uuid": "uuid2",
            "embedding": np.array([3.0, 4.0]),
            "meta": {"key2": "value2"}
        }.get(k))
        mock_conn.fetch = AsyncMock(return_value=[mock_row1, mock_row2])
        
        results = await pg_store.get_by_ids(["uuid1", "uuid2"])
        
        assert len(results) == 2
        assert all(isinstance(r, Holon) for r in results)
        assert results[0].uuid == "uuid1"
        assert results[1].uuid == "uuid2"
    
    @pytest.mark.asyncio
    async def test_get_count(self, pg_store, mock_pool):
        """Test get_count returns total holon count."""
        pg_store._pool = mock_pool
        mock_conn = AsyncMock()
        mock_conn = mock_pool.acquire.return_value.__aenter__.return_value
        mock_conn.fetchval = AsyncMock(return_value=42)
        
        count = await pg_store.get_count()
        
        assert count == 42
        mock_conn.fetchval.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_execute_scalar_query(self, pg_store, mock_pool):
        """Test execute_scalar_query executes and returns scalar value."""
        pg_store._pool = mock_pool
        mock_conn = AsyncMock()
        mock_conn = mock_pool.acquire.return_value.__aenter__.return_value
        mock_conn.fetchval = AsyncMock(return_value=1024)
        
        result = await pg_store.execute_scalar_query("SELECT pg_total_relation_size('holons')")
        
        assert result == 1024
        mock_conn.fetchval.assert_called_once_with("SELECT pg_total_relation_size('holons')")
    
    @pytest.mark.asyncio
    async def test_close(self, pg_store, mock_pool):
        """Test close properly closes the connection pool."""
        pg_store._pool = mock_pool
        
        await pg_store.close()
        
        mock_pool.close.assert_called_once()
        assert pg_store._pool is None
    
    @pytest.mark.asyncio
    async def test_close_no_pool(self, pg_store):
        """Test close handles case when pool doesn't exist."""
        pg_store._pool = None
        
        # Should not raise an exception
        await pg_store.close()
        
        assert pg_store._pool is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
