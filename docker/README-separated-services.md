# SeedCore Separated Services Architecture

This document explains the new separated services architecture where the serve modules are no longer tightly coupled with the main `seedcore-api` service.

## Overview

Previously, the serve modules (`cognitive_serve.py`, `simple_app.py`, `resource_manager.py`) were imported directly into the main telemetry server, creating tight coupling. Now these services run independently as separate containers.

## Service Architecture

### 1. Main API Service (`seedcore-api`)
- **Purpose**: Core telemetry and API endpoints
- **Port**: 8002
- **Dockerfile**: `Dockerfile.api`
- **Entrypoint**: `api_entrypoint_simple.sh`
- **Dependencies**: None on serve modules

### 2. Cognitive Serve Service (`seedcore-cognitive-serve`)
- **Purpose**: Cognitive reasoning and AI services
- **Port**: 8002 (mapped from internal 8000)
- **Dockerfile**: `Dockerfile.cognitive-serve`
- **Entrypoint**: `cognitive_serve_entrypoint.py`
- **Dependencies**: Ray cluster, databases

### 3. General Serve Service (`seedcore-serve`)
- **Purpose**: ML and general Ray Serve deployments
- **Port**: 8001
- **Dockerfile**: `Dockerfile.serve`
- **Entrypoint**: `serve_entrypoint.py`
- **Dependencies**: Ray cluster, databases

## Running the Services

### Option 1: Run All Services Together
```bash
# Start core infrastructure
docker-compose --profile core up -d

# Start Ray cluster
docker-compose --profile ray up -d

# Start all services
docker-compose --profile api --profile serve --profile cognitive-serve up -d
```

### Option 2: Run Services Individually
```bash
# Start only the main API (without serve modules)
docker-compose --profile core --profile ray --profile api up -d

# Start only cognitive services
docker-compose --profile core --profile ray --profile cognitive-serve up -d

# Start only general serve services
docker-compose --profile core --profile ray --profile serve up -d
```

### Option 3: Development Mode
```bash
# Start with specific profiles for development
docker-compose --profile core --profile ray --profile api --profile cognitive-serve up -d
```

## Service Communication

### Main API → Cognitive Service
The main API now communicates with the cognitive service via HTTP calls instead of direct imports:

```python
# Before (tightly coupled)
from ..serve.cognitive_serve import CognitiveCoreClient
client = CognitiveCoreClient()
result = await client.reason_about_failure(...)

# After (loosely coupled)
import httpx
client = httpx.AsyncClient(base_url="http://seedcore-cognitive-serve:8000")
response = await client.post("/cognitive/reason-about-failure", json={...})
result = response.json()
```

### Fallback Behavior
If the cognitive service is unavailable, the main API falls back to direct cognitive core usage:

```python
try:
    # Try HTTP client first
    response = await client.post("/cognitive/reason-about-failure", json={...})
    result = response.json()
    return result
except Exception:
    # Fallback to direct cognitive core
    cognitive_core = get_cognitive_core()
    if not cognitive_core:
        cognitive_core = initialize_cognitive_core()
    # ... direct usage
```

## Benefits of Separation

1. **Independent Scaling**: Each service can be scaled independently
2. **Fault Isolation**: Failures in serve modules don't affect the main API
3. **Resource Management**: Better resource allocation and monitoring
4. **Development Flexibility**: Developers can work on services independently
5. **Deployment Flexibility**: Services can be deployed to different environments

## Configuration

### Environment Variables
Each service has its own configuration:

```bash
# Main API
SEEDCORE_API_PORT=8002
DSP_LOG_DIR=/tmp/seedcore-logs

# Cognitive Service
RAY_ADDRESS=ray://ray-head:10001
RAY_NAMESPACE=seedcore
SERVE_HTTP_PORT=8000

# General Serve
RAY_ADDRESS=ray://ray-head:10001
RAY_NAMESPACE=seedcore
SERVE_HTTP_PORT=8000
```

### Network Configuration
All services use the `seedcore-network` for internal communication:

```yaml
networks:
  - seedcore-network
```

## Monitoring and Health Checks

Each service has its own health check endpoint:

- **Main API**: `http://localhost:8002/health`
- **Cognitive Service**: `http://localhost:8002/health` (mapped from 8000)
- **General Serve**: `http://localhost:8001/health` (mapped from 8000)

## Troubleshooting

### Service Not Starting
1. Check if Ray cluster is healthy: `docker-compose --profile ray ps`
2. Verify database connections are working
3. Check service logs: `docker logs seedcore-cognitive-serve`

### Communication Issues
1. Verify network connectivity between services
2. Check if cognitive service is responding: `curl http://localhost:8002/health`
3. Verify Ray cluster is accessible from cognitive service

### Performance Issues
1. Monitor resource usage: `docker stats`
2. Check Ray cluster resources: `ray status`
3. Verify service replicas are running: `ray list deployments`

## Migration from Old Architecture

If you're migrating from the old tightly-coupled architecture:

1. **Stop old services**: `docker-compose down`
2. **Build new images**: `docker-compose build`
3. **Start new services**: `docker-compose --profile core --profile ray --profile api --profile cognitive-serve up -d`
4. **Verify separation**: Check that main API doesn't import serve modules
5. **Test communication**: Verify HTTP calls between services work

## Future Enhancements

- **Service Discovery**: Implement proper service discovery for dynamic environments
- **Load Balancing**: Add load balancing for multiple cognitive service instances
- **Circuit Breakers**: Implement circuit breakers for better fault tolerance
- **Metrics**: Add comprehensive metrics collection across all services
