# Ray Cluster Operations Reference (Kubernetes)

This document summarizes how the SeedCore Ray cluster is configured and operated using Kubernetes with KubeRay operator, including data store integration.

## Architecture Overview

- **Head node**: `seedcore-head-*` pod running Ray head with KubeRay operator
- **Workers**: `seedcore-small-worker-*` pods managed by KubeRay operator
- **Data Stores**: PostgreSQL, MySQL, Redis, Neo4j running in the same namespace
- **Infrastructure**: Kubernetes cluster with KubeRay operator for Ray management

## Ray Ports in Kubernetes Setup

| Port | Role | Who Connects | Notes |
|------|------|--------------|-------|
| 6380 | GCS (Global Control Store) | Workers, internal cluster RPC | **Workers join cluster using `--address=<head>:6380`** |
| 10001 | Ray Client Server | Developer scripts, applications | Client-mode for apps and tools; not needed by workers |
| 8265 | Ray Dashboard | Browser | Web UI for monitoring cluster status |
| 8081 | Metrics | Prometheus, monitoring | Ray metrics export port |

## Data Store Ports

| Service | Port | Purpose | Connection String |
|---------|------|---------|-------------------|
| PostgreSQL | 5432 | Vector database with pgvector | `postgresql://postgres:password@postgresql:5432/postgres` |
| MySQL | 3306 | Relational database | `mysql+mysqlconnector://seedcore:password@mysql:3306/seedcore` |
| Redis | 6379 | In-memory cache | `redis://redis-master:6379` |
| Neo4j | 7687 | Graph database | `bolt://neo4j:7687` |

## Where Things Are Defined

- **KubeRay Operator**: `kuberay/kuberay-operator` Helm chart
- **Ray Cluster**: `deploy/kustomize/base/raycluster.yaml`
- **Data Stores**: `deploy/helm/` directory with custom charts
- **Deployment Scripts**: `deploy/setup-kind-ray.sh` and `deploy/deploy-datastores.sh`

## Quick Start Commands

### 1. Setup Complete Environment
```bash
# From deploy directory
./setup-kind-ray.sh
```

This script will:
- Create Kind cluster
- Install KubeRay operator
- Deploy Ray cluster
- Deploy all data stores (PostgreSQL, MySQL, Redis, Neo4j)
- Test Ray connectivity

### 2. Individual Service Management
```bash
# Deploy only data stores
./deploy-datastores.sh

# Check Ray cluster status
kubectl get raycluster -n seedcore-dev

# Check all pods
kubectl get pods -n seedcore-dev

# Check services
kubectl get svc -n seedcore-dev
```

### 3. Ray Cluster Operations
```bash
# Scale workers
kubectl scale raycluster seedcore --replicas=5 -n seedcore-dev

# Check Ray cluster health
kubectl describe raycluster seedcore -n seedcore-dev

# Access Ray dashboard
kubectl port-forward -n seedcore-dev svc/seedcore-head-svc 8265:8265
```

## Worker Configurations

### Kubernetes Workers (`seedcore-small-worker-*`)

- **Network**: Kubernetes pod network
- **Join**: Automatically managed by KubeRay operator
- **Discovery**: Via headless service `seedcore-head-svc`
- **Scaling**: Managed through `kubectl scale raycluster`

### Worker Connection Flow
```
Worker Pod → seedcore-head-svc.seedcore-dev.svc.cluster.local:6380 (GCS)
           ↓ (DNS Resolution)
           → 10.244.0.12:6380 (Head Pod GCS Port)
```

## Client vs Cluster Ports (Quick Guide)

- **Use `6380`** for cluster join (workers, system components)
- **Use `ray://<host>:10001`** for client-mode (`RAY_ADDRESS`) in developer tools and services

## Data Store Integration

### PostgreSQL with pgvector
- **Purpose**: Vector database for embeddings and similarity search
- **Extension**: pgvector for vector operations
- **Connection**: Direct connection (no PgBouncer for simplicity)

### Redis Cluster
- **Purpose**: In-memory caching and session storage
- **Architecture**: Master + 3 replicas for high availability
- **Chart**: Bitnami Redis chart for reliability

### Neo4j
- **Purpose**: Graph database for relationship modeling
- **Configuration**: Community edition with proper resource limits
- **Ports**: 7687 (Bolt), 7474 (HTTP)

## Security and Networking Notes

- **Internal Communication**: All services use ClusterIP within the namespace
- **External Access**: Use `kubectl port-forward` for development access
- **Load Balancers**: Disabled for Neo4j (ClusterIP only)
- **Authentication**: Default passwords for development (change for production)

## Troubleshooting

### Ray Head Healthy but Workers Not Joining
```bash
# Check worker pod logs
kubectl logs seedcore-small-worker-* -n seedcore-dev

# Verify head service
kubectl get svc seedcore-head-svc -n seedcore-dev

# Check Ray cluster status
kubectl describe raycluster seedcore -n seedcore-dev
```

### Data Store Connection Issues
```bash
# Check service endpoints
kubectl get endpoints -n seedcore-dev

# Verify pod health
kubectl get pods -n seedcore-dev -l app.kubernetes.io/name

# Check service logs
kubectl logs <pod-name> -n seedcore-dev
```

### Client Connection Failures
```bash
# Test Ray connection
kubectl run ray-test --rm -it --image rayproject/ray:2.33.0-py310 \
  --restart=Never --namespace=seedcore-dev -- \
  python -c "import ray; ray.init(address='ray://seedcore-head-svc:10001', namespace='seedcore-dev'); print('Connected!'); ray.shutdown()"
```

## Notable Improvements

- **KubeRay Integration**: Proper Kubernetes-native Ray management
- **Data Store Integration**: All services deployed and tested together
- **Resource Management**: Proper CPU/memory limits and requests
- **Service Discovery**: Headless services for dynamic pod discovery
- **Load Balancer Removal**: No unnecessary external services

## Quick Reference

### Start Complete Environment
```bash
./setup-kind-ray.sh
```

### Scale Ray Workers
```bash
kubectl scale raycluster seedcore --replicas=5 -n seedcore-dev
```

### Access Services
```bash
# Ray Dashboard
kubectl port-forward -n seedcore-dev svc/seedcore-head-svc 8265:8265

# PostgreSQL
kubectl port-forward -n seedcore-dev svc/postgresql 5432:5432

# Neo4j Browser
kubectl port-forward -n seedcore-dev svc/neo4j 7474:7474
```

### Check Status
```bash
# All services
kubectl get pods,svc -n seedcore-dev

# Ray specific
kubectl get raycluster -n seedcore-dev
kubectl get pods -n seedcore-dev -l ray.io/cluster=seedcore
```


