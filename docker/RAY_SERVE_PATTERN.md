# Battle-Tested Ray Serve Pattern for SeedCore

This document describes the production-ready Ray Serve pattern implemented in SeedCore that solves common deployment pain points.

## Problem Solved

This pattern addresses two critical issues in Ray Serve deployments:

1. **Container restarts ⇒ "head not ready yet"** → Solved with `wait_for_head.sh` wrapper
2. **Serve app must always redeploy** when containers restart → Solved with persistent serve container

## Architecture Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Ray Head      │    │   Ray Workers   │    │   Serve App     │
│   (seedcore-    │    │   (seedcore-    │    │   (seedcore-    │
│    ray-head)    │◄───┤    ray-worker)  │    │    serve)       │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │                       │                       │
         ▼                       ▼                       ▼
   ┌─────────────────────────────────────────────────────────────┐
   │                    Docker Network                           │
   │                  (seedcore-network)                        │
   └─────────────────────────────────────────────────────────────┘
```

## Key Components

### 1. Pinned Ray Image (`Dockerfile.ray`)

```dockerfile
FROM rayproject/ray:2.22.0-py310  # ← pin an image; "latest" breaks silently
```

**Why**: Prevents silent breakages from image updates.

### 2. Wait-for-Head Script (`wait_for_head.sh`)

```bash
#!/usr/bin/env bash
# Usage: ["wait_for_head.sh", "seedcore-ray-head:6379", "ray", "start", "--address=seedcore-ray-head:6379", "--block"]

set -e
HEAD_ADDR=$1 ; shift
echo "[wait_for_head] Waiting for $HEAD_ADDR ..."
for i in {1..60}; do
  (echo > /dev/tcp/${HEAD_ADDR/:/\/}) >/dev/null 2>&1 && break
  sleep 2
done
echo "[wait_for_head] Head reachable, launching: $*"
exec "$@"
```

**Why**: Ensures workers wait for head to be fully ready before connecting.

### 3. Health-Checked Head Node

```yaml
seedcore-ray-head:
  healthcheck:
    test: ["CMD-SHELL", "curl -sf http://localhost:8265/api/version"]
    interval: 5s
    timeout: 3s
    retries: 30
```

**Why**: Prevents "head open but not ready" race conditions.

### 4. Persistent Serve Container (`serve_entrypoint.py`)

```python
while True:
    try:
        ray.init(address=RAY_ADDRESS, namespace="serve")
        serve.start(detached=True)
        app = create_serve_app()
        serve.run(app, name="seedcore-ml", route_prefix="/")
        
        print("🟢 Serve app is live. Blocking to keep container up ...")
        while True:
            time.sleep(3600)
    except (ConnectionError, RuntimeError) as e:
        print(f"🔄 Ray not ready ({e}); retrying in 3 s …")
        time.sleep(3)
```

**Why**: Automatically redeploys Serve apps after any cluster restart.

## Usage

### Quick Start

```bash
# Start the full cluster
cd docker
./start-cluster.sh

# Or manually:
docker compose up -d seedcore-ray-head seedcore-ray-worker seedcore-serve
```

### Monitoring

```bash
# Check cluster status
docker compose logs -f seedcore-ray-head

# View Serve dashboard
open http://localhost:8265/#/serve

# Test endpoints
curl http://localhost:8000/SalienceScorer
curl http://localhost:8000/AnomalyDetector
curl http://localhost:8000/ScalingPredictor
```

### Worker Management

```bash
# Start workers (uses ray-workers.sh script)
./ray-workers.sh start 3

# Stop workers
./ray-workers.sh stop

# Scale workers
./ray-workers.sh scale 5
```

## Key Improvements

| Problem | Fix |
|---------|-----|
| Containers restart faster than Ray's GCS | `wait_for_head.sh` with TCP polling & retry |
| Serve app not redeployed after restart | Make Serve the container's main process; infinite reconnect loop |
| "head open but not ready" | Compose health‑check + `depends_on: condition: service_healthy` |
| Unpredictable image changes | Pin Ray image version |
| Cluster namespace pollution | `ray.init(namespace="serve")` |

## Troubleshooting

### Common Issues

1. **Workers can't connect to head**
   ```bash
   # Check if head is healthy
   docker compose ps seedcore-ray-head
   
   # Check head logs
   docker compose logs seedcore-ray-head
   ```

2. **Serve app not deploying**
   ```bash
   # Check serve container logs
   docker compose logs seedcore-serve
   
   # Verify Ray connection
   docker exec seedcore-serve python -c "import ray; ray.init()"
   ```

3. **Port conflicts**
   ```bash
   # Check what's using the ports
   netstat -tulpn | grep :8265
   netstat -tulpn | grep :8000
   ```

### Recovery Procedures

```bash
# Full cluster restart
docker compose down
docker compose up -d seedcore-ray-head seedcore-ray-worker seedcore-serve

# Rebuild images (if needed)
docker compose build --no-cache seedcore-ray-head seedcore-ray-worker seedcore-serve
```

## Production Considerations

1. **Resource Limits**: Adjust `shm_size` and CPU/memory limits based on your workload
2. **Logging**: All containers stream logs to stdout/stderr for easy aggregation
3. **Monitoring**: Prometheus and Grafana are pre-configured for observability
4. **Security**: Use non-root users and network isolation in production

## Next Steps

- [ ] Add load balancing for multiple Serve replicas
- [ ] Implement graceful shutdown procedures
- [ ] Add metrics collection for Serve endpoints
- [ ] Set up automated health checks and alerting 