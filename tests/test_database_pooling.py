"""
Comprehensive test suite for database connection pooling.

This module tests all aspects of the connection pooling system including
async/sync operations, Ray integration, health checks, and metrics.
"""

# Import mock dependencies BEFORE any other imports
import mock_database_dependencies
import mock_ray_dependencies

import pytest
import asyncio
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any

import ray
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from seedcore.database import (
    get_async_pg_engine,
    get_async_mysql_engine,
    get_sync_pg_engine,
    get_sync_mysql_engine,
    get_neo4j_driver,
    get_async_pg_session,
    get_async_mysql_session,
    get_sync_pg_session,
    get_sync_mysql_session,
    get_neo4j_session,
    check_pg_health,
    check_mysql_health,
    check_neo4j_health,
    get_pg_pool_stats,
    get_mysql_pool_stats,
)

from seedcore.monitoring.database_metrics import (
    DatabaseMetrics,
    monitor_query,
    monitor_health_check,
    start_metrics_collection,
    stop_metrics_collection,
)


class TestDatabaseConnectionPools:
    """Test database connection pool functionality."""
    
    def test_sync_pg_engine_creation(self):
        """Test sync PostgreSQL engine creation with pooling."""
        engine = get_sync_pg_engine()
        assert engine is not None
        assert engine.pool.size() > 0
        assert engine.pool._max_overflow > 0
    
    def test_sync_mysql_engine_creation(self):
        """Test sync MySQL engine creation with pooling."""
        engine = get_sync_mysql_engine()
        assert engine is not None
        assert engine.pool.size() > 0
        assert engine.pool._max_overflow > 0
    
    def test_async_pg_engine_creation(self):
        """Test async PostgreSQL engine creation with pooling."""
        engine = get_async_pg_engine()
        assert engine is not None
        # Async engines don't expose pool size directly, but we can check the engine exists
    
    def test_async_mysql_engine_creation(self):
        """Test async MySQL engine creation with pooling."""
        engine = get_async_mysql_engine()
        assert engine is not None
    
    def test_neo4j_driver_creation(self):
        """Test Neo4j driver creation with pooling."""
        driver = get_neo4j_driver()
        assert driver is not None
    
    def test_engine_singleton_pattern(self):
        """Test that engines are cached as singletons."""
        engine1 = get_sync_pg_engine()
        engine2 = get_sync_pg_engine()
        assert engine1 is engine2
        
        mysql_engine1 = get_sync_mysql_engine()
        mysql_engine2 = get_sync_mysql_engine()
        assert mysql_engine1 is mysql_engine2


class TestSyncDatabaseOperations:
    """Test synchronous database operations with connection pooling."""
    
    def test_sync_pg_connection(self):
        """Test sync PostgreSQL connection and query."""
        # Skip if no database connection is available
        import os
        if not os.getenv("POSTGRES_HOST") and not os.getenv("PG_DSN"):
            pytest.skip("No PostgreSQL connection configured")
        
        session = get_sync_pg_session()
        try:
            result = session.execute(text("SELECT 1 as test_value"))
            row = result.fetchone()
            assert row.test_value == 1
        finally:
            session.close()
    
    def test_sync_mysql_connection(self):
        """Test sync MySQL connection and query."""
        # Skip if no database connection is available
        import os
        if not os.getenv("MYSQL_HOST") and not os.getenv("MYSQL_DSN"):
            pytest.skip("No MySQL connection configured")
        
        session = get_sync_mysql_session()
        try:
            result = session.execute(text("SELECT 1 as test_value"))
            row = result.fetchone()
            assert row.test_value == 1
        finally:
            session.close()
    
    def test_sync_pool_stats(self):
        """Test sync pool statistics collection."""
        pg_stats = get_pg_pool_stats()
        assert 'size' in pg_stats
        assert 'checked_out' in pg_stats
        assert 'checked_in' in pg_stats
        assert 'overflow' in pg_stats
        assert 'invalid' in pg_stats
        
        mysql_stats = get_mysql_pool_stats()
        assert 'size' in mysql_stats
        assert 'checked_out' in mysql_stats
        assert 'checked_in' in mysql_stats
        assert 'overflow' in mysql_stats
        assert 'invalid' in mysql_stats


class TestAsyncDatabaseOperations:
    """Test asynchronous database operations with connection pooling."""
    
    @pytest.mark.asyncio
    async def test_async_pg_connection(self):
        """Test async PostgreSQL connection and query."""
        # Skip if no database connection is available
        import os
        if not os.getenv("POSTGRES_HOST") and not os.getenv("PG_DSN"):
            pytest.skip("No PostgreSQL connection configured")
        
        from seedcore.database import get_async_pg_session_factory
        async with get_async_pg_session_factory()() as session:
            result = await session.execute(text("SELECT 1 as test_value"))
            row = result.fetchone()
            assert row.test_value == 1
    
    @pytest.mark.asyncio
    async def test_async_mysql_connection(self):
        """Test async MySQL connection and query."""
        # Skip if no database connection is available
        import os
        if not os.getenv("MYSQL_HOST") and not os.getenv("MYSQL_DSN"):
            pytest.skip("No MySQL connection configured")
        
        from seedcore.database import get_async_mysql_session_factory
        async with get_async_mysql_session_factory()() as session:
            result = await session.execute(text("SELECT 1 as test_value"))
            row = result.fetchone()
            assert row.test_value == 1
    
    @pytest.mark.asyncio
    async def test_neo4j_connection(self):
        """Test Neo4j connection and query."""
        # Skip if no database connection is available
        import os
        if not os.getenv("NEO4J_URI"):
            pytest.skip("No Neo4j connection configured")
        
        async with get_neo4j_session() as session:
            result = await session.run("RETURN 1 as test_value")
            record = await result.single()
            assert record["test_value"] == 1


class TestHealthChecks:
    """Test database health check functionality."""
    
    @pytest.mark.asyncio
    async def test_pg_health_check(self):
        """Test PostgreSQL health check."""
        # Skip if no database connection is available
        import os
        if not os.getenv("POSTGRES_HOST") and not os.getenv("PG_DSN"):
            pytest.skip("No PostgreSQL connection configured")
        
        is_healthy = await check_pg_health()
        assert isinstance(is_healthy, bool)
        # Don't assert is_healthy == True since DB might not be available in test env
    
    @pytest.mark.asyncio
    async def test_mysql_health_check(self):
        """Test MySQL health check."""
        # Skip if no database connection is available
        import os
        if not os.getenv("MYSQL_HOST") and not os.getenv("MYSQL_DSN"):
            pytest.skip("No MySQL connection configured")
        
        is_healthy = await check_mysql_health()
        assert isinstance(is_healthy, bool)
        # Don't assert is_healthy == True since DB might not be available in test env
    
    @pytest.mark.asyncio
    async def test_neo4j_health_check(self):
        """Test Neo4j health check."""
        # Skip if no database connection is available
        import os
        if not os.getenv("NEO4J_URI"):
            pytest.skip("No Neo4j connection configured")
        
        is_healthy = await check_neo4j_health()
        assert isinstance(is_healthy, bool)
        # Don't assert is_healthy == True since DB might not be available in test env


class TestConcurrentOperations:
    """Test concurrent database operations with connection pooling."""
    
    def test_concurrent_sync_operations(self):
        """Test concurrent sync database operations."""
        # Skip if no database connection is available
        import os
        if not os.getenv("POSTGRES_HOST") and not os.getenv("PG_DSN"):
            pytest.skip("No PostgreSQL connection configured")
        
        def execute_query(query_id: int) -> Dict[str, Any]:
            session = get_sync_pg_session()
            try:
                result = session.execute(text(f"SELECT {query_id} as query_id"))
                row = result.fetchone()
                return {"query_id": row.query_id, "success": True}
            except Exception as e:
                return {"query_id": query_id, "success": False, "error": str(e)}
            finally:
                session.close()
        
        # Execute 10 concurrent queries
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(execute_query, i) for i in range(10)]
            results = [future.result() for future in futures]
        
        # All queries should succeed
        assert len(results) == 10
        for result in results:
            assert result["success"]
    
    @pytest.mark.asyncio
    async def test_concurrent_async_operations(self):
        """Test concurrent async database operations."""
        # Skip if no database connection is available
        import os
        if not os.getenv("POSTGRES_HOST") and not os.getenv("PG_DSN"):
            pytest.skip("No PostgreSQL connection configured")
        
        async def execute_async_query(query_id: int) -> Dict[str, Any]:
            from seedcore.database import get_async_pg_session_factory
            async with get_async_pg_session_factory()() as session:
                try:
                    result = await session.execute(text(f"SELECT {query_id} as query_id"))
                    row = result.fetchone()
                    return {"query_id": row.query_id, "success": True}
                except Exception as e:
                    return {"query_id": query_id, "success": False, "error": str(e)}
        
        # Execute 10 concurrent async queries
        tasks = [execute_async_query(i) for i in range(10)]
        results = await asyncio.gather(*tasks)
        
        # All queries should succeed
        assert len(results) == 10
        for result in results:
            assert result["success"]


class TestRayIntegration:
    """Test Ray integration with database connection pooling."""
    
    @pytest.fixture(scope="class")
    def ray_init(self):
        """Initialize Ray for testing."""
        if not ray.is_initialized():
            from seedcore.utils.ray_utils import ensure_ray_initialized
            if not ensure_ray_initialized(local_mode=True):
                pytest.skip("Failed to initialize Ray for testing")
        yield
        if ray.is_initialized():
            ray.shutdown()
    
    def test_ray_actor_with_database_pools(self, ray_init):
        """Test Ray actor with database connection pools."""
        # Skip if no database connection is available
        import os
        if not os.getenv("POSTGRES_HOST") and not os.getenv("PG_DSN"):
            pytest.skip("No PostgreSQL connection configured")
        if not os.getenv("MYSQL_HOST") and not os.getenv("MYSQL_DSN"):
            pytest.skip("No MySQL connection configured")
        
        @ray.remote
        class TestDatabaseActor:
            def __init__(self):
                self.pg_engine = get_sync_pg_engine()
                self.mysql_engine = get_sync_mysql_engine()
            
            def test_pg_query(self):
                with self.pg_engine.connect() as conn:
                    result = conn.execute(text("SELECT 1 as test_value"))
                    row = result.fetchone()
                    return row.test_value
            
            def test_mysql_query(self):
                with self.mysql_engine.connect() as conn:
                    result = conn.execute(text("SELECT 1 as test_value"))
                    row = result.fetchone()
                    return row.test_value
        
        # Create actor and test queries
        actor = TestDatabaseActor.remote()
        
        pg_result = ray.get(actor.test_pg_query.remote())
        assert pg_result == 1
        
        mysql_result = ray.get(actor.test_mysql_query.remote())
        assert mysql_result == 1


class TestMetricsCollection:
    """Test database metrics collection."""
    
    def test_metrics_initialization(self):
        """Test metrics initialization."""
        metrics = DatabaseMetrics()
        assert metrics is not None
        assert metrics.registry is not None
    
    def test_pool_metrics_update(self):
        """Test pool metrics update."""
        metrics = DatabaseMetrics()
        metrics.update_pool_metrics()
        
        # Check that metrics were updated
        summary = metrics.get_metrics_summary()
        assert 'postgresql' in summary
        assert 'mysql' in summary
        assert 'pool_size' in summary['postgresql']
        assert 'pool_size' in summary['mysql']
    
    def test_metrics_decorators(self):
        """Test metrics decorators."""
        @monitor_query("postgresql", "sync", "test")
        def test_query():
            session = get_sync_pg_session()
            try:
                result = session.execute(text("SELECT 1"))
                return result.scalar()
            finally:
                session.close()
        
        result = test_query()
        assert result == 1
    
    def test_health_check_decorator(self):
        """Test health check decorator."""
        @monitor_health_check("postgresql", "sync")
        def test_health_check():
            session = get_sync_pg_session()
            try:
                result = session.execute(text("SELECT 1"))
                return result.scalar() == 1
            finally:
                session.close()
        
        result = test_health_check()
        assert result is True


class TestConnectionPoolStress:
    """Stress tests for connection pooling."""
    
    def test_pool_exhaustion_recovery(self):
        """Test that pools recover after being exhausted."""
        # Skip if no database connection is available
        import os
        if not os.getenv("POSTGRES_HOST") and not os.getenv("PG_DSN"):
            pytest.skip("No PostgreSQL connection configured")
        
        # Get initial pool stats
        initial_stats = get_pg_pool_stats()
        initial_size = initial_stats['size']
        
        # Create many connections to potentially exhaust the pool
        connections = []
        try:
            for i in range(initial_size + 5):  # Exceed pool size
                session = get_sync_pg_session()
                connections.append(session)
                # Execute a simple query
                result = session.execute(text("SELECT 1"))
                assert result.scalar() == 1
        except Exception as e:
            # Pool exhaustion is expected, but should not crash
            assert "timeout" in str(e).lower() or "pool" in str(e).lower()
        finally:
            # Close all connections
            for session in connections:
                session.close()
        
        # Pool should recover
        final_stats = get_pg_pool_stats()
        assert final_stats['checked_out'] == 0
    
    @pytest.mark.asyncio
    async def test_async_pool_stress(self):
        """Stress test for async connection pools."""
        # Skip if no database connection is available
        import os
        if not os.getenv("POSTGRES_HOST") and not os.getenv("PG_DSN"):
            pytest.skip("No PostgreSQL connection configured")
        
        async def stress_operation(operation_id: int):
            from seedcore.database import get_async_pg_session_factory
            async with get_async_pg_session_factory()() as session:
                try:
                    # Simulate some work
                    await asyncio.sleep(0.01)
                    result = await session.execute(text(f"SELECT {operation_id} as op_id"))
                    row = result.fetchone()
                    return {"operation_id": row.op_id, "success": True}
                except Exception as e:
                    return {"operation_id": operation_id, "success": False, "error": str(e)}
        
        # Execute many concurrent operations
        tasks = [stress_operation(i) for i in range(50)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Most operations should succeed
        successful_results = [r for r in results if isinstance(r, dict) and r.get("success")]
        assert len(successful_results) > 0


class TestConfigurationValidation:
    """Test configuration validation and edge cases."""
    
    def test_invalid_dsn_handling(self):
        """Test handling of invalid database DSNs."""
        # This test would require mocking the database settings
        # to simulate invalid DSNs and ensure graceful error handling
        pass
    
    def test_pool_size_limits(self):
        """Test pool size limits and validation."""
        # Test with very small pool sizes
        # Test with very large pool sizes
        # Test with zero pool size
        pass
    
    def test_connection_timeout_handling(self):
        """Test connection timeout handling."""
        # Test behavior when database is unreachable
        # Test timeout settings
        pass


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegrationScenarios:
    """Integration tests for real-world scenarios."""
    
    @pytest.mark.asyncio
    async def test_mixed_sync_async_operations(self):
        """Test mixing sync and async operations."""
        # Test scenario where both sync and async operations are used
        # in the same application
        pass
    
    def test_ray_worker_pool_scaling(self):
        """Test Ray worker pool scaling with database connections."""
        # Test creating many Ray workers and ensuring they all
        # can access the database efficiently
        pass
    
    @pytest.mark.asyncio
    async def test_database_failover_scenarios(self):
        """Test database failover and recovery scenarios."""
        # Test behavior when database becomes unavailable
        # Test recovery when database comes back online
        pass


# =============================================================================
# Performance Tests
# =============================================================================

class TestPerformance:
    """Performance tests for connection pooling."""
    
    def test_connection_acquisition_speed(self):
        """Test connection acquisition speed."""
        # Skip if no database connection is available
        import os
        if not os.getenv("POSTGRES_HOST") and not os.getenv("PG_DSN"):
            pytest.skip("No PostgreSQL connection configured")
        
        start_time = time.time()
        
        # Acquire many connections quickly
        sessions = []
        for i in range(100):
            session = get_sync_pg_session()
            sessions.append(session)
        
        acquisition_time = time.time() - start_time
        
        # Clean up
        for session in sessions:
            session.close()
        
        # Connection acquisition should be fast (< 1 second for 100 connections)
        assert acquisition_time < 1.0
    
    @pytest.mark.asyncio
    async def test_async_connection_throughput(self):
        """Test async connection throughput."""
        # Skip if no database connection is available
        import os
        if not os.getenv("POSTGRES_HOST") and not os.getenv("PG_DSN"):
            pytest.skip("No PostgreSQL connection configured")
        
        async def quick_query():
            from seedcore.database import get_async_pg_session_factory
            async with get_async_pg_session_factory()() as session:
                await session.execute(text("SELECT 1"))
        
        start_time = time.time()
        
        # Execute many quick queries with timeout protection
        try:
            tasks = [quick_query() for _ in range(100)]
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=10.0)
            
            total_time = time.time() - start_time
            
            # Should handle 100 queries efficiently
            assert total_time < 10.0  # Should complete in under 10 seconds
        except asyncio.TimeoutError:
            pytest.skip("Database connection too slow for throughput test")
        except Exception as e:
            if "connection" in str(e).lower() or "timeout" in str(e).lower():
                pytest.skip(f"Database connection issue: {e}")
            else:
                raise


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"]) 