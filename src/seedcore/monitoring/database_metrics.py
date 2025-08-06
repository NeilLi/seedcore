"""
Database connection pool metrics for Prometheus monitoring.

This module provides Prometheus metrics for monitoring database
connection pool health and performance.
"""

import time
from typing import Dict, Any
from prometheus_client import Gauge, Counter, Histogram, Info
from prometheus_client.registry import CollectorRegistry

from seedcore.database import (
    get_pg_pool_stats,
    get_mysql_pool_stats,
    get_async_pg_engine,
    get_async_mysql_engine,
    get_sync_pg_engine,
    get_sync_mysql_engine,
)


class DatabaseMetrics:
    """
    Prometheus metrics collector for database connection pools.
    
    This class provides comprehensive metrics for monitoring
    database connection pool health, performance, and utilization.
    """
    
    def __init__(self):
        """Initialize database metrics collectors."""
        
        # Create a custom registry for database metrics
        self.registry = CollectorRegistry()
        
        # Connection pool size metrics
        self.pool_size = Gauge(
            'database_pool_size',
            'Number of connections in the pool',
            ['database', 'engine_type'],
            registry=self.registry
        )
        
        # Connection pool utilization metrics
        self.pool_checked_out = Gauge(
            'database_pool_checked_out',
            'Number of connections currently checked out',
            ['database', 'engine_type'],
            registry=self.registry
        )
        
        self.pool_checked_in = Gauge(
            'database_pool_checked_in',
            'Number of connections currently checked in',
            ['database', 'engine_type'],
            registry=self.registry
        )
        
        self.pool_overflow = Gauge(
            'database_pool_overflow',
            'Number of overflow connections',
            ['database', 'engine_type'],
            registry=self.registry
        )
        
        self.pool_invalid = Gauge(
            'database_pool_invalid',
            'Number of invalid connections',
            ['database', 'engine_type'],
            registry=self.registry
        )
        
        # Connection pool utilization percentage
        self.pool_utilization = Gauge(
            'database_pool_utilization_percent',
            'Connection pool utilization percentage',
            ['database', 'engine_type'],
            registry=self.registry
        )
        
        # Connection errors
        self.connection_errors = Counter(
            'database_connection_errors_total',
            'Total number of database connection errors',
            ['database', 'engine_type', 'error_type'],
            registry=self.registry
        )
        
        # Query performance metrics
        self.query_duration = Histogram(
            'database_query_duration_seconds',
            'Database query duration in seconds',
            ['database', 'engine_type', 'query_type'],
            buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
            registry=self.registry
        )
        
        # Health check metrics
        self.health_check_duration = Histogram(
            'database_health_check_duration_seconds',
            'Database health check duration in seconds',
            ['database', 'engine_type'],
            buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5],
            registry=self.registry
        )
        
        self.health_status = Gauge(
            'database_health_status',
            'Database health status (1 = healthy, 0 = unhealthy)',
            ['database', 'engine_type'],
            registry=self.registry
        )
        
        # Database info
        self.database_info = Info(
            'database_info',
            'Database connection information',
            ['database', 'engine_type'],
            registry=self.registry
        )
        
        # Initialize database info
        self._initialize_database_info()
    
    def _initialize_database_info(self):
        """Initialize database information metrics."""
        try:
            # PostgreSQL info
            pg_engine = get_sync_pg_engine()
            self.database_info.labels(
                database='postgresql',
                engine_type='sync'
            ).info({
                'dsn': str(pg_engine.url).replace(pg_engine.url.password, '***'),
                'pool_size': str(pg_engine.pool.size()),
                'max_overflow': str(pg_engine.pool._max_overflow),
                'pool_timeout': str(pg_engine.pool._timeout),
                'pool_recycle': str(pg_engine.pool._recycle),
            })
            
            # MySQL info
            mysql_engine = get_sync_mysql_engine()
            self.database_info.labels(
                database='mysql',
                engine_type='sync'
            ).info({
                'dsn': str(mysql_engine.url).replace(mysql_engine.url.password, '***'),
                'pool_size': str(mysql_engine.pool.size()),
                'max_overflow': str(mysql_engine.pool._max_overflow),
                'pool_timeout': str(mysql_engine.pool._timeout),
                'pool_recycle': str(mysql_engine.pool._recycle),
            })
            
        except Exception as e:
            print(f"Error initializing database info: {e}")
    
    def update_pool_metrics(self):
        """Update all connection pool metrics."""
        try:
            # PostgreSQL metrics
            pg_stats = get_pg_pool_stats()
            self.pool_size.labels(
                database='postgresql',
                engine_type='sync'
            ).set(pg_stats['size'])
            
            self.pool_checked_out.labels(
                database='postgresql',
                engine_type='sync'
            ).set(pg_stats['checked_out'])
            
            self.pool_checked_in.labels(
                database='postgresql',
                engine_type='sync'
            ).set(pg_stats['checked_in'])
            
            self.pool_overflow.labels(
                database='postgresql',
                engine_type='sync'
            ).set(pg_stats['overflow'])
            
            self.pool_invalid.labels(
                database='postgresql',
                engine_type='sync'
            ).set(pg_stats['invalid'])
            
            # Calculate utilization percentage
            if pg_stats['size'] > 0:
                utilization = (pg_stats['checked_out'] / pg_stats['size']) * 100
                self.pool_utilization.labels(
                    database='postgresql',
                    engine_type='sync'
                ).set(utilization)
            
            # MySQL metrics
            mysql_stats = get_mysql_pool_stats()
            self.pool_size.labels(
                database='mysql',
                engine_type='sync'
            ).set(mysql_stats['size'])
            
            self.pool_checked_out.labels(
                database='mysql',
                engine_type='sync'
            ).set(mysql_stats['checked_out'])
            
            self.pool_checked_in.labels(
                database='mysql',
                engine_type='sync'
            ).set(mysql_stats['checked_in'])
            
            self.pool_overflow.labels(
                database='mysql',
                engine_type='sync'
            ).set(mysql_stats['overflow'])
            
            self.pool_invalid.labels(
                database='mysql',
                engine_type='sync'
            ).set(mysql_stats['invalid'])
            
            # Calculate utilization percentage
            if mysql_stats['size'] > 0:
                utilization = (mysql_stats['checked_out'] / mysql_stats['size']) * 100
                self.pool_utilization.labels(
                    database='mysql',
                    engine_type='sync'
                ).set(utilization)
                
        except Exception as e:
            print(f"Error updating pool metrics: {e}")
    
    def record_connection_error(self, database: str, engine_type: str, error_type: str):
        """Record a database connection error."""
        self.connection_errors.labels(
            database=database,
            engine_type=engine_type,
            error_type=error_type
        ).inc()
    
    def record_query_duration(self, database: str, engine_type: str, query_type: str, duration: float):
        """Record database query duration."""
        self.query_duration.labels(
            database=database,
            engine_type=engine_type,
            query_type=query_type
        ).observe(duration)
    
    def record_health_check(self, database: str, engine_type: str, is_healthy: bool, duration: float):
        """Record database health check results."""
        self.health_check_duration.labels(
            database=database,
            engine_type=engine_type
        ).observe(duration)
        
        self.health_status.labels(
            database=database,
            engine_type=engine_type
        ).set(1 if is_healthy else 0)
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get a summary of current metrics."""
        try:
            pg_stats = get_pg_pool_stats()
            mysql_stats = get_mysql_pool_stats()
            
            return {
                'postgresql': {
                    'pool_size': pg_stats['size'],
                    'checked_out': pg_stats['checked_out'],
                    'checked_in': pg_stats['checked_in'],
                    'overflow': pg_stats['overflow'],
                    'invalid': pg_stats['invalid'],
                    'utilization_percent': round((pg_stats['checked_out'] / pg_stats['size']) * 100, 2) if pg_stats['size'] > 0 else 0
                },
                'mysql': {
                    'pool_size': mysql_stats['size'],
                    'checked_out': mysql_stats['checked_out'],
                    'checked_in': mysql_stats['checked_in'],
                    'overflow': mysql_stats['overflow'],
                    'invalid': mysql_stats['invalid'],
                    'utilization_percent': round((mysql_stats['checked_out'] / mysql_stats['size']) * 100, 2) if mysql_stats['size'] > 0 else 0
                }
            }
        except Exception as e:
            return {'error': str(e)}


# Global metrics instance
db_metrics = DatabaseMetrics()


# =============================================================================
# Decorators for automatic metrics collection
# =============================================================================

def monitor_query(database: str, engine_type: str, query_type: str = "general"):
    """
    Decorator to automatically monitor database query performance.
    
    Args:
        database: Database name ("postgresql", "mysql", "neo4j")
        engine_type: Engine type ("sync", "async")
        query_type: Type of query for categorization
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                db_metrics.record_query_duration(database, engine_type, query_type, duration)
                return result
            except Exception as e:
                duration = time.time() - start_time
                db_metrics.record_query_duration(database, engine_type, query_type, duration)
                db_metrics.record_connection_error(database, engine_type, "query_error")
                raise
        return wrapper
    return decorator


def monitor_health_check(database: str, engine_type: str):
    """
    Decorator to automatically monitor database health checks.
    
    Args:
        database: Database name ("postgresql", "mysql", "neo4j")
        engine_type: Engine type ("sync", "async")
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                db_metrics.record_health_check(database, engine_type, True, duration)
                return result
            except Exception as e:
                duration = time.time() - start_time
                db_metrics.record_health_check(database, engine_type, False, duration)
                db_metrics.record_connection_error(database, engine_type, "health_check_error")
                raise
        return wrapper
    return decorator


# =============================================================================
# Background metrics collection
# =============================================================================

import threading
import time


class MetricsCollector:
    """Background metrics collector that periodically updates pool metrics."""
    
    def __init__(self, interval: int = 30):
        """
        Initialize metrics collector.
        
        Args:
            interval: Collection interval in seconds
        """
        self.interval = interval
        self.running = False
        self.thread = None
    
    def start(self):
        """Start the background metrics collection."""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._collect_metrics, daemon=True)
            self.thread.start()
            print(f"Database metrics collector started (interval: {self.interval}s)")
    
    def stop(self):
        """Stop the background metrics collection."""
        self.running = False
        if self.thread:
            self.thread.join()
            print("Database metrics collector stopped")
    
    def _collect_metrics(self):
        """Background metrics collection loop."""
        while self.running:
            try:
                db_metrics.update_pool_metrics()
                time.sleep(self.interval)
            except Exception as e:
                print(f"Error in metrics collection: {e}")
                time.sleep(self.interval)


# Global metrics collector instance
metrics_collector = MetricsCollector()


def start_metrics_collection(interval: int = 30):
    """Start background metrics collection."""
    global metrics_collector
    metrics_collector = MetricsCollector(interval)
    metrics_collector.start()


def stop_metrics_collection():
    """Stop background metrics collection."""
    global metrics_collector
    metrics_collector.stop() 