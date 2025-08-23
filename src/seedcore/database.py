"""
Database connection management with robust connection pooling.

This module provides centralized database engine creation with configurable
connection pools for PostgreSQL, MySQL, and Neo4j. All engines are cached
as singletons to ensure efficient resource usage across FastAPI requests
and Ray tasks.
"""

import os
from functools import lru_cache
from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from neo4j import GraphDatabase
import logging

logger = logging.getLogger(__name__)

# Public API exports
__all__ = [
    # Engine getters
    "get_async_pg_engine",
    "get_sync_pg_engine", 
    "get_async_mysql_engine",
    "get_sync_mysql_engine",
    "get_neo4j_driver",
    
    # Session factories
    "get_async_pg_session_factory",
    "get_sync_pg_session_factory",
    "get_async_mysql_session_factory", 
    "get_sync_mysql_session_factory",
    
    # FastAPI dependencies
    "get_async_pg_session",
    "get_async_mysql_session",
    "get_sync_pg_session",
    "get_sync_mysql_session",
    
    # Neo4j session
    "get_neo4j_session",
    
    # Health checks
    "check_pg_health",
    "check_mysql_health", 
    "check_neo4j_health",
    
    # Pool statistics
    "get_pg_pool_stats",
    "get_mysql_pool_stats",
    
    # Legacy compatibility
    "get_db_session",
    "get_mysql_session",
]


# Database configuration settings loaded from environment variables
def get_env_setting(key: str, default: str) -> str:
    """Get environment variable with fallback to default."""
    return os.getenv(key, default)


def get_env_int_setting(key: str, default: int) -> int:
    """Get environment variable as integer with fallback to default."""
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def get_env_bool_setting(key: str, default: bool) -> bool:
    """Get environment variable as boolean with fallback to default."""
    value = os.getenv(key, str(default)).lower()
    return value in ('true', '1', 'yes', 'on')


# Database settings
# PostgreSQL
POSTGRES_HOST = get_env_setting("POSTGRES_HOST", "postgresql")
POSTGRES_PORT = get_env_int_setting("POSTGRES_PORT", 5432)
POSTGRES_DB = get_env_setting("POSTGRES_DB", "postgres")
POSTGRES_USER = get_env_setting("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = get_env_setting("POSTGRES_PASSWORD", "CHANGE_ME")
PG_DSN = get_env_setting("PG_DSN", f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}")

# MySQL
MYSQL_HOST = get_env_setting("MYSQL_HOST", "mysql")
MYSQL_PORT = get_env_int_setting("MYSQL_PORT", 3306)
MYSQL_DB = get_env_setting("MYSQL_DB", "seedcore")
MYSQL_USER = get_env_setting("MYSQL_USER", "root")
MYSQL_PASSWORD = get_env_setting("MYSQL_PASSWORD", "CHANGE_ME")
MYSQL_DSN = get_env_setting("MYSQL_DSN", f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}")

# Redis
REDIS_HOST = get_env_setting("REDIS_HOST", "redis-master")
REDIS_PORT = get_env_int_setting("REDIS_PORT", 6379)
REDIS_DB = get_env_int_setting("REDIS_DB", 0)
REDIS_URL = get_env_setting("REDIS_URL", f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}")

# Neo4j
NEO4J_HOST = get_env_setting("NEO4J_HOST", "neo4j")
NEO4J_BOLT_PORT = get_env_int_setting("NEO4J_BOLT_PORT", 7687)
NEO4J_HTTP_PORT = get_env_int_setting("NEO4J_HTTP_PORT", 7474)
NEO4J_USER = get_env_setting("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = get_env_setting("NEO4J_PASSWORD", "password")
NEO4J_BOLT_URL = get_env_setting("NEO4J_BOLT_URL", f"bolt://{NEO4J_HOST}:{NEO4J_BOLT_PORT}")
NEO4J_HTTP_URL = get_env_setting("NEO4J_HTTP_URL", f"http://{NEO4J_HOST}:{NEO4J_HTTP_PORT}")
# Legacy support - keep NEO4J_URI for backward compatibility
NEO4J_URI = NEO4J_BOLT_URL

# Connection pool settings (kept for backward compatibility)
PG_POOL_SIZE = get_env_int_setting("POSTGRES_POOL_SIZE", 20)
PG_MAX_OVERFLOW = get_env_int_setting("POSTGRES_MAX_OVERFLOW", 10)
PG_POOL_TIMEOUT = get_env_int_setting("POSTGRES_POOL_TIMEOUT", 30)
PG_POOL_RECYCLE = get_env_int_setting("POSTGRES_POOL_RECYCLE", 1800)
PG_POOL_PRE_PING = get_env_bool_setting("POSTGRES_POOL_PRE_PING", True)

MYSQL_POOL_SIZE = get_env_int_setting("MYSQL_POOL_SIZE", 10)
MYSQL_MAX_OVERFLOW = get_env_int_setting("MYSQL_MAX_OVERFLOW", 5)
MYSQL_POOL_TIMEOUT = get_env_int_setting("MYSQL_POOL_TIMEOUT", 30)
MYSQL_POOL_RECYCLE = get_env_int_setting("MYSQL_POOL_RECYCLE", 1800)
MYSQL_POOL_PRE_PING = get_env_bool_setting("MYSQL_POOL_PRE_PING", True)

NEO4J_POOL_SIZE = get_env_int_setting("NEO4J_POOL_SIZE", 50)
NEO4J_CONNECTION_ACQUISITION_TIMEOUT = get_env_int_setting("NEO4J_CONNECTION_ACQUISITION_TIMEOUT", 30)


# =============================================================================
# PostgreSQL Engine Management
# =============================================================================

@lru_cache
def get_async_pg_engine() -> AsyncEngine:
    """
    Get cached async PostgreSQL engine with connection pooling.
    
    Returns:
        AsyncEngine: Configured async PostgreSQL engine
    """
    # Convert to async DSN if needed, avoiding double-prefixing
    if "+" not in PG_DSN:
        async_dsn = PG_DSN.replace("postgresql://", "postgresql+asyncpg://")
    else:
        async_dsn = PG_DSN
    
    # Extract hostname for logging
    hostname = urlparse(async_dsn).hostname
    
    logger.info(f"Creating async PostgreSQL engine for {hostname} with pool_size={PG_POOL_SIZE}")
    
    return create_async_engine(
        async_dsn,
        pool_size=PG_POOL_SIZE,
        max_overflow=PG_MAX_OVERFLOW,
        pool_timeout=PG_POOL_TIMEOUT,
        pool_recycle=PG_POOL_RECYCLE,
        pool_pre_ping=PG_POOL_PRE_PING,
        echo_pool=False,  # Set to True for debugging pool behavior
        future=True,
    )


@lru_cache
def get_sync_pg_engine():
    """
    Get cached sync PostgreSQL engine with connection pooling.
    
    Returns:
        Engine: Configured sync PostgreSQL engine
    """
    logger.info(f"Creating sync PostgreSQL engine with pool_size={PG_POOL_SIZE}")
    
    return create_engine(
        PG_DSN,
        pool_size=PG_POOL_SIZE,
        max_overflow=PG_MAX_OVERFLOW,
        pool_timeout=PG_POOL_TIMEOUT,
        pool_recycle=PG_POOL_RECYCLE,
        pool_pre_ping=PG_POOL_PRE_PING,
        echo_pool=False,
    )


# =============================================================================
# MySQL Engine Management
# =============================================================================

@lru_cache
def get_async_mysql_engine() -> AsyncEngine:
    """
    Get cached async MySQL engine with connection pooling.
    
    Returns:
        AsyncEngine: Configured async MySQL engine
    """
    # Get async DSN from environment or auto-convert sync DSN
    dsn = get_env_setting("MYSQL_DSN_ASYNC", "")
    if not dsn:
        base = MYSQL_DSN
        # Auto-convert driver if user only set MYSQL_DSN
        dsn = base.replace("mysql+pymysql://", "mysql+aiomysql://")
    else:
        # Ensure the async DSN uses aiomysql
        if "mysql+pymysql://" in dsn:
            dsn = dsn.replace("mysql+pymysql://", "mysql+aiomysql://")
    
    # Extract hostname for logging
    hostname = urlparse(dsn).hostname
    
    logger.info(f"Creating async MySQL engine for {hostname} with pool_size={MYSQL_POOL_SIZE}")
    
    return create_async_engine(
        dsn,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=MYSQL_POOL_SIZE,
        max_overflow=MYSQL_MAX_OVERFLOW,
        pool_timeout=MYSQL_POOL_TIMEOUT,
        future=True,
        echo=False,
    )


@lru_cache
def get_sync_mysql_engine():
    """
    Get cached sync MySQL engine with connection pooling.
    
    Returns:
        Engine: Configured sync MySQL engine
    """
    logger.info(f"Creating sync MySQL engine with pool_size={MYSQL_POOL_SIZE}")
    
    return create_engine(
        MYSQL_DSN,
        pool_size=MYSQL_POOL_SIZE,
        max_overflow=MYSQL_MAX_OVERFLOW,
        pool_timeout=MYSQL_POOL_TIMEOUT,
        pool_recycle=MYSQL_POOL_RECYCLE,
        pool_pre_ping=MYSQL_POOL_PRE_PING,
        echo_pool=False,
    )


# =============================================================================
# Neo4j Driver Management
# =============================================================================

@lru_cache
def get_neo4j_driver():
    """
    Get cached Neo4j driver with connection pooling.
    
    Returns:
        Driver: Configured Neo4j driver
    """
    logger.info(f"Creating Neo4j driver for {NEO4J_URI} with pool_size={NEO4J_POOL_SIZE}")
    
    try:
        return GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASSWORD),
            max_connection_pool_size=NEO4J_POOL_SIZE,
            connection_acquisition_timeout=NEO4J_CONNECTION_ACQUISITION_TIMEOUT,
        )
    except Exception as e:
        logger.error(f"Failed to create Neo4j driver: {e}")
        raise


# =============================================================================
# Session Factories (Lazy Loading)
# =============================================================================

# PostgreSQL session factories
def get_async_pg_session_factory():
    """Get async PostgreSQL session factory (lazy loaded)."""
    return async_sessionmaker(
        bind=get_async_pg_engine(),
        expire_on_commit=False,
        class_=AsyncSession,
    )

def get_sync_pg_session_factory():
    """Get sync PostgreSQL session factory (lazy loaded)."""
    return sessionmaker(
        bind=get_sync_pg_engine(),
        expire_on_commit=False,
    )

# MySQL session factories
def get_async_mysql_session_factory():
    """Get async MySQL session factory (lazy loaded)."""
    return async_sessionmaker(
        bind=get_async_mysql_engine(),
        expire_on_commit=False,
        class_=AsyncSession,
    )

def get_sync_mysql_session_factory():
    """Get sync MySQL session factory (lazy loaded)."""
    return sessionmaker(
        bind=get_sync_mysql_engine(),
        expire_on_commit=False,
    )


# =============================================================================
# FastAPI Dependency Functions
# =============================================================================

async def get_async_pg_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for async PostgreSQL sessions.
    
    Yields:
        AsyncSession: Async PostgreSQL database session
    """
    async with get_async_pg_session_factory()() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            logger.error(f"PostgreSQL session error: {e}")
            raise
        finally:
            await session.close()


async def get_async_mysql_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for async MySQL sessions.
    
    Yields:
        AsyncSession: Async MySQL database session
    """
    async with get_async_mysql_session_factory()() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            logger.error(f"MySQL session error: {e}")
            raise
        finally:
            await session.close()


def get_sync_pg_session() -> Session:
    """
    Get sync PostgreSQL session.
    
    Returns:
        Session: Sync PostgreSQL database session
    """
    return get_sync_pg_session_factory()()


def get_sync_mysql_session() -> Session:
    """
    Get sync MySQL session.
    
    Returns:
        Session: Sync MySQL database session
    """
    return get_sync_mysql_session_factory()()


# =============================================================================
# Neo4j Session Management
# =============================================================================

@asynccontextmanager
async def get_neo4j_session():
    """
    Context manager for Neo4j sessions.
    
    Yields:
        Session: Neo4j database session
    """
    driver = get_neo4j_driver()
    session = driver.session()
    try:
        yield session
    finally:
        session.close()
        driver.close()


# =============================================================================
# Legacy Compatibility Functions
# =============================================================================

def get_db_session():
    """
    Legacy function for backward compatibility.
    
    Yields:
        Session: Sync PostgreSQL database session
    """
    db = get_sync_pg_session()
    try:
        yield db
    finally:
        db.close()


def get_mysql_session():
    """
    Legacy function for backward compatibility.
    
    Yields:
        Session: Sync MySQL database session
    """
    db = get_sync_mysql_session()
    try:
        yield db
    finally:
        db.close()


# =============================================================================
# Health Check Functions
# =============================================================================

async def check_pg_health() -> bool:
    """
    Check PostgreSQL connection health.
    
    Returns:
        bool: True if connection is healthy
    """
    try:
        async with get_async_pg_session_factory()() as session:
            result = await session.execute(text("SELECT 1"))
            return result.scalar() == 1
    except Exception as e:
        logger.error(f"PostgreSQL health check failed: {e}")
        return False


async def check_mysql_health() -> bool:
    """
    Check MySQL connection health.
    
    Returns:
        bool: True if connection is healthy
    """
    try:
        async with get_async_mysql_session_factory()() as session:
            result = await session.execute(text("SELECT 1"))
            return result.scalar() == 1
    except Exception as e:
        logger.error(f"MySQL health check failed: {e}")
        return False


async def check_neo4j_health() -> bool:
    """
    Check Neo4j connection health.
    
    Returns:
        bool: True if connection is healthy
    """
    try:
        async with get_neo4j_session() as session:
            result = await session.run("RETURN 1")
            record = await result.single()
            return record[0] == 1
    except Exception as e:
        logger.error(f"Neo4j health check failed: {e}")
        return False


# =============================================================================
# Pool Statistics
# =============================================================================

def _safe_pool_stats(pool):
    """Safely collect pool statistics with error handling."""
    stats = {}
    try:
        stats["size"] = pool.size()
    except Exception:
        stats["size"] = None
    try:
        stats["checked_out"] = pool.checkedout()
    except Exception:
        stats["checked_out"] = None
    # "checked_in" isn't a direct API; approximate as size - checked_out if size is known
    stats["checked_in"] = (stats["size"] - stats["checked_out"]) if all(
        isinstance(stats[k], int) for k in ("size", "checked_out")) else None
    try:
        stats["overflow"] = pool.overflow()
    except Exception:
        stats["overflow"] = None
    return stats


def get_pg_pool_stats():
    """
    Get PostgreSQL pool statistics.
    
    Returns:
        dict: Pool statistics
    """
    engine = get_sync_pg_engine()
    return _safe_pool_stats(engine.pool)


def get_mysql_pool_stats():
    """
    Get MySQL pool statistics.
    
    Returns:
        dict: Pool statistics
    """
    engine = get_sync_mysql_engine()
    return _safe_pool_stats(engine.pool) 