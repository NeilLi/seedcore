# SeedCore Database Pooling Test Scripts

This directory contains comprehensive test scripts for validating SeedCore's database connection pooling and overall system functionality.

## Test Scripts

### 1. `test_database_pooling_simple.py`
**Lightweight Database Pooling Test Script**

- **Purpose**: Quick validation of database pooling and core features
- **Dependencies**: Only `requests` and `subprocess` (no docker Python library)
- **Features Tested**:
  - Database connection pooling (PostgreSQL via PgBouncer, MySQL, Neo4j)
  - Database connection health and staleness monitoring (`mw_staleness`)
  - API endpoints and health checks
  - Energy system monitoring
  - Ray cluster functionality
  - Monitoring services (Prometheus, Grafana)

**Usage:**
```bash
python3 scripts/test_database_pooling_simple.py
```

### 2. `test_database_pooling_comprehensive.py`
**Comprehensive Database Pooling Test Script**

- **Purpose**: Detailed validation with advanced Docker integration
- **Dependencies**: `docker` Python library, `requests`
- **Features Tested**:
  - All features from simple script
  - Advanced Docker container health monitoring
  - Detailed connection pool statistics
  - Enhanced error reporting and diagnostics

**Usage:**
```bash
python3 scripts/test_database_pooling_comprehensive.py
```

## Database Pooling Tests

Both scripts specifically test database connection pooling through:

### 1. **PgBouncer Connection Test**
- Tests PostgreSQL connection via PgBouncer on port 6432
- Validates connection pooling is working correctly
- Command: `docker exec -e PGPASSWORD=password seedcore-pgbouncer psql -h localhost -p 6432 -U postgres -d postgres -c "SELECT 1 as test;"`

### 2. **Database Staleness Monitoring**
- Tests the `mw_staleness` metric from `/health` endpoint
- Validates that connection pools are healthy (staleness = 0.0)
- Critical for ensuring database connections are fresh and responsive

### 3. **Direct Database Connections**
- Tests MySQL direct connection
- Tests Neo4j browser accessibility
- Validates all database services are operational

## Test Results

The scripts generate comprehensive test reports including:

- **Success Rate**: Overall system health percentage
- **Detailed Results**: Per-service and per-endpoint status
- **Error Details**: Specific error messages for failed tests
- **JSON Output**: Machine-readable results saved to files

### Example Output:
```
============================================================
SEEDCORE FEATURE TEST SUMMARY
============================================================
Total Tests: 26
Passed: 25
Failed: 1
Success Rate: 96.2%

DATABASE POOLING:
----------------------------------------
  pooling_health: ✅ PASS (staleness: 0.0)
```

## Key Database Pooling Metrics

### `mw_staleness`
- **What it measures**: Connection pool staleness indicator
- **Healthy value**: 0.0 (no staleness)
- **Test location**: `/health` endpoint
- **Critical for**: Ensuring database connections are fresh and responsive

### Connection Pool Health
- **PgBouncer**: Validates PostgreSQL connection pooling
- **MySQL**: Direct connection validation
- **Neo4j**: Graph database accessibility
- **Overall**: All databases accessible and pooling working

## Troubleshooting

### Common Issues

1. **PgBouncer Connection Failures**
   - Check if PgBouncer container is healthy
   - Verify PostgreSQL is running and accessible
   - Check authentication credentials

2. **High Staleness Values**
   - Indicates connection pool issues
   - May require restarting database services
   - Check for connection leaks

3. **Timeout Errors**
   - Increase timeout values in test scripts
   - Check system resource usage
   - Verify network connectivity

### Debug Commands

```bash
# Check PgBouncer status
docker exec seedcore-pgbouncer psql -h localhost -p 6432 -U postgres -d postgres -c "SHOW POOLS;"

# Check database health
curl http://localhost:8002/health | jq '.mw_staleness'

# Check all services
docker ps --filter "name=seedcore"
```

## Integration with CI/CD

These scripts can be integrated into CI/CD pipelines:

```yaml
# Example GitHub Actions step
- name: Test Database Pooling
  run: |
    python3 scripts/test_database_pooling_simple.py
    if [ $? -ne 0 ]; then
      echo "Database pooling tests failed"
      exit 1
    fi
```

## Performance Monitoring

The scripts provide baseline performance metrics for:
- Database connection response times
- API endpoint response times
- Service health status
- Connection pool efficiency

Use these metrics to establish performance baselines and detect regressions. 