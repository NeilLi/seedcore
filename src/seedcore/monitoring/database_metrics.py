# src/seedcore/monitoring/database_metrics.py
from __future__ import annotations

import logging
import threading
import time
import functools
from typing import Optional, Dict, Any, Callable

from prometheus_client import CollectorRegistry, Gauge  # no global default registry use

# Import lazily referenced helpers from your db module.
# These imports are **inside** functions where used to avoid circular imports at module load time.
#   get_pg_pool_stats(), get_mysql_pool_stats() -> dicts with keys: size, checked_out, checked_in, overflow
logger = logging.getLogger(__name__)


def monitor_query(database: str, connection_type: str, operation: str):
    """
    Decorator to monitor database query performance and success rates.
    
    Args:
        database: Database type (postgresql, mysql, neo4j)
        connection_type: Connection type (sync, async)
        operation: Operation name for identification
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                logger.info(f"Query {operation} on {database} ({connection_type}) completed in {duration:.3f}s")
                return result
            except Exception as e:
                duration = time.time() - start_time
                logger.error(f"Query {operation} on {database} ({connection_type}) failed after {duration:.3f}s: {e}")
                raise
        return wrapper
    
    def async_decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time
                logger.info(f"Query {operation} on {database} ({connection_type}) completed in {duration:.3f}s")
                return result
            except Exception as e:
                duration = time.time() - start_time
                logger.error(f"Query {operation} on {database} ({connection_type}) failed after {duration:.3f}s: {e}")
                raise
        return async_wrapper
    
    def actual_decorator(func):
        if asyncio.iscoroutinefunction(func):
            return async_decorator(func)
        else:
            return decorator(func)
    
    return actual_decorator


def monitor_health_check(database: str, connection_type: str):
    """
    Decorator to monitor database health check performance and success rates.
    
    Args:
        database: Database type (postgresql, mysql, neo4j)
        connection_type: Connection type (sync, async)
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                logger.info(f"Health check {database} ({connection_type}) completed in {duration:.3f}s: {result}")
                return result
            except Exception as e:
                duration = time.time() - start_time
                logger.error(f"Health check {database} ({connection_type}) failed after {duration:.3f}s: {e}")
                raise
        return wrapper
    
    def async_decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time
                logger.info(f"Health check {database} ({connection_type}) completed in {duration:.3f}s: {result}")
                return result
            except Exception as e:
                duration = time.time() - start_time
                logger.error(f"Health check {database} ({connection_type}) failed after {duration:.3f}s: {e}")
                raise
        return async_wrapper
    
    def actual_decorator(func):
        if asyncio.iscoroutinefunction(func):
            return async_decorator(func)
        else:
            return decorator(func)
    
    return actual_decorator


class DatabaseMetrics:
    """
    Collects and exposes DB pool metrics into a private Prometheus registry.

    Use update_pool_metrics() to refresh values. This class does NOT run a web server;
    your application can export the registry or scrape it elsewhere.
    """

    def __init__(self, registry: Optional[CollectorRegistry] = None) -> None:
        self.registry = registry or CollectorRegistry()

        # Gauges for PostgreSQL pool
        self.pg_size = Gauge("db_pg_pool_size", "PostgreSQL pool size", registry=self.registry)
        self.pg_checked_out = Gauge("db_pg_pool_checked_out", "PostgreSQL checked out connections", registry=self.registry)
        self.pg_checked_in = Gauge("db_pg_pool_checked_in", "PostgreSQL checked in connections", registry=self.registry)
        self.pg_overflow = Gauge("db_pg_pool_overflow", "PostgreSQL pool overflow", registry=self.registry)

        # Gauges for MySQL pool
        self.my_size = Gauge("db_mysql_pool_size", "MySQL pool size", registry=self.registry)
        self.my_checked_out = Gauge("db_mysql_pool_checked_out", "MySQL checked out connections", registry=self.registry)
        self.my_checked_in = Gauge("db_mysql_pool_checked_in", "MySQL checked in connections", registry=self.registry)
        self.my_overflow = Gauge("db_mysql_pool_overflow", "MySQL pool overflow", registry=self.registry)

        # Gauges for Neo4j pool
        self.neo4j_size = Gauge("db_neo4j_pool_size", "Neo4j pool size", registry=self.registry)
        self.neo4j_checked_out = Gauge("db_neo4j_pool_checked_out", "Neo4j checked out connections", registry=self.registry)
        self.neo4j_checked_in = Gauge("db_neo4j_pool_checked_in", "Neo4j checked in connections", registry=self.registry)
        self.neo4j_overflow = Gauge("db_neo4j_pool_overflow", "Neo4j pool overflow", registry=self.registry)

        # Optional background thread controls
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._interval = 30

    @staticmethod
    def _safe_set(g: Gauge, value: Any) -> None:
        try:
            if value is None:
                # Use 0 when unavailable to keep time series continuous
                g.set(0)
            else:
                g.set(float(value))
        except Exception:
            # Never raise from metrics path
            logger.debug("Skipping metric set for %s due to invalid value=%r", g._name, value)

    def _get_stats(self, getter: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
        try:
            return getter() or {}
        except Exception as e:
            logger.debug("Pool stats getter failed: %s", e)
            return {}

    def update_pool_metrics(self) -> bool:
        """
        Pulls stats from pool getters and updates gauges.
        Returns True on success, False if all providers look invalid.
        """
        # Local import to avoid circulars at module import time
        from seedcore.database import get_pg_pool_stats, get_mysql_pool_stats

        pg = self._get_stats(get_pg_pool_stats)
        my = self._get_stats(get_mysql_pool_stats)

        # Recognize invalid payloads (e.g., strings, 'invalid', etc.)
        def valid(d: Dict[str, Any]) -> bool:
            return isinstance(d, dict) and any(k in d for k in ("size", "checked_out", "checked_in", "overflow"))

        # Update PG
        self._safe_set(self.pg_size, pg.get("size"))
        self._safe_set(self.pg_checked_out, pg.get("checked_out"))
        self._safe_set(self.pg_checked_in, pg.get("checked_in"))
        self._safe_set(self.pg_overflow, pg.get("overflow"))

        # Update MySQL
        self._safe_set(self.my_size, my.get("size"))
        self._safe_set(self.my_checked_out, my.get("checked_out"))
        self._safe_set(self.my_checked_in, my.get("checked_in"))
        self._safe_set(self.my_overflow, my.get("overflow"))

        # Update Neo4j (using driver pool info)
        try:
            from seedcore.database import get_neo4j_driver
            driver = get_neo4j_driver()
            # Neo4j driver doesn't expose pool stats the same way, so we'll set defaults
            self._safe_set(self.neo4j_size, getattr(driver, '_pool', None) and getattr(driver._pool, 'size', None) or 0)
            self._safe_set(self.neo4j_checked_out, 0)  # Neo4j doesn't track this
            self._safe_set(self.neo4j_checked_in, 0)   # Neo4j doesn't track this
            self._safe_set(self.neo4j_overflow, 0)     # Neo4j doesn't track this
        except Exception as e:
            logger.debug("Neo4j pool stats unavailable: %s", e)
            # Set Neo4j metrics to 0 when unavailable
            self._safe_set(self.neo4j_size, 0)
            self._safe_set(self.neo4j_checked_out, 0)
            self._safe_set(self.neo4j_checked_in, 0)
            self._safe_set(self.neo4j_overflow, 0)

        return valid(pg) or valid(my)

    # ---------- optional background loop ----------

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                ok = self.update_pool_metrics()
                if not ok:
                    logger.debug("Pool metrics update returned False (no valid providers yet).")
            except Exception as e:
                # Never crash the thread
                logger.debug("Error updating pool metrics: %r", e)
            # Wait for interval or early stop
            self._stop.wait(self._interval)

    def start(self, interval_seconds: int = 30) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._interval = max(1, int(interval_seconds))
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="db-metrics-loop", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)


# Module-level helpers expected by your validator
_metrics_singleton: Optional[DatabaseMetrics] = None

def start_metrics_collection(interval_seconds: int = 30) -> DatabaseMetrics:
    """Create (or reuse) a singleton DatabaseMetrics and start background updates."""
    global _metrics_singleton
    if _metrics_singleton is None:
        _metrics_singleton = DatabaseMetrics()
    _metrics_singleton.start(interval_seconds=interval_seconds)
    return _metrics_singleton

def stop_metrics_collection() -> None:
    """Stop the background updater if running."""
    global _metrics_singleton
    if _metrics_singleton:
        _metrics_singleton.stop()
