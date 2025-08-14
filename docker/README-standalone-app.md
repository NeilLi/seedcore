# Standalone SeedCore App Pod

This document describes the new standalone `seedcore-app` pod that runs independently from the Ray head container.

## Overview

The standalone app pod:
- Connects to the Ray cluster via `ray://ray-head:10001`
- Runs the SeedCore telemetry API server on port 8002
- Includes health checks and proper resource limits
- Runs as a non-root user for security
- Provides the main API endpoints for SeedCore

## Architecture

```
┌─────────────────┐    ray://ray-head:10001    ┌─────────────────┐
│                 │ ──────────────────────────► │                 │
│ seedcore-app    │                             │   ray-head      │
│ (port 8002)     │                             │ (port 10001)    │
│                 │                             │                 │
└─────────────────┘                             └─────────────────┘
```

## Files

### 1. Dockerfile.app
- Base: `python:3.10-slim`
- Sets `PYTHONPATH=/app:/app/src`
- Runs as non-root user `app`
- Includes healthcheck for `/health` endpoint
- Exposes port 8002

### 2. app_entrypoint.py
- Waits for Ray head to be reachable
- Connects to Ray cluster
- Imports and starts telemetry server
- Runs uvicorn server with proper configuration

### 3. docker-compose.app.yml
- Full compose file with external network dependencies
- Requires main compose to be running

### 4. docker-compose.app.standalone.yml
- Standalone compose file without external dependencies
- Can be run independently

## Usage

### Docker Compose

```bash
# Start the standalone app pod (requires main compose running)
docker compose --profile app -f docker/docker-compose.app.yml up -d seedcore-app

# Start standalone (no external dependencies)
docker compose -f docker/docker-compose.app.standalone.yml up -d seedcore-app

# Test the setup
./docker/test-standalone-app.sh
```

### Direct Docker Build

```bash
# Build directly from the project root
docker build -f docker/Dockerfile.app -t seedcore-app:latest .

# Or with no cache
docker build --no-cache -f docker/Dockerfile.app -t seedcore-app:latest .
```

### Kubernetes

The pod can be deployed via the existing `api-deploy.yaml` with updated configuration:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: seedcore-app-dev
  namespace: seedcore-dev
spec:
  replicas: 1
  containers:
  - name: app
    image: seedcore-app:latest
    env:
    - name: RAY_ADDRESS
      value: ray://seedcore-dev-head-svc:10001
    - name: RAY_NAMESPACE
      value: seedcore-dev
    ports:
    - containerPort: 8002
    readinessProbe:
      httpGet: { path: /health, port: 8002 }
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RAY_ADDRESS` | `ray://seedcore-dev-head-svc:10001` | Ray cluster address |
| `RAY_NAMESPACE` | `seedcore-dev` | Ray namespace |
| `API_HOST` | `0.0.0.0` | API bind host |
| `API_PORT` | `8002` | API bind port |
| `PYTHONPATH` | `/app:/app/src` | Python path for imports |

## Health Checks

The pod includes multiple health check mechanisms:

1. **Docker healthcheck**: Tests `/health` endpoint every 30s
2. **Built-in health endpoint**: Available at `/health` for external monitoring
3. **Ray connection check**: Verifies connection to Ray cluster

## Resource Limits

- **CPU**: Default limits from base image
- **Memory**: 1g limit
- **Port**: 8002 (internal), 8003 (external in compose)

## API Endpoints

The app pod provides:
- **Health Check**: `http://localhost:8003/health`
- **Telemetry API**: `http://localhost:8003/`
- **Ray Integration**: Connects to Ray cluster for distributed operations

## Troubleshooting

### Common Issues

1. **Ray connection failed**: Ensure ray-head is running and accessible
2. **Health check failed**: Check if telemetry server started successfully
3. **Port conflicts**: App pod uses port 8003 externally to avoid conflicts

### Debug Commands

```bash
# Check Ray connection
docker exec seedcore-app python -c "import ray; print('Ray available')"

# Check telemetry server
docker exec seedcore-app python -c "from seedcore.telemetry.server import app; print('Server available')"

# View application logs
docker logs seedcore-app | grep "\[app\]"
```

## Migration from Integrated Setup

If you're migrating from the integrated Ray head + App setup:
1. **Update RAY_ADDRESS**: Point to `ray://ray-head:10001`
2. **Port changes**: App pod uses port 8003 externally
3. **Independent scaling**: App pod can be scaled independently
4. **Health monitoring**: Use `/health` endpoint for monitoring

## Security

- Runs as non-root user `app`
- Minimal resource allocation
- Health check timeouts prevent hanging
- Environment variable isolation
- Secure file permissions

## Testing

Use the provided test script to validate the setup:

```bash
./docker/test-standalone-app.sh
```

This script will:
1. Check Ray head availability
2. Build and start the app pod
3. Verify health endpoints
4. Test API functionality
5. Validate Ray connection


