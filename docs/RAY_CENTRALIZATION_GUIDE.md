# Ray Centralization Guide - Complete Reference

This comprehensive guide covers the centralized Ray architecture, configuration patterns, deployment strategies, and operational procedures for the SeedCore system.

## 📋 Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Configuration Patterns](#configuration-patterns)
4. [Deployment Strategies](#deployment-strategies)
5. [Bootstrap Integration](#bootstrap-integration)
6. [Ray Serve Configuration](#ray-serve-configuration)
7. [Environment Management](#environment-management)
8. [Troubleshooting](#troubleshooting)
9. [Migration Guide](#migration-guide)
10. [Best Practices](#best-practices)

## 🏗️ Overview

The SeedCore system uses a centralized Ray architecture that provides:

- **Unified Connection Management**: Single utility for all Ray connections
- **Environment-Aware Configuration**: Automatic detection of deployment scenarios
- **Ray Serve Integration**: Comprehensive service deployment and management
- **Bootstrap Orchestration**: Coordinated system initialization
- **Production-Ready Features**: Health monitoring, error handling, and scalability

## 🏛️ Architecture

### **Centralized Ray Connection Management**

The system uses `src/seedcore/utils/ray_utils.py` as the single source of truth for Ray connections:

```python
def ensure_ray_initialized(
    ray_address: Optional[str] = None, 
    ray_namespace: Optional[str] = "seedcore-dev"
) -> bool:
    """Centralized Ray connection utility with environment awareness."""
```

#### **Key Features**
- **Idempotent**: Safe to call multiple times
- **Environment-aware**: Automatically detects connection method
- **Smart fallback**: Uses environment variables when available
- **Performance optimized**: Module-level flag prevents repeated checks

### **Ray Serve Architecture**

The system deploys multiple services via Ray Serve:

#### **Service Deployments**
- **ML Service**: Machine learning capabilities (`/ml`)
- **Cognitive Service**: Advanced reasoning (`/cognitive`)
- **Coordinator Service**: Task coordination (`/pipeline`)
- **State Service**: State management (`/state`)
- **Energy Service**: Energy optimization (`/energy`)
- **Organism Service**: Agent management (`/organism`)

#### **Service Configuration**
```yaml
# From rayservice.yaml
applications:
  - name: ml_service
    import_path: entrypoints.ml_entrypoint:build_ml_service
    route_prefix: /ml
    deployments:
      - name: MLService
        num_replicas: 1
        ray_actor_options:
          num_cpus: 0.2
          num_gpus: 0
          resources: {"head_node": 0.001}
```

## ⚙️ Configuration Patterns

### **Pod Role Configuration**

The system uses role-based configuration for different pod types:

| Pod Role | Configmaps Used | RAY_ADDRESS | Purpose |
|----------|-----------------|-------------|---------|
| **Ray Head** | `seedcore-env` only | `auto` or unset | Runs Ray locally |
| **Ray Workers** | `seedcore-env` only | unset | KubeRay auto-wiring |
| **Client Pods** | `seedcore-env` + `seedcore-client-env` | `ray://seedcore-svc-head-svc:10001` | Connect via Service DNS |

### **Environment Variable Hierarchy**

#### **Shared Environment (`seedcore-env`)**
```bash
# Ray Configuration (shared K8s defaults - safe for all pods)
RAY_HOST=seedcore-svc-head-svc
RAY_PORT=10001
RAY_SERVE_URL=http://seedcore-svc-head-svc:8000
RAY_DASHBOARD_URL=http://seedcore-svc-head-svc:8265
RAY_NAMESPACE=seedcore-dev

# Database Connections
SEEDCORE_PG_DSN=postgresql://postgres:postgres@postgresql:5432/seedcore
REDIS_URL=redis://redis:6379
NEO4J_URI=bolt://neo4j:7687

# Application Configuration
LOG_LEVEL=INFO
LLM_PROVIDER=mlservice
```

#### **Client Environment (`seedcore-client-env`)**
```bash
# Ray Client Configuration
RAY_ADDRESS=ray://seedcore-svc-head-svc:10001
RAY_NAMESPACE=seedcore-dev
RAY_SERVE_ADDRESS=http://seedcore-svc-head-svc:8000
RAY_DASHBOARD_ADDRESS=http://seedcore-svc-head-svc:8265
```

### **Configuration Files**

#### **Base Kustomize (`deploy/kustomize/base/kustomization.yaml`)**
```yaml
generatorOptions:
  disableNameSuffixHash: true

configMapGenerator:
  - name: seedcore-env
    envs:
      - ../../../docker/.env

resources:
  - raycluster.yaml
  - api-deploy.yaml
  - api-svc.yaml
  - serve-deploy.yaml
  - serve-svc.yaml
```

#### **Dev Overlay (`deploy/kustomize/overlays/dev/kustomization.yaml`)**
```yaml
generatorOptions:
  disableNameSuffixHash: true

configMapGenerator:
  - name: seedcore-client-env
    literals:
      - RAY_ADDRESS=ray://seedcore-svc-head-svc:10001
      - RAY_NAMESPACE=seedcore-dev
      - RAY_SERVE_ADDRESS=http://seedcore-svc-head-svc:8000
      - RAY_DASHBOARD_ADDRESS=http://seedcore-svc-head-svc:8265

resources:
  - ../../base
```

## 🚀 Deployment Strategies

### **Kubernetes Deployment**

#### **RayService Configuration**
The system uses RayService for comprehensive Ray cluster and Serve deployment:

```yaml
apiVersion: ray.io/v1
kind: RayService
metadata:
  name: seedcore-svc
  namespace: seedcore-dev
spec:
  serveConfigV2: |
    http_options:
      host: 0.0.0.0
      port: 8000
      location: HeadOnly
    applications:
      # Service definitions...
  rayClusterConfig:
    rayVersion: "2.33.0"
    headGroupSpec:
      serviceType: ClusterIP
      rayStartParams:
        dashboard-host: "0.0.0.0"
        dashboard-port: "8265"
        ray-client-server-port: "10001"
        num-cpus: "2"
```

#### **Deployment Commands**
```bash
# Apply base configuration
kubectl apply -k deploy/kustomize/base -n seedcore-dev

# Apply dev overlay
kubectl apply -k deploy/kustomize/overlays/dev -n seedcore-dev

# Or use convenience script
./deploy/apply-new-ray-config.sh seedcore-dev
```

### **Docker Compose Deployment**

For local development, the system supports Docker Compose with similar configuration patterns:

```yaml
# docker-compose.yml
services:
  ray-head:
    environment:
      - RAY_NAMESPACE=seedcore-dev
      - SEEDCORE_NS=seedcore-dev
    ports:
      - "10001:10001"  # Ray client
      - "8265:8265"    # Dashboard
      - "8000:8000"    # Serve

  seedcore-api:
    environment:
      - RAY_ADDRESS=ray://ray-head:10001
      - RAY_NAMESPACE=seedcore-dev
    depends_on:
      - ray-head
```

## 🔧 Bootstrap Integration

### **Bootstrap Architecture**

The system uses a coordinated bootstrap process:

#### **Bootstrap Entry Point (`bootstraps/bootstrap_entry.py`)**
```python
def main() -> int:
    mode = os.getenv("BOOTSTRAP_MODE", "all").lower().strip()
    
    if mode in ("all", "organism"):
        log.info("🚀 Step 1/2: Initializing organism...")
        ok = bootstrap_organism()
        
    if mode in ("all", "dispatchers"):
        log.info("🚀 Step 2/2: Initializing dispatchers...")
        ok = bootstrap_dispatchers()
```

#### **Organism Bootstrap (`bootstraps/bootstrap_organism.py`)**
- **Ray Serve Integration**: Uses Serve deployment handles
- **Singleton Actor Bootstrap**: Creates required system actors
- **Health Monitoring**: Waits for organism initialization
- **Fallback Support**: HTTP fallback if Ray fails

#### **Dispatcher Bootstrap (`bootstraps/bootstrap_dispatchers.py`)**
- **Queue Dispatchers**: Task processing workers
- **Graph Dispatchers**: Graph-based task routing
- **Reaper**: Stale task cleanup
- **Health Verification**: Ensures all components are ready

### **Bootstrap Process Flow**

1. **Ray Initialization**: Ensure Ray cluster is available
2. **Singleton Actor Creation**: Bootstrap required system actors
3. **Organism Initialization**: Initialize agent management system
4. **Dispatcher Creation**: Start task processing workers
5. **Health Verification**: Confirm all components are operational

## 🌐 Ray Serve Configuration

### **Service Definitions**

#### **ML Service**
```yaml
- name: ml_service
  import_path: entrypoints.ml_entrypoint:build_ml_service
  route_prefix: /ml
  deployments:
    - name: MLService
      num_replicas: 1
      ray_actor_options:
        num_cpus: 0.2
        num_gpus: 0
        resources: {"head_node": 0.001}
```

#### **Cognitive Service**
```yaml
- name: cognitive
  import_path: entrypoints.cognitive_entrypoint:build_cognitive_app
  route_prefix: /cognitive
  deployments:
    - name: CognitiveService
      num_replicas: 2
      ray_actor_options:
        num_cpus: 0.2
        num_gpus: 0
        memory: 2147483648  # 2GB
        resources: {"head_node": 0.001}
```

### **Resource Management**

#### **Head Node Resources**
```yaml
resources:
  requests:
    cpu: "500m"
    memory: "4Gi"
  limits:
    cpu: "2"
    memory: "8Gi"
```

#### **Worker Node Resources**
```yaml
resources:
  requests:
    cpu: "500m"
    memory: "4Gi"
  limits:
    cpu: "2"
    memory: "8Gi"
```

### **Health Monitoring**

#### **Startup Probes**
```yaml
startupProbe:
  exec:
    command: ["bash", "-lc", "wget --tries=1 -T 2 -q -O- http://127.0.0.1:52365/api/local_raylet_healthz | grep -q success"]
  periodSeconds: 5
  timeoutSeconds: 3
  failureThreshold: 72
```

#### **Readiness Probes**
```yaml
readinessProbe:
  exec:
    command: ["bash", "-lc", "wget --tries=1 -T 2 -q -O- http://127.0.0.1:52365/api/local_raylet_healthz | grep -q success"]
  periodSeconds: 5
  timeoutSeconds: 2
  failureThreshold: 3
```

## 🌍 Environment Management

### **Environment Variables**

#### **Core Ray Configuration**
```bash
# Ray Connection
RAY_ADDRESS=ray://seedcore-svc-head-svc:10001
RAY_NAMESPACE=seedcore-dev
SEEDCORE_NS=seedcore-dev

# Ray Services
RAY_SERVE_ADDRESS=http://seedcore-svc-head-svc:8000
RAY_DASHBOARD_ADDRESS=http://seedcore-svc-head-svc:8265

# Ray Components
RAY_HOST=seedcore-svc-head-svc
RAY_PORT=10001
```

#### **Service-Specific Configuration**
```bash
# ML Service
LLM_PROVIDER=mlservice
XGB_STORAGE_PATH=/app/data/models

# Cognitive Service
COGNITIVE_TIMEOUT_S=8.0
COGNITIVE_MAX_INFLIGHT=64
OCPS_DRIFT_THRESHOLD=0.5

# System Configuration
LOG_LEVEL=INFO
DSP_LOG_TO_STDOUT=true
```

### **Namespace Management**

The system uses consistent namespace handling:

```python
# From ray_utils.py
def get_ray_namespace() -> str:
    """Get Ray namespace with proper fallback hierarchy."""
    return (
        os.getenv("SEEDCORE_NS") or
        os.getenv("RAY_NAMESPACE") or
        "seedcore-dev"
    )
```

## 🔍 Troubleshooting

### **Common Issues**

#### **Connection Timeouts**
```bash
# Check Ray cluster status
kubectl -n seedcore-dev get rayservice

# Check Ray head pod
kubectl -n seedcore-dev get pods -l ray.io/node-type=head

# Check Ray dashboard
kubectl -n seedcore-dev port-forward svc/seedcore-svc-head-svc 8265:8265
```

#### **Service Discovery Issues**
```bash
# Check service endpoints
kubectl -n seedcore-dev get endpoints

# Check Ray services
kubectl -n seedcore-dev get services | grep ray

# Test Ray connection
kubectl -n seedcore-dev exec -it <pod-name> -- python -c "
import ray
ray.init()
print('✅ Ray connection successful')
"
```

#### **Configuration Issues**
```bash
# Check configmaps
kubectl -n seedcore-dev get configmaps

# Check environment variables
kubectl -n seedcore-dev exec -it <pod-name> -- env | grep RAY_

# Verify Kustomize output
kubectl kustomize deploy/kustomize/overlays/dev
```

### **Debug Commands**

#### **Ray Cluster Information**
```python
from seedcore.utils.ray_utils import get_ray_cluster_info
print(get_ray_cluster_info())
```

#### **Service Health Checks**
```bash
# Check organism health
curl http://seedcore-svc-head-svc:8000/organism/health

# Check ML service health
curl http://seedcore-svc-head-svc:8000/ml/health

# Check cognitive service health
curl http://seedcore-svc-head-svc:8000/cognitive/health
```

## 🔄 Migration Guide

### **From Scattered Ray.init() Calls**

#### **Before (Scattered Approach)**
```python
# Multiple files with inconsistent logic
if not ray.is_initialized():
    try:
        ray.init(address=ray_address, ignore_reinit_error=True, namespace=namespace)
    except Exception:
        ray.init(ignore_reinit_error=True, namespace=namespace)
```

#### **After (Centralized Approach)**
```python
# Single, consistent call across all files
from seedcore.utils.ray_utils import ensure_ray_initialized

if not ensure_ray_initialized(ray_address=ray_address, ray_namespace=namespace):
    raise ConnectionError("Failed to connect to Ray cluster")
```

### **Migration Steps**

1. **Update Code**: Replace scattered `ray.init()` calls with `ensure_ray_initialized()`
2. **Update Configuration**: Apply new Kustomize configuration
3. **Test Deployment**: Verify functionality in different environments
4. **Monitor**: Check Ray connection success/failure rates

### **Backward Compatibility**

The centralized approach maintains backward compatibility:
- Existing environment variables still work
- Gradual migration is supported
- No breaking changes to existing functionality

## 📚 Best Practices

### **Connection Management**

1. **Use Centralized Utility**: Always use `ensure_ray_initialized()`
2. **Environment Awareness**: Let the utility handle environment detection
3. **Error Handling**: Implement proper error handling and fallbacks
4. **Resource Management**: Use appropriate resource limits and requests

### **Configuration Management**

1. **Role-Based Configuration**: Use appropriate configmaps for pod roles
2. **Environment Variables**: Use consistent naming and hierarchy
3. **Kustomize Patterns**: Follow established Kustomize patterns
4. **Documentation**: Keep configuration documentation up to date

### **Deployment Practices**

1. **Health Checks**: Implement comprehensive health monitoring
2. **Resource Limits**: Set appropriate CPU and memory limits
3. **Scaling**: Use Ray Serve autoscaling features
4. **Monitoring**: Implement proper observability and logging

### **Development Workflow**

1. **Local Development**: Use Docker Compose for local testing
2. **Environment Testing**: Test in multiple environments
3. **Configuration Validation**: Validate configuration before deployment
4. **Documentation**: Keep documentation synchronized with code changes

## 🎯 Summary

The Ray Centralization Guide provides a comprehensive framework for:

✅ **Unified Ray Management**: Centralized connection and configuration management  
✅ **Production-Ready Deployment**: Kubernetes and Docker Compose support  
✅ **Bootstrap Integration**: Coordinated system initialization  
✅ **Service Architecture**: Ray Serve-based microservices  
✅ **Environment Management**: Role-based configuration patterns  
✅ **Troubleshooting**: Comprehensive debugging and monitoring tools  
✅ **Best Practices**: Proven patterns for development and operations  

This architecture represents a significant evolution from scattered Ray initialization to a sophisticated, production-ready system that provides reliability, scalability, and maintainability for the SeedCore platform.