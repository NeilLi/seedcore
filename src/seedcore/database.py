"""
Database connection management with robust connection pooling.

This module provides centralized database engine creation with configurable
connection pools for PostgreSQL, MySQL, and Neo4j. All engines/drivers are
cached as singletons to ensure efficient resource usage across FastAPI requests
and Ray tasks.
"""

import os
import logging
from functools import lru_cache
from typing import Optional, AsyncGenerator, Dict, Any, Generator
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

# ✅ Use the async Neo4j driver
from neo4j import AsyncGraphDatabase

logger = logging.getLogger(__name__)

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

    # FastAPI deps
    "get_async_pg_session",
    "get_async_mysql_session",
    "get_sync_pg_session",
    "get_sync_mysql_session",

    # Neo4j session / helpers
    "get_neo4j_session",
    "warm_neo4j_pool",

    # Health checks
    "check_pg_health",
    "check_mysql_health",
    "check_neo4j_health",

    # Pool statistics
    "get_pg_pool_stats",
    "get_mysql_pool_stats",

    # Legacy
    "get_db_session",
    "get_mysql_session",
]

# ─────────────────────────────────────────────────────────────────────
# Env helpers
# ─────────────────────────────────────────────────────────────────────

def get_env_setting(key: str, default: str) -> str:
    return os.getenv(key, default)

def get_env_int_setting(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default

def get_env_bool_setting(key: str, default: bool) -> bool:
    value = os.getenv(key, str(default)).lower()
    return value in ("true", "1", "yes", "on")

# ─────────────────────────────────────────────────────────────────────
# DB settings
# ─────────────────────────────────────────────────────────────────────

def _infer_encrypted_from_uri(uri: str) -> bool:
    """Parse encryption from URI unless explicitly overridden."""
    scheme = uri.split("://", 1)[0].lower()
    # Secure schemes per Neo4j driver docs
    return scheme in ("neo4j+s", "neo4j+ssc", "bolt+s", "bolt+ssc")

# PostgreSQL
POSTGRES_HOST = get_env_setting("POSTGRES_HOST", "postgresql")
POSTGRES_PORT = get_env_int_setting("POSTGRES_PORT", 5432)
POSTGRES_DB = get_env_setting("POSTGRES_DB", "postgres")
POSTGRES_USER = get_env_setting("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = get_env_setting("POSTGRES_PASSWORD", "CHANGE_ME")
PG_DSN = get_env_setting(
    "PG_DSN",
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}",
)

# MySQL
MYSQL_HOST = get_env_setting("MYSQL_HOST", "mysql")
MYSQL_PORT = get_env_int_setting("MYSQL_PORT", 3306)
MYSQL_DB = get_env_setting("MYSQL_DB", "seedcore")
MYSQL_USER = get_env_setting("MYSQL_USER", "root")
MYSQL_PASSWORD = get_env_setting("MYSQL_PASSWORD", "CHANGE_ME")
MYSQL_DSN = get_env_setting(
    "MYSQL_DSN",
    f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}",
)

# Redis (not used here, but kept for completeness)
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
# Prefer override by NEO4J_URI (neo4j:// for cluster, bolt:// for direct)
NEO4J_URI = get_env_setting("NEO4J_URI", NEO4J_BOLT_URL)

# Pool config (SQL)
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

# Pool/config (Neo4j)
NEO4J_POOL_SIZE = get_env_int_setting("NEO4J_POOL_SIZE", 50)
NEO4J_CONNECTION_ACQUISITION_TIMEOUT = get_env_int_setting("NEO4J_CONNECTION_ACQUISITION_TIMEOUT", 30)
NEO4J_MAX_CONNECTION_LIFETIME = get_env_int_setting("NEO4J_MAX_CONNECTION_LIFETIME", 3600)  # seconds
NEO4J_MAX_TX_RETRY_TIME = get_env_int_setting("NEO4J_MAX_TX_RETRY_TIME", 15)  # seconds

# Prefer explicit env override; otherwise infer from URI
_env_enc = get_env_setting("NEO4J_ENCRYPTED", "").strip().lower()
if _env_enc in ("true", "1", "yes", "on"):
    NEO4J_ENCRYPTED = True
elif _env_enc in ("false", "0", "no", "off"):
    NEO4J_ENCRYPTED = False
else:
    NEO4J_ENCRYPTED = _infer_encrypted_from_uri(NEO4J_URI)

NEO4J_KEEP_ALIVE = get_env_bool_setting("NEO4J_KEEP_ALIVE", True)
NEO4J_DATABASE = get_env_setting("NEO4J_DATABASE", "neo4j")
NEO4J_FETCH_SIZE = get_env_int_setting("NEO4J_FETCH_SIZE", 1000)  # driver default is usually fine

# ─────────────────────────────────────────────────────────────────────
# PostgreSQL Engines
# ─────────────────────────────────────────────────────────────────────

@lru_cache
def get_async_pg_engine() -> AsyncEngine:
    # Prefer explicit async DSN if provided
    dsn = get_env_setting("PG_DSN_ASYNC", "").strip()
    if not dsn:
        dsn = PG_DSN.strip()

    # Normalize to async driver regardless of incoming scheme/driver
    # e.g., postgresql://..., postgresql+psycopg://..., postgresql+psycopg2://...
    import re
    dsn = re.sub(r"^postgresql(\+[a-z0-9_]+)?://", "postgresql+asyncpg://", dsn, flags=re.IGNORECASE)

    hostname = urlparse(dsn).hostname
    logger.info(f"Creating async PostgreSQL engine for {hostname} (pool_size={PG_POOL_SIZE})")

    return create_async_engine(
        dsn,
        pool_size=PG_POOL_SIZE,
        max_overflow=PG_MAX_OVERFLOW,
        pool_timeout=PG_POOL_TIMEOUT,
        pool_recycle=PG_POOL_RECYCLE,
        pool_pre_ping=PG_POOL_PRE_PING,
        echo_pool=False,
        future=True,
    )

@lru_cache
def get_sync_pg_engine():
    logger.info(f"Creating sync PostgreSQL engine (pool_size={PG_POOL_SIZE})")
    return create_engine(
        PG_DSN,
        pool_size=PG_POOL_SIZE,
        max_overflow=PG_MAX_OVERFLOW,
        pool_timeout=PG_POOL_TIMEOUT,
        pool_recycle=PG_POOL_RECYCLE,
        pool_pre_ping=PG_POOL_PRE_PING,
        echo_pool=False,
    )

# ─────────────────────────────────────────────────────────────────────
# MySQL Engines
# ─────────────────────────────────────────────────────────────────────

@lru_cache
def get_async_mysql_engine() -> AsyncEngine:
    dsn = get_env_setting("MYSQL_DSN_ASYNC", "")
    if not dsn:
        dsn = MYSQL_DSN.replace("mysql+pymysql://", "mysql+aiomysql://")
    else:
        if "mysql+pymysql://" in dsn:
            dsn = dsn.replace("mysql+pymysql://", "mysql+aiomysql://")
    hostname = urlparse(dsn).hostname
    logger.info(f"Creating async MySQL engine for {hostname} (pool_size={MYSQL_POOL_SIZE})")
    return create_async_engine(
        dsn,
        pool_pre_ping=True,
        pool_recycle=MYSQL_POOL_RECYCLE,
        pool_size=MYSQL_POOL_SIZE,
        max_overflow=MYSQL_MAX_OVERFLOW,
        pool_timeout=MYSQL_POOL_TIMEOUT,
        future=True,
        echo=False,
    )

@lru_cache
def get_sync_mysql_engine():
    logger.info(f"Creating sync MySQL engine (pool_size={MYSQL_POOL_SIZE})")
    return create_engine(
        MYSQL_DSN,
        pool_size=MYSQL_POOL_SIZE,
        max_overflow=MYSQL_MAX_OVERFLOW,
        pool_timeout=MYSQL_POOL_TIMEOUT,
        pool_recycle=MYSQL_POOL_RECYCLE,
        pool_pre_ping=MYSQL_POOL_PRE_PING,
        echo_pool=False,
    )

# ─────────────────────────────────────────────────────────────────────
# Neo4j Driver (Async) — keep warm & pooled
# ─────────────────────────────────────────────────────────────────────

@lru_cache
def get_neo4j_driver():
    """
    Get a cached Async Neo4j driver with connection pooling.
    IMPORTANT: Do NOT close this driver per request; keep it warm.
    """
    driver_kwargs: Dict[str, Any] = dict(
        auth=(NEO4J_USER, NEO4J_PASSWORD),
        max_connection_pool_size=NEO4J_POOL_SIZE,
        connection_acquisition_timeout=NEO4J_CONNECTION_ACQUISITION_TIMEOUT,
        max_connection_lifetime=NEO4J_MAX_CONNECTION_LIFETIME,
        max_transaction_retry_time=NEO4J_MAX_TX_RETRY_TIME,
        encrypted=NEO4J_ENCRYPTED,
        # keep_alive may not be supported by some versions; we'll try and fall back
        keep_alive=NEO4J_KEEP_ALIVE,
    )

    logger.info(
        "Creating Async Neo4j driver for %s "
        "(pool_size=%s, enc=%s, keep_alive=%s, db=%s)",
        NEO4J_URI, NEO4J_POOL_SIZE, NEO4J_ENCRYPTED, NEO4J_KEEP_ALIVE, NEO4J_DATABASE
    )

    try:
        return AsyncGraphDatabase.driver(NEO4J_URI, **driver_kwargs)
    except TypeError as e:
        # Fallback: remove keep_alive if unsupported
        if "keep_alive" in driver_kwargs:
            logger.warning("Neo4j driver does not support keep_alive kwarg, retrying without it: %s", e)
            driver_kwargs.pop("keep_alive", None)
            return AsyncGraphDatabase.driver(NEO4J_URI, **driver_kwargs)
        raise
    except Exception as e:
        logger.error(f"Failed to create Neo4j driver: {e}")
        raise

@asynccontextmanager
async def get_neo4j_session():
    """
    Async context manager for Neo4j sessions.
    NOTE: We keep the driver open (singleton); only open/close the session.
    """
    driver = get_neo4j_driver()
    session = driver.session(database=NEO4J_DATABASE, fetch_size=NEO4J_FETCH_SIZE)
    try:
        yield session
    finally:
        await session.close()
        # DO NOT close the driver here; it is a cached singleton.

# Optional: pre-warm the pool at app startup to avoid first-hit latency.
async def warm_neo4j_pool(min_sessions: int = 4) -> None:
    """
    Open a few sessions and run a trivial query to populate the pool and
    routing tables. This hides the initial 4–5s handshake from the first user.
    """
    try:
        driver = get_neo4j_driver()
        async def _ping():
            async with driver.session(database=NEO4J_DATABASE) as s:
                res = await s.run("RETURN 1")
                await res.consume()

        import asyncio
        await asyncio.gather(*[_ping() for _ in range(max(1, min_sessions))])
        logger.info("Neo4j pool pre-warmed with %d sessions.", min_sessions)
    except Exception as e:
        logger.warning(f"Neo4j pool pre-warm skipped/failed: {e}")

# ─────────────────────────────────────────────────────────────────────
# Session factories (SQL)
# ─────────────────────────────────────────────────────────────────────

def get_async_pg_session_factory():
    return async_sessionmaker(bind=get_async_pg_engine(), expire_on_commit=False, class_=AsyncSession)

def get_sync_pg_session_factory():
    return sessionmaker(bind=get_sync_pg_engine(), expire_on_commit=False)

def get_async_mysql_session_factory():
    return async_sessionmaker(bind=get_async_mysql_engine(), expire_on_commit=False, class_=AsyncSession)

def get_sync_mysql_session_factory():
    return sessionmaker(bind=get_sync_mysql_engine(), expire_on_commit=False)

# ─────────────────────────────────────────────────────────────────────
# FastAPI Dependencies (SQL)
# ─────────────────────────────────────────────────────────────────────

async def get_async_pg_session() -> AsyncGenerator[AsyncSession, None]:
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
    return get_sync_pg_session_factory()()

def get_sync_mysql_session() -> Session:
    return get_sync_mysql_session_factory()()

# ─────────────────────────────────────────────────────────────────────
# Legacy Compatibility (SQL)
# ─────────────────────────────────────────────────────────────────────

def get_db_session() -> Generator[Session, None, None]:
    db = get_sync_pg_session()
    try:
        yield db
    finally:
        db.close()

def get_mysql_session() -> Generator[Session, None, None]:
    db = get_sync_mysql_session()
    try:
        yield db
    finally:
        db.close()

# ─────────────────────────────────────────────────────────────────────
# Health Checks
# ─────────────────────────────────────────────────────────────────────

async def check_pg_health() -> bool:
    try:
        async with get_async_pg_session_factory()() as session:
            result = await session.execute(text("SELECT 1"))
            return (result.scalar_one_or_none() == 1)
    except Exception as e:
        logger.error(f"PostgreSQL health check failed: {e}")
        return False

async def check_mysql_health() -> bool:
    try:
        async with get_async_mysql_session_factory()() as session:
            result = await session.execute(text("SELECT 1"))
            return (result.scalar_one_or_none() == 1)
    except Exception as e:
        logger.error(f"MySQL health check failed: {e}")
        return False

async def check_neo4j_health() -> bool:
    """
    Minimal read query; uses pooled session (no driver teardown).
    """
    try:
        async with get_neo4j_session() as session:
            result = await session.run("RETURN 1")
            record = await result.single()
            return (record is not None) and (record[0] == 1)
    except Exception as e:
        logger.error(f"Neo4j health check failed: {e}")
        return False

# ─────────────────────────────────────────────────────────────────────
# Pool Statistics (SQL engines only)
# ─────────────────────────────────────────────────────────────────────

def _safe_pool_stats(pool):
    stats = {}
    try:
        stats["size"] = pool.size()
    except Exception:
        stats["size"] = None
    try:
        stats["checked_out"] = pool.checkedout()
    except Exception:
        stats["checked_out"] = None
    stats["checked_in"] = (
        (stats["size"] - stats["checked_out"])
        if all(isinstance(stats.get(k), int) for k in ("size", "checked_out"))
        else None
    )
    try:
        stats["overflow"] = pool.overflow()
    except Exception:
        stats["overflow"] = None
    # Add invalid connections count (default to 0 if not tracked)
    try:
        stats["invalid"] = getattr(pool, 'invalid', 0)
    except Exception:
        stats["invalid"] = 0
    return stats

def get_pg_pool_stats():
    engine = get_sync_pg_engine()
    return _safe_pool_stats(engine.pool)

def get_mysql_pool_stats():
    engine = get_sync_mysql_engine()
    return _safe_pool_stats(engine.pool)
