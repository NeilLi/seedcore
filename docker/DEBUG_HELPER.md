# SeedCore Debug Helper

This directory contains tools to help debug and manage the SeedCore Docker stack.

## Quick Commands

### `debug-helper.sh`

A hardened script that provides quick commands for common debug operations:

```bash
# Start Ray stack + databases only
./debug-helper.sh start-ray

# Start ALL services (full stack)
./debug-helper.sh start-full

# Restart all application containers (databases stay untouched)
./debug-helper.sh restart-app



# Restart seedcore-api only
./debug-helper.sh restart-api

# Follow ray-head logs in real-time
./debug-helper.sh logs-head

# Follow seedcore-api logs in real-time
./debug-helper.sh logs-api

# Quick health check and diagnostics for ray-head
./debug-helper.sh debug-head

# Show container status
./debug-helper.sh status

# Stop and remove all containers
./debug-helper.sh clean

# Run database seeding manually
./debug-helper.sh seed-db
```

## Health Check Improvements

The `ray-head` container now has a more forgiving health check that:

1. **Primary check**: Tries the `/health` endpoint first (fast and reliable)
2. **Fallback check**: Uses `ray health-check` if the health endpoint isn't ready yet
3. **Longer start period**: 30 seconds to give Ray Serve time to initialize
4. **Fewer retries**: 12 retries (2 minutes total) instead of 60

### Health Check Configuration

```yaml
healthcheck:
  test: ["CMD-SHELL",
         "curl -sf http://localhost:8000/health || ray health-check"]
  interval: 10s
  timeout: 5s
  retries: 12        # 2 min total (12×10 s)
  start_period: 30s  # give Ray Serve time to come up
```

## Command Categories

### Startup Commands
- **`start-ray`**: Starts only Ray stack + databases (for Ray development)
- **`start-full`**: Starts ALL services including API and observability (for full stack development)

### Restart Commands  
- **`restart-app`**: Restarts all application containers (databases stay untouched) + Ray workers
- **`restart-api`**: Restarts only the seedcore-api container

### Monitoring Commands
- **`logs-head`**: Follow ray-head logs in real-time
- **`logs-api`**: Follow seedcore-api logs in real-time
- **`debug-head`**: Quick health check and diagnostics for ray-head
- **`status`**: Show container status

### Utility Commands
- **`clean`**: Stop and remove all containers
- **`seed-db`**: Run database seeding manually

## Usage Examples

### When ray-head is stuck in a restart loop:

```bash
# 1. Check the current status
./debug-helper.sh debug-head

# 2. If needed, restart just the ray-head with new health check
docker compose up -d ray-head

# 3. Wait for it to become healthy, then restart the rest
./debug-helper.sh restart-app
```



### When you need to restart the entire application stack:

```bash
# This restarts everything except the three healthy databases
./debug-helper.sh restart-app
```

### When you need to monitor ray-head logs:

```bash
# Follow logs in real-time (Ctrl+C to exit)
./debug-helper.sh logs-head
```

## What Gets Restarted

### `restart-app` command restarts:
- **Ray workers** (stopped first)
- **All application services** (using Docker Compose dependency resolution)
  - `seedcore-ray-head`
  - `seedcore-api`
  - `seedcore-ray-metrics-proxy`
  - `seedcore-ray-dashboard-proxy`
  - `seedcore-prometheus`
  - `seedcore-grafana`
  - `seedcore-node-exporter`
  - `seedcore-db-seed`
- **Ray workers** (restarted last)

**Note**: Uses the same dependency resolution as `start-full` to ensure correct startup order.

**Note**: The three healthy databases (`postgres`, `mysql`, `neo4j`) are **not** restarted to avoid data loss.

## Naming Convention Clarification

### `start-full` vs `restart-app`
- **`start-full`**: Starts ALL services from scratch (used by `start-cluster.sh`)
- **`restart-app`**: Restarts only application containers (databases stay untouched)

This naming convention resolves the conflict between:
- `start-cluster.sh` which expects `start-full` to start everything
- Debug workflows which need `restart-app` to restart only non-DB containers

## Troubleshooting

### Ray Cluster Issues

**Problem**: After restarting ray-head, workers lose connection and the cluster becomes unhealthy.

**Solution**: Use `restart-app` to restart the entire application stack with proper dependency resolution:
```bash
./debug-helper.sh restart-app
```

### Restart Loop Issues

If you're still seeing restart loops:

1. Check if the `/health` endpoint is responding:
   ```bash
   curl http://localhost:8000/health
   ```

2. Check Ray's internal health:
   ```bash
   docker compose exec ray-head ray health-check
   ```

3. Check container logs:
   ```bash
   ./debug-helper.sh debug-head
   ```

4. If all else fails, try a clean restart:
   ```bash
   docker compose down
   docker compose up -d
   ``` 