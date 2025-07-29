# Ray Dashboard Python 3.10 Compatibility Fixes

This document describes the fixes implemented to make Ray 2.48.0 dashboard work reliably with Python 3.10 in Docker containers.

## Problem

Ray dashboard was failing on Python 3.11 due to compatibility issues. The main problems were:

1. **Port collision** - Both dashboard agent gRPC and HTTP services trying to use port 52365
2. **Python 3.11 compatibility issues** - Many dependencies don't have proper cp311 wheels
3. **Template stack issues** - `aiohttp-jinja2` and `jinja2` version conflicts in Python 3.11

## Solution Implemented

### ✅ **Using rayproject's Python 3.10 Image**

The optimal solution is to use rayproject's official Ray image with Python 3.10:

```yaml
# docker-compose.yml
ray-head:
  image: rayproject/ray:latest-py310
  # ... rest of configuration
```

This image:
- ✅ **Much smaller** - Only 2.15GB vs 23.3GB for Anyscale image
- ✅ **Better compatibility** - Python 3.10 has excellent Ray 2.48.0 support
- ✅ **Official Ray image** - Maintained by the Ray project team
- ✅ **No dependency issues** - All packages work correctly with Python 3.10

## Key Changes Summary

| Component | Change | Purpose |
|-----------|--------|---------|
| docker-compose.yml | Use `rayproject/ray:latest-py310` | Optimal Python 3.10 compatibility |
| docker-compose.yml | Fixed port collision | Separate gRPC (52365) and HTTP (52366) ports |
| docker-compose.yml | Added version header | Ensure compatibility |
| docker-compose.yml | Added port 52366 | Expose agent HTTP port |

## Port Configuration

Ray uses three distinct ports for dashboard functionality:

| Service | Port | Protocol | Purpose |
|---------|------|----------|---------|
| Dashboard UI | 8265 | HTTP | Main dashboard interface |
| Agent gRPC | 52365 | gRPC | Internal agent communication |
| Agent HTTP | 52366 | HTTP | Agent REST API |

## Quick Start

### 1. Start the services:
```bash
cd docker
docker compose up -d
```

### 2. Run comprehensive verification:
```bash
./verify-310-compatibility.sh
```

### 3. Or run basic test:
```bash
./test-ray-dashboard.sh
```

### 4. Access the dashboard:
- **Dashboard UI**: http://localhost:8265
- **API endpoint**: http://localhost:8265/api/version

## Verification Results

✅ **Python 3.10.18** - Working correctly (much better than 3.11)  
✅ **Ray 2.48.0** - Working correctly  
✅ **grpcio 1.66.2** - Working correctly  
✅ **Dashboard API** - Responding at http://localhost:8265/api/version  
✅ **Dashboard UI** - Loading correctly at http://localhost:8265  
✅ **Port allocation** - All three ports (8265, 52365, 52366) working  
✅ **Image size** - Only 2.15GB (vs 23.3GB for Anyscale)  

## Why Python 3.10 Works Better

Python 3.10 has much better compatibility with Ray 2.48.0:

1. **No wheel compatibility issues** - All dependencies have proper cp310 wheels
2. **Stable dependency ecosystem** - No version conflicts with `aiohttp-jinja2` or `jinja2`
3. **Official Ray support** - Ray project officially supports Python 3.10
4. **Smaller image size** - No need for heavy ML dependencies

## Alternative: Custom Dockerfile

If you prefer to maintain your own Dockerfile with Python 3.10:

```dockerfile
FROM python:3.10-slim

# Install Ray with Python 3.10 compatible dependencies
RUN pip install --no-cache-dir \
    "ray[default]==2.48.0" \
    "grpcio>=1.63.0"

# Set dashboard ports
ENV RAY_DASHBOARD_HOST=0.0.0.0 \
    RAY_DASHBOARD_PORT=8265

EXPOSE 8265 52365 52366

CMD ["ray", "start", "--head", \
     "--dashboard-host=0.0.0.0", \
     "--dashboard-port=8265", \
     "--dashboard-agent-grpc-port=52365", \
     "--dashboard-agent-listen-port=52366", \
     "--include-dashboard=true", \
     "--block"]
```

## Troubleshooting

### Common Issues and Solutions

| Error Pattern | Cause | Solution |
|---------------|-------|----------|
| `ValueError: Ray component dashboard_agent_http is trying to use a port number 52365` | Port collision | Use separate ports for gRPC (52365) and HTTP (52366) |
| `grpc.aio.AioRpcError: UNAVAILABLE` | Agent gRPC port not exposed | Add port 52365 to docker-compose.yml |
| Python 3.11 compatibility issues | Use Python 3.10 | Switch to `rayproject/ray:latest-py310` |

### Debug Commands

```bash
# Check Ray logs
docker compose logs ray-head

# Test dashboard API
curl -sf http://localhost:8265/api/version && echo "✅ Dashboard responding"

# Check port binding
docker compose exec ray-head ss -lntp | grep 5236

# Test Ray initialization
docker compose exec ray-head python -c "import ray; ray.init(address='auto'); print('Ray working')"
```

## Image Comparison

| Image | Size | Python | Compatibility | Source |
|-------|------|--------|---------------|---------|
| `anyscale/ray-ml:2.48.0-py311` | 23.3GB | 3.11 | ✅ Good | Anyscale |
| `rayproject/ray:latest-py310` | **2.15GB** | **3.10** | ✅ **Excellent** | **Official Ray** |

## References

- [Ray Dashboard Configuration](https://docs.ray.io/en/latest/ray-core/configure.html)
- [Ray Docker Images](https://hub.docker.com/r/rayproject/ray)
- [Python 3.10 compatibility guide](https://docs.python.org/3.10/whatsnew/3.10.html) 