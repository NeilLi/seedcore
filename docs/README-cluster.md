# SeedCore Cluster Management

## Quick Start

The new `start-cluster.sh` script provides a unified interface for managing your SeedCore Ray cluster.

### Basic Commands

```bash
# Start the full cluster with 3 workers (default)
./start-cluster.sh up

# Start with 5 workers
./start-cluster.sh up 5

# Restart application services (keeps databases running, preserves worker count)
./start-cluster.sh restart

# Stop everything
./start-cluster.sh down

# Follow logs
./start-cluster.sh logs head    # Ray head node logs
./start-cluster.sh logs api     # API service logs

# Check status
./start-cluster.sh status

# Run database seeding only
./start-cluster.sh seed-db
```

## What's Fixed

### 1. Restart Loop Prevention
- **Problem**: `restart-app` was causing Ray dashboard port conflicts
- **Root Cause**: Docker `stop` returns before ports are fully released
- **Solution**: Using `docker compose restart --no-deps` for safe, fast restarts

### 2. Health Check Grace Period
- **Problem**: Ray dashboard failed to start due to port race conditions
- **Solution**: Enhanced healthcheck with proper `start_period: 30s` grace period

### 3. Database Preservation
- **Problem**: Restart was killing databases by including `--profile core`
- **Solution**: Using `--no-deps` to restart only app services, leaving DBs untouched

### 4. Worker Management
- **Problem**: Workers weren't properly managed during restarts
- **Solution**: Automatically detect, stop, and restart the same number of workers
- **Improvement**: Workers now use separate project name (`seedcore-workers`) for better isolation

### 5. Path Handling
- **Problem**: Script assumed it was run from the docker directory
- **Solution**: Uses `SCRIPT_DIR` to determine absolute paths, works from any location

### 6. Unified Management
- **Before**: Two separate scripts (`start-cluster.sh` + `debug-helper.sh`)
- **After**: Single `start-cluster.sh` with all functionality merged

## Service Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Databases     │    │   Ray Cluster   │    │   Observability │
│                 │    │                 │    │                 │
│ • PostgreSQL    │    │ • Ray Head      │    │ • Prometheus    │
│ • MySQL         │    │ • Ray Workers   │    │ • Grafana       │
│ • Neo4j         │    │ • Ray Serve     │    │ • Node Exporter │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌─────────────────┐
                    │   Application   │
                    │                 │
                    │ • SeedCore API  │
                    │ • Metrics Proxy │
                    │ • Dashboard     │
                    └─────────────────┘
```

## Ports

- **8265**: Ray Dashboard
- **8000**: Ray Serve API
- **80**: SeedCore API
- **9090**: Prometheus
- **3000**: Grafana
- **5432**: PostgreSQL
- **3306**: MySQL
- **7474**: Neo4j

## Restart Behavior

The `restart` command now intelligently manages your cluster:

1. **Detects running workers** - Counts how many workers are currently running
2. **Stops workers cleanly** - Prevents port conflicts during app restart (uses separate project)
3. **Restarts app services** - Uses `--no-deps` to leave databases untouched
4. **Waits for head health** - Ensures Ray head is ready before proceeding
5. **Restores workers** - Brings back the same number of workers as before

This means your databases (`postgres`, `mysql`, `neo4j`) will never be restarted during a `restart` operation, preserving your data and avoiding unnecessary downtime.

## Project Structure

The script now uses separate Docker Compose projects for better isolation:

- **Main project**: `seedcore` - Contains databases, Ray head, API, and observability services
- **Workers project**: `seedcore-workers` - Contains only Ray worker containers

This separation ensures that worker management doesn't interfere with the main application stack.

## Troubleshooting

### If Ray Head Fails to Start
```bash
# Check logs
./start-cluster.sh logs head

# Check status
./start-cluster.sh status

# Restart just the application tier (preserves DBs and worker count)
./start-cluster.sh restart
```

### If Workers Won't Connect
```bash
# Ensure head is healthy first
./start-cluster.sh status

# Restart workers only
./ray-workers.sh restart 3
```

### Clean Slate
```bash
# Stop everything
./start-cluster.sh down

# Start fresh
./start-cluster.sh up
``` 