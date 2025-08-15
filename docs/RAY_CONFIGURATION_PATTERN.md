# Ray Configuration Pattern

This document describes the new Ray configuration pattern that makes the system more robust and maintainable by centralizing Ray connection settings and automatically configuring pods based on their role.

## Overview

The new pattern separates Ray configuration into two configmaps:
- **`seedcore-env`**: Shared environment variables (databases, Redis, Neo4j, etc.)
- **`seedcore-client-env`**: Client-only Ray connection variables

This eliminates the brittleness of having `RAY_ADDRESS` scattered across multiple files and ensures consistent configuration across all pods.

## Pod Role Configuration

### Ray Head Pod
- **Environment**: `seedcore-env` only
- **RAY_ADDRESS**: `auto` (or unset)
- **Why**: Head runs Ray locally; client URL is wrong here

### Ray Worker Pods
- **Environment**: `seedcore-env` only  
- **RAY_ADDRESS**: Unset
- **Why**: KubeRay wires workers to head automatically

### Client Pods (API, Jobs, etc.)
- **Environment**: `seedcore-env` + `seedcore-client-env`
- **RAY_ADDRESS**: `ray://seedcore-head-svc:10001`
- **RAY_NAMESPACE**: `seedcore-dev`
- **Why**: Clients need to connect via the Service DNS

## Configuration Files

### 1. Base Kustomize (`deploy/kustomize/base/kustomization.yaml`)

```yaml
generatorOptions:
  disableNameSuffixHash: true

configMapGenerator:
  - name: seedcore-env
    envs:
      - ../../../docker/.env        # shared app env (NO RAY_ADDRESS here)

resources:
  - raycluster.yaml
  - api-deploy.yaml
  - api-svc.yaml
  - serve-deploy.yaml
  - serve-svc.yaml
```

### 2. Dev Overlay (`deploy/kustomize/overlays/dev/kustomization.yaml`)

```yaml
generatorOptions:
  disableNameSuffixHash: true

configMapGenerator:
  - name: seedcore-client-env
    literals:
      - RAY_ADDRESS=ray://seedcore-head-svc:10001
      - RAY_NAMESPACE=seedcore-dev
      - RAY_SERVE_ADDRESS=http://seedcore-head-svc:8000
      - RAY_DASHBOARD_ADDRESS=http://seedcore-head-svc:8265

resources:
  - ../../base
```

### 3. Shared Environment (`docker/.env`)

```bash
# Ray (shared K8s defaults - safe for all pods)
# NOTE: Do NOT set RAY_ADDRESS here - it's configured per-pod role
RAY_HOST=seedcore-head-svc
RAY_PORT=10001
RAY_SERVE_URL=http://seedcore-head-svc:8000
RAY_DASHBOARD_URL=http://seedcore-head-svc:8265
RAY_NAMESPACE=seedcore-dev
```

## Deployment

### Apply Configuration

```bash
# Base (creates seedcore-env, RayCluster uses it)
kubectl apply -k deploy/kustomize/base -n seedcore-dev

# Dev overlay (adds seedcore-client-env; API uses both)
kubectl apply -k deploy/kustomize/overlays/dev -n seedcore-dev

# Or use the convenience script
./deploy/apply-new-ray-config.sh seedcore-dev
```

### Verify Configuration

```bash
# Check configmaps
kubectl -n seedcore-dev get configmaps

# Check head pod environment
HEAD=$(kubectl -n seedcore-dev get pod -l ray.io/node-type=head -o jsonpath='{.items[0].metadata.name}')
kubectl -n seedcore-dev exec "$HEAD" -c ray-head -- env | grep RAY_

# Check API pod environment  
API=$(kubectl -n seedcore-dev get pod -l app=seedcore-api -o jsonpath='{.items[0].metadata.name}')
kubectl -n seedcore-dev exec "$API" -- env | grep RAY_
```

## Code Integration

### Using the New Pattern

The `src/seedcore/utils/ray_config.py` module provides utilities for the new pattern:

```python
from seedcore.utils.ray_config import init_ray_with_smart_defaults

# Automatically handles different pod roles
init_ray_with_smart_defaults()
```

### Manual Ray Initialization

```python
import os
import ray

ray_address = os.getenv("RAY_ADDRESS")
if not ray_address or ray_address == "auto":
    # head/worker or explicit 'auto'
    ray.init(address=ray_address or "auto", namespace=os.getenv("RAY_NAMESPACE"))
else:
    ray.init(address=ray_address, namespace=os.getenv("RAY_NAMESPACE"))
```

### Deriving RAY_ADDRESS from Components

```python
import os

addr = os.getenv("RAY_ADDRESS")
if not addr:
    host = os.getenv("RAY_HOST", "seedcore-head-svc")
    port = os.getenv("RAY_PORT", "10001")
    addr = f"ray://{host}:{port}"

ray.init(address=addr, namespace=os.getenv("RAY_NAMESPACE"))
```

## Migration Guide

### From Old Pattern

1. **Remove hardcoded RAY_ADDRESS** from:
   - `docker/.env`
   - Individual deployment files
   - Docker Compose files

2. **Update pod configurations**:
   - Head/workers: Use `seedcore-env` only
   - Clients: Use `seedcore-env` + `seedcore-client-env`

3. **Update code** to use the new utilities or manual pattern

### Testing Migration

```bash
# 1. Apply new configuration
./deploy/apply-new-ray-config.sh seedcore-dev

# 2. Verify environment variables
kubectl -n seedcore-dev exec -it <head-pod> -c ray-head -- env | grep RAY_
kubectl -n seedcore-dev exec -it <api-pod> -- env | grep RAY_

# 3. Test Ray connectivity
kubectl -n seedcore-dev exec -it <api-pod> -- python -c "
import ray
ray.init()
print('✅ Ray connection successful')
"
```

## Benefits

1. **Single Source of Truth**: Host/port defined once in shared config
2. **Role-Based Configuration**: Pods automatically get the right settings
3. **Easier Maintenance**: Update Ray connection in one place
4. **Consistent Behavior**: All pods follow the same pattern
5. **Development Friendly**: Easy to override for local development

## Troubleshooting

### Common Issues

1. **RAY_ADDRESS not set in client pods**
   - Check that `seedcore-client-env` configmap exists
   - Verify the overlay is applied correctly

2. **Head pod has wrong RAY_ADDRESS**
   - Ensure head pod only uses `seedcore-env`
   - Check that `RAY_ADDRESS` is set to "auto" or unset

3. **Configmap not found**
   - Verify the base and overlay are applied
   - Check configmap names match deployment references

### Debug Commands

```bash
# Check configmap contents
kubectl -n seedcore-dev describe configmap seedcore-env
kubectl -n seedcore-dev describe configmap seedcore-client-env

# Check pod environment
kubectl -n seedcore-dev exec -it <pod-name> -- env | sort

# Check Kustomize output
kubectl kustomize deploy/kustomize/overlays/dev
```

## Future Enhancements

1. **Environment-Specific Overlays**: Different Ray configurations for dev/staging/prod
2. **Dynamic Configuration**: Use Kustomize transformers for environment-specific values
3. **Health Checks**: Validate Ray configuration on pod startup
4. **Metrics**: Track Ray connection success/failure rates
