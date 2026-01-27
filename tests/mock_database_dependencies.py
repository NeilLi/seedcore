#!/usr/bin/env python3
"""
Mock Database Dependencies for Testing

This module provides mock implementations of database engines and sessions
to allow tests to run without requiring real database connections.
"""

import sys
import os
import asyncio
from typing import Any, Dict, List, Optional, Union, Tuple
from unittest.mock import Mock, AsyncMock, MagicMock
import logging

# Module-level simulated pool states
PG_POOL_STATE = {
    "size": 5,
    "checked_in": 5,
    "checked_out": 0,
    "overflow": 0,
    "invalid": 0,
}
MYSQL_POOL_STATE = {
    "size": 5,
    "checked_in": 5,
    "checked_out": 0,
    "overflow": 0,
    "invalid": 0,
}

# Mock SQLAlchemy async engine
class MockAsyncEngine:
    """Mock async SQLAlchemy engine."""
    
    def __init__(self, name="mock_engine"):
        self.name = name
        self.pool = MockPool()
        self._closed = False
    
    def dispose(self):
        """Mock dispose method."""
        self._closed = True
    
    def is_closed(self):
        """Mock is_closed method."""
        return self._closed
    
    def get_pool(self):
        """Mock get_pool method."""
        return self.pool

class MockPool:
    """Mock connection pool."""
    
    def __init__(self):
        self._size = 5
        self._checked_in = 3
        self._overflow = 0
        self._checked_out = 2
        self._invalid = 0
        self._checked_in_connections = 3
        self._overflow_connections = 0
        self._checked_out_connections = 2
        self._invalid_connections = 0
        self._max_overflow = 10
        self._max_size = 20
        self._min_size = 1
    
    def size(self):
        """Mock size method - callable version."""
        return self._size
    
    def get_size(self):
        """Mock get_size method."""
        return self._size
    
    def get_checked_in(self):
        """Mock get_checked_in method."""
        return self._checked_in
    
    def get_overflow(self):
        """Mock get_overflow method."""
        return self._overflow
    
    def get_checked_out(self):
        """Mock get_checked_out method."""
        return self._checked_out
    
    def get_invalid(self):
        """Mock get_invalid method."""
        return self._invalid

# Mock SQLAlchemy async session
class MockAsyncSession:
    """Mock async SQLAlchemy session."""
    
    def __init__(self):
        self._closed = False
        self._in_transaction = False
    
    async def __aenter__(self):
        """Mock async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Mock async context manager exit."""
        self._closed = True
    
    async def execute(self, statement, parameters=None):
        """Mock execute method."""
        # Return a mock result
        return MockResult()
    
    async def commit(self):
        """Mock commit method."""
        pass
    
    async def rollback(self):
        """Mock rollback method."""
        pass
    
    async def close(self):
        """Mock close method."""
        self._closed = True
    
    async def refresh(self, instance, attribute_names=None, with_for_update=None):
        """Mock refresh method - no-op for testing."""
        pass
    
    async def flush(self):
        """Mock flush method - no-op for testing."""
        pass
    
    def add(self, instance):
        """Mock add method."""
        pass
    
    def add_all(self, instances):
        """Mock add_all method."""
        pass
    
    def begin(self):
        """Mock begin method for transaction."""
        return self

class MockResult:
    """Mock SQLAlchemy result."""
    
    def __init__(self):
        self._data = [{"test_value": 1}]
        self._index = 0
    
    def fetchone(self):
        """Mock fetchone method."""
        if self._index < len(self._data):
            row = self._data[self._index]
            self._index += 1
            return MockRow(row)
        return None
    
    def fetchall(self):
        """Mock fetchall method."""
        return [MockRow(row) for row in self._data]
    
    def scalar(self):
        """Mock scalar method."""
        if self._data:
            return list(self._data[0].values())[0]
        return None
    
    def scalar_one(self):
        """Mock scalar_one method."""
        if self._data:
            return list(self._data[0].values())[0]
        raise ValueError("No rows returned")
    
    def scalar_one_or_none(self):
        """Mock scalar_one_or_none method."""
        if self._data:
            return list(self._data[0].values())[0]
        return None

class MockRow:
    """Mock SQLAlchemy row."""
    
    def __init__(self, data):
        self._data = data
    
    def __getattr__(self, name):
        """Mock attribute access."""
        return self._data.get(name)

# Mock sync session
class MockSyncSession:
    """Mock sync SQLAlchemy session."""
    
    def __init__(self, pool_state=None):
        self._closed = False
        self._pool_state = pool_state
        # Simulate checkout from pool on session creation
        if isinstance(self._pool_state, dict):
            if self._pool_state.get("checked_in", 0) > 0:
                self._pool_state["checked_in"] -= 1
            self._pool_state["checked_out"] = self._pool_state.get("checked_out", 0) + 1
    
    def __enter__(self):
        """Mock context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Mock context manager exit."""
        self._closed = True
    
    def execute(self, statement, parameters=None):
        """Mock execute method."""
        return MockResult()
    
    def commit(self):
        """Mock commit method."""
        pass
    
    def rollback(self):
        """Mock rollback method."""
        pass
    
    def close(self):
        """Mock close method."""
        self._closed = True
        # Simulate return to pool on close
        if isinstance(self._pool_state, dict):
            if self._pool_state.get("checked_out", 0) > 0:
                self._pool_state["checked_out"] -= 1
            self._pool_state["checked_in"] = self._pool_state.get("checked_in", 0) + 1

# Mock Neo4j driver
class MockNeo4jDriver:
    """Mock Neo4j driver."""
    
    def __init__(self):
        self._closed = False
    
    def close(self):
        """Mock close method."""
        self._closed = True
    
    def is_closed(self):
        """Mock is_closed method."""
        return self._closed
    
    def session(self, **kwargs):
        """Mock session method."""
        return MockNeo4jSession()

class MockNeo4jSession:
    """Mock Neo4j session."""
    
    def __init__(self):
        self._closed = False
    
    def __enter__(self):
        """Mock context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Mock context manager exit."""
        self._closed = True
    
    async def __aenter__(self):
        """Mock async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Mock async context manager exit."""
        self._closed = True
    
    async def run(self, query, parameters=None):
        """Mock run method."""
        return MockNeo4jResult()
    
    def close(self):
        """Mock close method."""
        self._closed = True

class MockNeo4jResult:
    """Mock Neo4j result."""
    
    def __init__(self):
        self._data = [{"test_value": 1}]
        self._index = 0
    
    async def single(self):
        """Mock single method."""
        if self._data:
            return MockNeo4jRecord(self._data[0])
        return None
    
    def data(self):
        """Mock data method."""
        return self._data

class MockNeo4jRecord:
    """Mock Neo4j record."""
    
    def __init__(self, data):
        self._data = data
    
    def __getitem__(self, key):
        """Mock item access."""
        return self._data.get(key)

# Create singleton engine instances
_singleton_async_pg_engine = None
_singleton_async_mysql_engine = None
_singleton_sync_pg_engine = None
_singleton_sync_mysql_engine = None

# Mock database functions
def mock_get_async_pg_engine():
    """Mock get_async_pg_engine function."""
    global _singleton_async_pg_engine
    if _singleton_async_pg_engine is None:
        _singleton_async_pg_engine = MockAsyncEngine("mock_pg_engine")
    return _singleton_async_pg_engine

def mock_get_async_mysql_engine():
    """Mock get_async_mysql_engine function."""
    global _singleton_async_mysql_engine
    if _singleton_async_mysql_engine is None:
        _singleton_async_mysql_engine = MockAsyncEngine("mock_mysql_engine")
    return _singleton_async_mysql_engine

def mock_get_sync_pg_engine():
    """Mock get_sync_pg_engine function."""
    global _singleton_sync_pg_engine
    if _singleton_sync_pg_engine is None:
        _singleton_sync_pg_engine = MockAsyncEngine("mock_sync_pg_engine")
    return _singleton_sync_pg_engine

def mock_get_sync_mysql_engine():
    """Mock get_sync_mysql_engine function."""
    global _singleton_sync_mysql_engine
    if _singleton_sync_mysql_engine is None:
        _singleton_sync_mysql_engine = MockAsyncEngine("mock_sync_mysql_engine")
    return _singleton_sync_mysql_engine

def mock_get_neo4j_driver():
    """Mock get_neo4j_driver function."""
    return MockNeo4jDriver()

def mock_get_redis_client():
    """Mock get_redis_client function - returns None for tests."""
    return None

async def mock_get_async_redis_client():
    """Mock get_async_redis_client function - returns None for tests."""
    return None

def mock_get_async_pg_session():
    """Mock get_async_pg_session function."""
    return MockAsyncSession()

def mock_get_async_mysql_session():
    """Mock get_async_mysql_session function."""
    return MockAsyncSession()

def mock_get_sync_pg_session():
    """Mock get_sync_pg_session function."""
    return MockSyncSession(pool_state=PG_POOL_STATE)

def mock_get_sync_mysql_session():
    """Mock get_sync_mysql_session function."""
    return MockSyncSession(pool_state=MYSQL_POOL_STATE)

def mock_get_neo4j_session():
    """Mock get_neo4j_session function."""
    return MockNeo4jSession()

def mock_get_async_pg_session_factory():
    """Mock get_async_pg_session_factory function."""
    class MockSessionMaker:
        def __call__(self):
            return MockAsyncSession()
    return MockSessionMaker()

def mock_get_async_mysql_session_factory():
    """Mock get_async_mysql_session_factory function."""
    class MockSessionMaker:
        def __call__(self):
            return MockAsyncSession()
    return MockSessionMaker()

def mock_get_sync_pg_session_factory():
    """Mock get_sync_pg_session_factory function."""
    class MockSessionMaker:
        def __call__(self):
            return MockSyncSession()
    return MockSessionMaker()

def mock_get_sync_mysql_session_factory():
    """Mock get_sync_mysql_session_factory function."""
    class MockSessionMaker:
        def __call__(self):
            return MockSyncSession()
    return MockSessionMaker()

def mock_get_neo4j_session_factory():
    """Mock get_neo4j_session_factory function."""
    class MockSessionMaker:
        def __call__(self):
            return MockNeo4jSession()
    return MockSessionMaker()

async def mock_check_pg_health():
    """Mock check_pg_health function."""
    return True

async def mock_check_mysql_health():
    """Mock check_mysql_health function."""
    return True

async def mock_check_neo4j_health():
    """Mock check_neo4j_health function."""
    return True

def mock_get_pg_pool_stats():
    """Mock get_pg_pool_stats function."""
    # Reflect current simulated PG pool state
    return dict(PG_POOL_STATE)

def mock_get_mysql_pool_stats():
    """Mock get_mysql_pool_stats function."""
    return dict(MYSQL_POOL_STATE)

# Mock database metrics
class MockDatabaseMetrics:
    """Mock database metrics class."""
    
    def __init__(self):
        self.query_count = 0
        self.query_duration = 0.0
        self.error_count = 0
        self.health_check_count = 0
        self.health_check_duration = 0.0
        # Minimal registry to satisfy tests
        self.registry = {
            'postgresql': {},
            'mysql': {}
        }
    
    def record_query(self, duration: float, success: bool = True):
        """Mock record_query method."""
        self.query_count += 1
        self.query_duration += duration
        if not success:
            self.error_count += 1
    
    def record_health_check(self, duration: float, success: bool = True):
        """Mock record_health_check method."""
        self.health_check_count += 1
        self.health_check_duration += duration
    
    def get_metrics(self):
        """Mock get_metrics method."""
        return {
            "query_count": self.query_count,
            "query_duration": self.query_duration,
            "error_count": self.error_count,
            "health_check_count": self.health_check_count,
            "health_check_duration": self.health_check_duration
        }

    def update_pool_metrics(self):
        """Populate registry with pool metrics from mocked database module."""
        db_module = sys.modules.get('seedcore.database')
        if not db_module:
            return
        # PostgreSQL
        try:
            pg = db_module.get_pg_pool_stats()
            self.registry['postgresql'].update({
                'pool_size': pg.get('size'),
                'checked_in': pg.get('checked_in'),
                'checked_out': pg.get('checked_out'),
                'overflow': pg.get('overflow'),
                'invalid': pg.get('invalid'),
            })
        except Exception:
            pass
        # MySQL
        try:
            my = db_module.get_mysql_pool_stats()
            self.registry['mysql'].update({
                'pool_size': my.get('size'),
                'checked_in': my.get('checked_in'),
                'checked_out': my.get('checked_out'),
                'overflow': my.get('overflow'),
                'invalid': my.get('invalid'),
            })
        except Exception:
            pass

    def get_metrics_summary(self):
        """Return a summary compatible with tests' expectations."""
        return self.registry

def mock_monitor_query(db_type: str, mode: str, name: str):
    """Mock monitor_query decorator factory accepting (db_type, mode, name)."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    return decorator

def mock_monitor_health_check(db_type: str, mode: str):
    """Mock monitor_health_check decorator factory accepting (db_type, mode)."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    return decorator

def mock_start_metrics_collection():
    """Mock start_metrics_collection function."""
    pass

def mock_stop_metrics_collection():
    """Mock stop_metrics_collection function."""
    pass

# Create a simple module object
import types
mock_database_module = types.ModuleType('seedcore.database')

# Set the functions as module attributes
mock_database_module.get_async_pg_engine = mock_get_async_pg_engine
mock_database_module.get_async_mysql_engine = mock_get_async_mysql_engine
mock_database_module.get_sync_pg_engine = mock_get_sync_pg_engine
mock_database_module.get_sync_mysql_engine = mock_get_sync_mysql_engine
mock_database_module.get_neo4j_driver = mock_get_neo4j_driver
mock_database_module.get_async_pg_session = mock_get_async_pg_session
mock_database_module.get_async_mysql_session = mock_get_async_mysql_session
mock_database_module.get_sync_pg_session = mock_get_sync_pg_session
mock_database_module.get_sync_mysql_session = mock_get_sync_mysql_session
mock_database_module.get_neo4j_session = mock_get_neo4j_session
mock_database_module.get_async_pg_session_factory = mock_get_async_pg_session_factory
mock_database_module.get_async_mysql_session_factory = mock_get_async_mysql_session_factory
mock_database_module.get_sync_pg_session_factory = mock_get_sync_pg_session_factory
mock_database_module.get_sync_mysql_session_factory = mock_get_sync_mysql_session_factory
mock_database_module.get_neo4j_session_factory = mock_get_neo4j_session_factory
mock_database_module.check_pg_health = mock_check_pg_health
mock_database_module.check_mysql_health = mock_check_mysql_health
mock_database_module.check_neo4j_health = mock_check_neo4j_health
mock_database_module.get_pg_pool_stats = mock_get_pg_pool_stats
mock_database_module.get_mysql_pool_stats = mock_get_mysql_pool_stats
mock_database_module.get_redis_client = mock_get_redis_client
mock_database_module.get_async_redis_client = mock_get_async_redis_client

# Mock asyncpg pool for TaskRepository
class MockAsyncPGPool:
    """Mock asyncpg.Pool for testing."""
    
    def __init__(self):
        self._closed = False
    
    async def acquire(self):
        """Mock acquire method - returns a mock connection."""
        return MockAsyncPGConnection()
    
    async def close(self):
        """Mock close method."""
        self._closed = True
    
    def is_closed(self):
        """Mock is_closed method."""
        return self._closed

class MockAsyncPGConnection:
    """Mock asyncpg.Connection for testing."""
    
    async def execute(self, query, *args):
        """Mock execute method."""
        return "UPDATE 0"
    
    async def fetchval(self, query, *args):
        """Mock fetchval method."""
        return None
    
    async def fetchrow(self, query, *args):
        """Mock fetchrow method."""
        return None
    
    async def fetch(self, query, *args):
        """Mock fetch method."""
        return []
    
    async def close(self):
        """Mock close method."""
        pass
    
    def __enter__(self):
        """Mock context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Mock context manager exit."""
        pass

async def mock_get_asyncpg_pool(
    min_size: Optional[int] = None,
    max_size: Optional[int] = None,
    command_timeout: Optional[float] = None,
):
    """Mock get_asyncpg_pool function."""
    return MockAsyncPGPool()

# Mock constants
PG_DSN = os.getenv("PG_DSN", "postgresql://postgres:postgres@localhost:5432/seedcore")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_BOLT_URL = os.getenv("NEO4J_BOLT_URL", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

# Mock the database metrics module as a proper module to avoid bound methods
mock_database_metrics_module = types.ModuleType('seedcore.monitoring.database_metrics')
mock_database_metrics_module.DatabaseMetrics = MockDatabaseMetrics
mock_database_metrics_module.monitor_query = mock_monitor_query
mock_database_metrics_module.monitor_health_check = mock_monitor_health_check
mock_database_metrics_module.start_metrics_collection = mock_start_metrics_collection
mock_database_metrics_module.stop_metrics_collection = mock_stop_metrics_collection

# Add get_asyncpg_pool and constants to mock database module
mock_database_module.get_asyncpg_pool = mock_get_asyncpg_pool
mock_database_module.PG_DSN = PG_DSN
mock_database_module.REDIS_URL = REDIS_URL
mock_database_module.NEO4J_URI = NEO4J_URI
mock_database_module.NEO4J_BOLT_URL = NEO4J_BOLT_URL
mock_database_module.NEO4J_USER = NEO4J_USER
mock_database_module.NEO4J_PASSWORD = NEO4J_PASSWORD

# Mock the modules in sys.modules before they're imported
sys.modules['seedcore.database'] = mock_database_module
sys.modules['seedcore.monitoring.database_metrics'] = mock_database_metrics_module

print("✅ Mock database dependencies loaded successfully")
