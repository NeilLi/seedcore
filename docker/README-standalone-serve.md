# Standalone SeedCore Serve Pod

This document describes the new standalone `seedcore-serve` pod that runs independently from the Ray head container.

## Overview

The standalone serve pod:
- Connects to the Ray cluster via `ray://ray-head:10001`
- Runs Ray Serve HTTP server on port 8000
- Deploys the SeedCore ML application
- Includes health checks and proper resource limits
- Runs as a non-root user for security

## Architecture

```
┌─────────────────┐    ray://ray-head:10001    ┌─────────────────┐
│                 │ ──────────────────────────► │                 │
│ seedcore-serve  │                             │   ray-head      │
│ (port 8000)     │                             │ (port 10001)    │
│                 │                             │                 │
└─────────────────┘                             └─────────────────┘
```

## Files

### 1. Dockerfile.serve
- Base: `rayproject/ray:2.33.0-py310`
- Sets `PYTHONPATH=/app:/app/src`
- Runs as non-root user `app`
- Includes healthcheck for `/health` endpoint
- Exposes port 8000

### 2. ray_serve_entrypoint.py
- Waits for Ray head to be reachable
- Connects to Ray cluster
- Starts Ray Serve HTTP server
- Deploys ML application via `build_app()`
- Keeps process alive for Kubernetes

### 3. serve_entrypoint.py (src/seedcore/)
- Provides `build_app()` function
- Returns ML service deployment from `create_serve_app()`

## Usage

### Docker Compose

```bash
# Start the standalone serve pod
docker compose --profile serve up -d seedcore-serve

# View logs
docker logs seedcore-serve

# Check health
curl http://localhost:8001/health
```

### Kubernetes

The pod is configured via `deploy/kustomize/base/serve-deploy.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: seedcore-serve-dev
  namespace: seedcore-dev
spec:
  replicas: 1
  containers:
  - name: serve
    image: seedcore-serve:latest
    env:
    - name: RAY_ADDRESS
      value: ray://seedcore-dev-head-svc:10001
    - name: RAY_NAMESPACE
      value: seedcore-dev
    ports:
    - containerPort: 8000
    readinessProbe:
      httpGet: { path: /health, port: 8000 }
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RAY_ADDRESS` | `ray://seedcore-dev-head-svc:10001` | Ray cluster address |
| `RAY_NAMESPACE` | `seedcore-dev` | Ray namespace |
| `SERVE_HTTP_HOST` | `0.0.0.0` | HTTP bind host |
| `SERVE_HTTP_PORT` | `8000` | HTTP bind port |
| `PYTHONPATH` | `/app:/app/src` | Python path for imports |

## Health Checks

The pod includes multiple health check mechanisms:

1. **Docker healthcheck**: Tests `/health` endpoint every 30s
2. **Kubernetes readiness probe**: Tests `/health` endpoint every 10s
3. **Built-in health endpoint**: Available at `/health` for external monitoring

## Resource Limits

- **CPU**: 100m request, 500m limit
- **Memory**: 256Mi request, 512Mi limit
- **Port**: 8000 (internal), 8001 (external in compose)

## Troubleshooting

### Common Issues

1. **Ray connection failed**: Ensure ray-head is running and accessible
2. **Health check failed**: Check if ML service deployed successfully
3. **Port conflicts**: Serve pod uses port 8001 externally to avoid conflicts

### Debug Commands

```bash
# Check Ray connection
docker exec seedcore-serve python -c "import ray; ray.init(address='ray://ray-head:10001')"

# Check Serve status
docker exec seedcore-serve python -c "from ray import serve; print(serve.status())"

# View application logs
docker logs seedcore-serve | grep "\[serve\]"
```

## Migration from Integrated Setup

If you're migrating from the integrated Ray head + Serve setup:

1. **Update RAY_ADDRESS**: Point to `ray://ray-head:10001`
2. **Separate ports**: Serve pod uses 8001 externally
3. **Independent scaling**: Serve pod can be scaled independently
4. **Health monitoring**: Use `/health` endpoint for monitoring

## Security

- Runs as non-root user `app`
- Minimal resource allocation
- Health check timeouts prevent hanging
- Environment variable isolation


