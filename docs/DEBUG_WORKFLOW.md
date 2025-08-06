# SeedCore Debug Workflow

This document describes the improved debug workflow for SeedCore, designed to make development and debugging faster and more efficient.

## 🎯 Problem Solved

Previously, restarting the `ray-head` container was painful because:
- It triggered the `db-seed` dependency, causing unnecessary database seeding
- Workers would disconnect after ~60 seconds when the head restarted
- The entire stack had to be brought down for simple code changes

## 🚀 New Debug Workflow

### Quick Start Commands

```bash
# Start only what you need for Ray debugging
./docker/debug-helper.sh start-ray

# Quick restart of ray-head (no dependencies)
./docker/debug-helper.sh restart-head

# Monitor ray-head logs
./docker/debug-helper.sh logs-head

# Clean slate
./docker/debug-helper.sh clean
```

### Docker Compose Profiles

The services are now organized into profiles for selective startup:

| Profile | Services | Use Case |
|---------|----------|----------|
| `core` | postgres, mysql, neo4j | Database services |
| `seed` | db-seed | Database seeding (one-time) |
| `ray` | ray-head | Ray cluster head node |
| `api` | seedcore-api | Main API service |
| `obs` | prometheus, grafana, nginx proxies | Observability stack |

### Common Debug Scenarios

#### 1. Ray Development Only
```bash
# Start databases + Ray head
./docker/debug-helper.sh start-ray

# Make code changes, then restart head
./docker/debug-helper.sh restart-head

# Monitor logs
./docker/debug-helper.sh logs-head
```

#### 2. Full Stack Development
```bash
# Start everything
./docker/debug-helper.sh start-full

# Quick API restart
./docker/debug-helper.sh restart-api
```

#### 3. Database Schema Changes
```bash
# Start databases
docker compose -p seedcore --profile core up -d

# Run seeding manually
./docker/debug-helper.sh seed-db
```

### Manual Docker Compose Commands

For advanced users, you can use Docker Compose directly:

```bash
# Start only Ray stack + databases
docker compose -p seedcore --profile core --profile ray up -d

# Restart ray-head without dependencies
docker compose -p seedcore restart --no-deps ray-head

# Force recreate ray-head (new image)
docker compose -p seedcore up -d --force-recreate --no-deps ray-head

# Start specific profiles
docker compose -p seedcore --profile core --profile ray --profile api up -d
```

## 🔧 Technical Changes

### 1. Removed db-seed Dependency
- `ray-head` now depends directly on healthy databases
- `db-seed` can be run manually when needed
- No more unnecessary seeding on every restart

### 2. Simplified Health Checks
- Removed custom polling loops from `start-ray-with-serve.sh`
- Rely on Docker Compose's built-in health checks
- Faster startup and cleaner logs

### 3. Profile Organization
- Services grouped by function
- Selective startup for different development scenarios
- Clear separation of concerns

## 📊 Health Check Strategy

### Docker Compose Health Checks
- **Ray Dashboard**: `curl -sf http://localhost:8265/api/version`
- **PostgreSQL**: `pg_isready -U postgres`
- **MySQL**: `mysqladmin ping -h localhost`
- **Neo4j**: `wget --spider http://localhost:7474/browser/`

### Manual Health Verification
```bash
# Check Ray dashboard
curl http://localhost:8265/api/version

# Check ML Serve
curl http://localhost:8000/ml/score/salience

# Check API
curl http://localhost:8002/api/health
```

## 🚨 Troubleshooting

### Ray Head Won't Start
```bash
# Check logs
./docker/debug-helper.sh logs-head

# Restart with fresh image
docker compose -p seedcore up -d --force-recreate --no-deps ray-head
```

### Workers Disconnect
- Workers will disconnect after ~60 seconds when head restarts
- This is normal Ray behavior
- Restart workers after head is stable: `./ray-workers.sh start 2`

### Database Issues
```bash
# Check database health
docker compose -p seedcore ps

# Re-seed if needed
./docker/debug-helper.sh seed-db
```

## 🔮 Future Improvements

### GCS Fault Tolerance (Optional)
For zero-downtime head restarts, consider enabling external Redis-backed GCS:

```yaml
# Add to ray-head environment
environment:
  RAY_external_storage_ns: gcs
  RAY_external_storage_address: redis://redis-gcs:6379/0
  RAY_gcs_rpc_server_reconnect_timeout_s: 120
```

### Split Compose Files
For even cleaner organization:
- `docker-compose.core.yml` - Databases
- `docker-compose.ray.yml` - Ray services
- `docker-compose.api.yml` - API services
- `docker-compose.obs.yml` - Observability

## 📝 Migration Notes

### From Old Workflow
1. **Old**: `docker compose up` (started everything)
   **New**: `./docker/debug-helper.sh start-ray` (selective startup)

2. **Old**: `docker compose restart ray-head` (triggered seeding)
   **New**: `./docker/debug-helper.sh restart-head` (no dependencies)

3. **Old**: Manual log monitoring
   **New**: `./docker/debug-helper.sh logs-head` (convenient monitoring)

### Backward Compatibility
- Full stack startup still works: `./docker/debug-helper.sh start-full`
- All existing functionality preserved
- New workflow is additive, not breaking

## 🎉 Benefits

- **Faster iteration**: Ray head restarts in ~10 seconds vs ~2 minutes
- **Selective startup**: Start only what you need
- **Cleaner logs**: No unnecessary seeding messages
- **Better isolation**: Debug Ray without affecting other services
- **Convenient commands**: Helper script for common operations 