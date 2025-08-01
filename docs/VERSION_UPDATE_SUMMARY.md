# Ray and Python Version Update Summary

## Changes Made

This update implements the recommended stable configuration using **Ray 2.20.0** with **Python 3.10** to resolve dependency conflicts and improve stability.

### Files Updated

1. **`docker/Dockerfile.ray`**
   - Changed base image from `python:3.10-slim` to `python:3.9-slim`
   - Updated PYTHONPATH from `python3.10/site-packages` to `python3.9/site-packages`

2. **`docker/Dockerfile.ray.optimized`**
   - Changed base image from `rayproject/ray:2.9.3-py310` to `rayproject/ray:2.20.0-py310`
   - Changed production stage from `python:3.10-slim` to `python:3.9-slim`
   - Updated PYTHONPATH from `python3.10/site-packages` to `python3.9/site-packages`

3. **`docker/requirements-minimal.txt`**
   - Changed Ray version from `ray==2.9.3` to `ray==2.20.0`

4. **`requirements.txt`**
   - Changed Ray version from `ray>=2.10` to `ray==2.20.0`

### Why This Configuration is More Stable

- **Long-Term Support**: Ray 2.9.x versions are more mature and have had more time for bug fixes
- **Fewer Dependency Conflicts**: Python 3.9 is more forgiving with dependencies like `jinja2`, `setproctitle`, and `aiohttp-jinja2`
- **Community Adoption**: Many large-scale Ray deployments use versions around 2.9.x for proven stability
- **Dashboard Stability**: This combination should resolve the persistent dashboard startup errors

## Next Steps

1. **Rebuild the Docker images**:
   ```bash
   docker compose build ray-head
   ```

2. **Restart the cluster**:
   ```bash
   ./start-cluster.sh
   ```

3. **Verify the changes**:
   - Check that Ray dashboard starts without errors
   - Verify Python version in containers: `docker exec seedcore-ray-head python --version`
   - Verify Ray version: `docker exec seedcore-ray-head ray --version`

## Rollback Plan

If issues arise, you can revert to the previous configuration by:
1. Restoring the original version numbers in the files above
2. Rebuilding the images
3. Restarting the cluster

The previous configuration used:
- Python 3.10
- Ray 2.48.0 