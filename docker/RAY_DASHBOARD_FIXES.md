# Ray Dashboard Fixes

## Overview

This document details the fixes applied to resolve Ray dashboard issues and ensure compatibility with Python 3.10.

## Key Changes

### 1. Python Version Migration
- **From**: Python 3.11 with compatibility issues
- **To**: Python 3.10 with stable Ray support
- **Image**: `rayproject/ray:latest-py310`

### 2. Port Configuration
- **Dashboard**: Port 8265 (unchanged)
- **Agent gRPC**: Port 52365 (new)
- **Agent HTTP**: Port 52366 (new)
- **Resolution**: Eliminated port collision between dashboard services

### 3. Docker Configuration
- **Base Image**: `rayproject/ray:latest-py310`
- **Dependencies**: Added `asyncpg` and other required packages
- **Environment**: Proper PYTHONPATH configuration
- **Volumes**: Project root mounted to `/app`

### 4. Environment Variable Fixes
- **Issue**: PYTHONPATH warnings during Docker Compose builds
- **Root Cause**: Variable substitution `${PYTHONPATH}` when not set on host
- **Solution**: Use direct assignment `PYTHONPATH: /app:/app/src`
- **Result**: Clean builds without warnings

## Configuration Details

### Docker Compose Environment
```yaml
environment:
  PYTHONPATH: /app:/app/src  # Direct assignment, no variable substitution
  RAY_worker_stdout_file: /dev/stdout
  RAY_worker_stderr_file: /dev/stderr
  RAY_log_to_driver: 1
  RAY_BACKEND_LOG_LEVEL: info
```

### Ray Head Command
```bash
ray start --head \
  --dashboard-host 0.0.0.0 \
  --dashboard-port 8265 \
  --dashboard-agent-grpc-port 52365 \
  --dashboard-agent-listen-port 52366 \
  --include-dashboard true \
  --num-cpus 1 \
  --block
```

## Verification Steps

1. **Build Test**
   ```bash
   docker compose build --no-cache seedcore-api
   # Should complete without PYTHONPATH warnings
   ```

2. **Configuration Test**
   ```bash
   docker compose config --quiet
   # Should show no warnings
   ```

3. **Dashboard Access**
   ```bash
   # Start services
   docker compose up -d
   
   # Check dashboard
   curl http://localhost:8265/api/version
   ```

4. **Port Verification**
   ```bash
   # Check all ports are accessible
   netstat -tlnp | grep -E '8265|52365|52366'
   ```

## Troubleshooting

### Common Issues

1. **PYTHONPATH Warnings**
   - **Symptom**: `WARN[0000] The "PYTHONPATH" variable is not set. Defaulting to a blank string.`
   - **Solution**: Use direct environment variable assignment in docker-compose.yml
   - **Prevention**: Always use explicit values, avoid variable substitution

2. **Port Conflicts**
   - **Symptom**: Ray fails to start with port binding errors
   - **Solution**: Ensure ports 52365 and 52366 are not used by other services
   - **Verification**: Check port availability before starting

3. **Dashboard Not Accessible**
   - **Symptom**: Cannot access http://localhost:8265
   - **Solution**: Check Ray head service is running and healthy
   - **Debug**: Check container logs for startup errors

4. **Agent Communication Issues**
   - **Symptom**: Workers cannot connect to head node
   - **Solution**: Verify network configuration and port exposure
   - **Debug**: Check Ray cluster status and connectivity

## Best Practices

1. **Environment Variables**
   - Use explicit values in docker-compose.yml
   - Avoid variable substitution for critical paths
   - Document any required host environment variables

2. **Port Management**
   - Reserve specific ports for Ray services
   - Document port assignments clearly
   - Use consistent port mapping across environments

3. **Image Selection**
   - Use official Ray images when possible
   - Prefer stable versions over latest
   - Test compatibility before production deployment

4. **Monitoring**
   - Enable Ray logging for debugging
   - Monitor dashboard health endpoints
   - Track agent connectivity and performance

## Success Metrics

- ✅ No PYTHONPATH warnings during builds
- ✅ Ray dashboard accessible on port 8265
- ✅ Agent gRPC and HTTP ports working
- ✅ All Ray services starting cleanly
- ✅ No port conflicts or binding errors
- ✅ Stable Python 3.10 compatibility 