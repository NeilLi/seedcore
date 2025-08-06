# Database Connection Pooling Implementation

This document provides comprehensive documentation for the robust database connection pooling system implemented in SeedCore.

## Overview

The SeedCore database connection pooling system provides efficient, configurable, and observable database connections for PostgreSQL, MySQL, and Neo4j. The implementation is designed to work seamlessly with both FastAPI (async) and Ray (distributed computing) workloads.

## Architecture

### Key Components

1. **Centralized Engine Management** (`src/seedcore/database.py`)
   - Singleton engine creation with `@lru_cache`
   - Configurable pool sizes via environment variables
   - Support for both sync and async operations

2. **FastAPI Integration** (`src/seedcore/api/database_example.py`)
   - Dependency injection for database sessions
   - Automatic connection management
   - Health check endpoints

3. **Ray Integration** (`src/seedcore/ray/database_actor_example.py`)
   - Actor-based connection pooling
   - Distributed database operations
   - Efficient resource sharing

4. **Monitoring & Observability** (`src/seedcore/monitoring/database_metrics.py`)
   - Prometheus metrics collection
   - Pool statistics and health monitoring
   - Performance tracking

5. **Advanced Pooling** (PgBouncer)
   - External connection pooling for high-scale deployments
   - Transaction-level pooling
   - Connection multiplexing

## Configuration

### Environment Variables

All connection pool settings are configurable via environment variables in `docker/env.example`:

```bash
# PostgreSQL Connection Pool Settings
POSTGRES_POOL_SIZE=20
POSTGRES_MAX_OVERFLOW=10
POSTGRES_POOL_TIMEOUT=30
POSTGRES_POOL_RECYCLE=1800
POSTGRES_POOL_PRE_PING=true

# MySQL Connection Pool Settings
MYSQL_POOL_SIZE=10
MYSQL_MAX_OVERFLOW=5
MYSQL_POOL_TIMEOUT=30
MYSQL_POOL_RECYCLE=1800
MYSQL_POOL_PRE_PING=true

# Neo4j Connection Pool Settings
NEO4J_POOL_SIZE=50
NEO4J_CONNECTION_ACQUISITION_TIMEOUT=30
```

### Pool Sizing Guidelines

| Component | Formula | Example |
|-----------|---------|---------|
| `pool_size` | `ceil(max_rps * avg_query_time)` | 20 connections |
| `max_overflow` | `pool_size / 2` | 10 connections |
| PostgreSQL `max_connections` | `sum(all_app_pool_sizes) + 50` | 270 connections |

## Usage Examples

### FastAPI Integration

```python
from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from seedcore.database import get_async_pg_session

app = FastAPI()

@app.get("/users")
async def get_users(session: AsyncSession = Depends(get_async_pg_session)):
    result = await session.execute(text("SELECT * FROM users"))
    return result.fetchall()
```

### Ray Actor Pattern

```python
import ray
from seedcore.database import get_async_pg_engine
from sqlalchemy.ext.asyncio import async_sessionmaker

@ray.remote
class DatabaseWorker:
    def __init__(self):
        self.engine = get_async_pg_engine()
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            expire_on_commit=False
        )
    
    async def process_data(self, data):
        async with self.session_factory() as session:
            # Process data with pooled connection
            pass
```

### Sync Operations

```python
from seedcore.database import get_sync_pg_session

def sync_operation():
    session = get_sync_pg_session()
    try:
        result = session.execute(text("SELECT 1"))
        return result.scalar()
    finally:
        session.close()
```

## Monitoring & Observability

### Prometheus Metrics

The system exports comprehensive Prometheus metrics:

```python
# Connection pool metrics
database_pool_size{database="postgresql",engine_type="sync"}
database_pool_checked_out{database="postgresql",engine_type="sync"}
database_pool_utilization_percent{database="postgresql",engine_type="sync"}

# Performance metrics
database_query_duration_seconds{database="postgresql",engine_type="sync",query_type="select"}

# Health metrics
database_health_status{database="postgresql",engine_type="sync"}
```

### Health Check Endpoints

```bash
# Check all databases
curl http://localhost:8002/health/all

# Check specific database
curl http://localhost:8002/async/pg/health

# Get pool statistics
curl http://localhost:8002/stats/pg
```

### Grafana Dashboards

Access Grafana at `http://localhost:3000` to view:
- Connection pool utilization
- Query performance metrics
- Health status monitoring
- Error rates and trends

## Advanced Features

### PgBouncer Integration

For high-scale deployments, PgBouncer provides external connection pooling:

```yaml
# docker-compose.yml
pgbouncer:
  image: edoburu/pgbouncer:1.20.2
  environment:
    DATABASE_URL: postgres://postgres:password@postgres:5432/postgres
    POOL_MODE: transaction
    MAX_CLIENT_CONN: 1000
    DEFAULT_POOL_SIZE: 20
```

### Connection Pool Decorators

Automatic metrics collection with decorators:

```python
from seedcore.monitoring.database_metrics import monitor_query

@monitor_query("postgresql", "sync", "user_queries")
def get_user_by_id(user_id: int):
    session = get_sync_pg_session()
    try:
        result = session.execute(text("SELECT * FROM users WHERE id = :id"), {"id": user_id})
        return result.fetchone()
    finally:
        session.close()
```

## Performance Optimization

### Pool Configuration Tuning

1. **Start Small**: Begin with conservative pool sizes
2. **Monitor Utilization**: Watch pool utilization in Grafana
3. **Scale Gradually**: Increase pool sizes based on metrics
4. **Consider PgBouncer**: For high concurrency scenarios

### Best Practices

1. **Use Appropriate Session Types**:
   - Async sessions for FastAPI endpoints
   - Sync sessions for Ray actors and background tasks

2. **Proper Resource Management**:
   - Always close sessions in finally blocks
   - Use context managers when possible

3. **Connection Pooling**:
   - Let the pool handle connection lifecycle
   - Avoid manual connection management

4. **Monitoring**:
   - Set up alerts for high pool utilization
   - Monitor query performance trends
   - Track connection errors

## Troubleshooting

### Common Issues

1. **Connection Exhaustion**
   ```
   Error: FATAL: remaining connection slots are reserved for non-replication superuser connections
   ```
   **Solution**: Increase pool size or add PgBouncer

2. **Connection Timeouts**
   ```
   Error: connection to server at "localhost" (127.0.0.1), port 5432 failed: timeout expired
   ```
   **Solution**: Check network connectivity and increase timeout settings

3. **Pool Overflow**
   ```
   Error: QueuePool limit of size X overflow Y reached
   ```
   **Solution**: Increase pool size or max_overflow

### Debug Commands

```bash
# Check pool statistics
curl http://localhost:8002/stats/pg

# Test database connectivity
curl http://localhost:8002/async/pg/test

# Monitor pool metrics
docker exec -it seedcore-api python -c "
from seedcore.database import get_pg_pool_stats
print(get_pg_pool_stats())
"
```

## Testing

### Running Tests

```bash
# Run all database tests
pytest tests/test_database_pooling.py -v

# Run specific test categories
pytest tests/test_database_pooling.py::TestDatabaseConnectionPools -v
pytest tests/test_database_pooling.py::TestConcurrentOperations -v
```

### Load Testing

```bash
# Test connection pool under load
python -c "
import asyncio
from seedcore.api.database_example import async_pg_test
from fastapi.testclient import TestClient

async def load_test():
    tasks = [async_pg_test() for _ in range(100)]
    results = await asyncio.gather(*tasks)
    print(f'Completed {len(results)} requests')

asyncio.run(load_test())
"
```

## Migration Guide

### From Legacy Database Code

1. **Replace Direct Engine Creation**:
   ```python
   # Old
   engine = create_engine(DATABASE_URL)
   
   # New
   from seedcore.database import get_sync_pg_engine
   engine = get_sync_pg_engine()
   ```

2. **Update Session Management**:
   ```python
   # Old
   SessionLocal = sessionmaker(bind=engine)
   db = SessionLocal()
   
   # New
   from seedcore.database import get_sync_pg_session
   db = get_sync_pg_session()
   ```

3. **Add Health Checks**:
   ```python
   # Add to your FastAPI app
   from seedcore.database import check_pg_health
   
   @app.get("/health")
   async def health_check():
       is_healthy = await check_pg_health()
       return {"healthy": is_healthy}
   ```

## Security Considerations

1. **Connection String Security**:
   - Use environment variables for sensitive data
   - Avoid hardcoding credentials
   - Use connection pooling to limit exposure

2. **Network Security**:
   - Use internal Docker networks
   - Implement proper firewall rules
   - Consider SSL/TLS for database connections

3. **Access Control**:
   - Use dedicated database users
   - Implement proper permissions
   - Monitor connection patterns

## Future Enhancements

1. **Connection Pool Sharding**: For multi-tenant applications
2. **Dynamic Pool Sizing**: Automatic pool size adjustment
3. **Circuit Breaker Pattern**: Automatic failover handling
4. **Connection Encryption**: End-to-end encryption support
5. **Advanced Monitoring**: AI-powered anomaly detection

## Support

For issues and questions:
1. Check the troubleshooting section
2. Review Grafana dashboards for metrics
3. Run the test suite to validate setup
4. Consult the operation manual for deployment guidance 