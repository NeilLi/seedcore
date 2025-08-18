# Kind Cluster Reference Guide

## Overview
This document provides a comprehensive reference for working with the Seedcore Kind cluster setup, replacing the previous Docker Compose development environment.

## Cluster Information
- **Cluster Name**: `seedcore-dev`
- **Context**: `kind-seedcore-dev`
- **Namespace**: `seedcore-dev`
- **Node Version**: `kindest/node:v1.30.0`

## Services and Ports

**Current Running Services (as of latest deployment):**
- `seedcore-svc-head-svc` (ClusterIP: None) - ports: 10001, 8265, 6379, 8080, 8000
- `seedcore-svc-serve-svc` (ClusterIP: 10.96.171.126) - port: 8000

**Note:** Pod names may change between deployments. Use `kubectl get pods -n seedcore-dev` to get current pod names.

### Database Services

#### MySQL
- **Service**: `mysql`
- **Cluster IP**: `10.96.252.168`
- **Port**: `3306`
- **Pod**: `mysql-5cbdbbbb86-wgmz7`
- **Status**: Running

#### PostgreSQL
- **Service**: `postgresql`
- **Cluster IP**: `10.96.247.253`
- **Port**: `5432`
- **Pod**: `postgresql-f6cd57587-dpsq4`
- **Status**: Running

#### Neo4j
- **Service**: `neo4j`
- **Cluster IP**: `10.96.113.108`
- **Ports**: `7687` (Bolt), `7474` (HTTP)
- **Pod**: `neo4j-0`
- **Status**: Running

**Neo4j Admin Service**:
- **Service**: `neo4j-admin`
- **Cluster IP**: `10.96.68.19`
- **Ports**: `7687` (Bolt), `7474` (HTTP)

#### Redis
- **Master Service**: `redis-master`
  - **Cluster IP**: `10.96.34.35
  - **Port**: `6379`
  - **Pod**: `redis-master-0`
- **Replica Service**: `redis-replicas`
  - **Cluster IP**: `10.96.20.22
  - **Port**: `6379`
  - **Pods**: `redis-replicas-0`, `redis-replicas-1`, `redis-replicas-2`
- **Headless Service**: `redis-headless`
  - **Cluster IP**: None
  - **Port**: `6379`

### Seedcore Services

#### Ray Head Service
- **Service**: `seedcore-svc-head-svc`
- **Type**: Headless (ClusterIP: None)
- **Ports**: `10001` (Ray), `8265` (Dashboard), `6379`, `8080`, `8000`
- **Pod**: `seedcore-svc-k68dc-head-vpg4j` (current running pod)

#### Ray Worker Service
- **Note**: Worker pods are managed by RayService and may have different names
- **Replicas**: 1 (configurable via WORKER_REPLICAS env var)
- **Resources**: 2 CPU, 1Gi memory (requests), 2 CPU, 4Gi memory (limits)

#### Serve Service
- **Service**: `seedcore-svc-serve-svc`
- **Cluster IP**: `10.96.171.126`
- **Port**: `8000`

## RayService Architecture: Understanding Dual Head Services

**Short answer: they're not duplicates or a bug. RayService intentionally gives you two head Services:**

1. **A per-cluster head Service** for the *actual* RayCluster it spins up (name has a random suffix, e.g. `seedcore-svc-2jd2t-head-svc`).
2. **A stable head Service** that **RayService** manages (no suffix, e.g. `seedcore-svc-head-svc`) whose selector is switched to the current active cluster during upgrades/failover, so you always have a consistent DNS name.

Because RayService does zero-downtime upgrades by creating a new RayCluster and then **retargeting the stable Service's selector** once the new cluster is ready, you'll typically see *both* Services at the same time. That's by design.

### What each Service is for

* `seedcore-svc-2jd2t-head-svc` (suffix): auto-created with the underlying **RayCluster**; exposes the head pod ports directly for that one cluster instance.
* `seedcore-svc-head-svc` (no suffix): **RayService-managed stable head Service**; its selector is moved to whichever RayCluster is active. Use this for things like dashboard (8265) and Ray Client (10001) so your integrations don't break during upgrades.

You should also see a third Service once Serve is healthy: `seedcore-svc-serve-svc` (stable Serve frontdoor for HTTP 8000). With your `proxy_location: HeadOnly`, that Service will route to the head node's proxy. If it hasn't appeared yet, it usually means the Serve app isn't "healthy and ready" yet.

### How to confirm (handy commands)

```bash
# See the RayService-managed stable Services
kubectl get svc -n seedcore-dev | grep 'seedcore-svc-.*-svc'

# Inspect selectors to observe retargeting during updates
kubectl describe svc -n seedcore-dev seedcore-svc-head-svc
kubectl describe svc -n seedcore-dev seedcore-svc-serve-svc

# List the RayClusters RayService created (one will have a suffix)
kubectl get raycluster -n seedcore-dev
```

Docs note that RayService switches the **stable** head Service's selector to the new RayCluster when it's ready, which is why both the stable and per-cluster Services exist simultaneously.

### Customizing (if you want)

* You can customize the **spec of the head/serve Services** (type, ports, annotations, etc.) via CRD fields (e.g., `headService` / `serveService` in newer KubeRay), but the stable/per-cluster split remains—it's fundamental to RayService HA & upgrades.

### TL;DR guidance for your manifest

* Keep using **`seedcore-svc-head-svc`** for dashboard (8265) and Ray Client (10001).
* Send HTTP traffic to **`seedcore-svc-serve-svc`** once your Serve app is ready.
* Ignore the suffixed `*-head-svc` in app integrations; it's for the current RayCluster instance and will be replaced on upgrades.

**References:**
- [RayCluster Quickstart](https://docs.ray.io/en/latest/cluster/kubernetes/getting-started/raycluster-quick-start.html)
- [RayService User Guide](https://docs.ray.io/en/latest/cluster/kubernetes/user-guides/rayservice.html)
- [RayCluster Configuration](https://docs.ray.io/en/latest/cluster/kubernetes/user-guides/config.html)
- [RayService Quickstart](https://docs.ray.io/en/latest/cluster/kubernetes/getting-started/rayservice-quick-start.html)
- [KubeRay Changelog](https://github.com/ray-project/kuberay/blob/master/CHANGELOG.md)

## Port Forwarding

### Current Port Forwarding Script
The `deploy/port-forward.sh` script sets up the following port forwards:

```bash
# Management/Dashboard/Client/Metrics
kubectl -n seedcore-dev port-forward svc/seedcore-svc-head-svc 8265:8265
kubectl -n seedcore-dev port-forward svc/seedcore-svc-head-svc 10001:10001

# Serve HTTP
kubectl -n seedcore-dev port-forward svc/seedcore-svc-serve-svc 8000:8000
```

### Recommended Port Forwarding (from setup-ray.sh)
```bash
# Dashboard: kubectl -n seedcore-dev port-forward svc/seedcore-svc-head-svc 8265:8265
# Ray Client: kubectl -n seedcore-dev port-forward svc/seedcore-svc-head-svc 10001:10001
# Serve HTTP: kubectl -n seedcore-dev port-forward svc/seedcore-svc-serve-svc 8001:8000
```

### Manual Port Forwarding Commands
```bash
# Ray Dashboard
kubectl -n seedcore-dev port-forward svc/seedcore-svc-head-svc 8265:8265

# Ray Client
kubectl -n seedcore-dev port-forward svc/seedcore-svc-head-svc 10001:10001

# HTTP API (Serve)
kubectl -n seedcore-dev port-forward svc/seedcore-svc-serve-svc 8000:8000

# Standalone API (if deployed)
kubectl -n seedcore-dev port-forward svc/seedcore-api 8002:8002

# Database Access (if needed)
kubectl -n seedcore-dev port-forward svc/mysql 3306:3306
kubectl -n seedcore-dev port-forward svc/postgresql 5432:5432
kubectl -n seedcore-dev port-forward svc/neo4j 7474:7474
kubectl -n seedcore-dev port-forward svc/neo4j 7687:7687
kubectl -n seedcore-dev port-forward svc/redis-master 6379:6379
```

## Environment Variables
Key environment variables from `k8s.dev.env`:

```bash
SEEDCORE_NS=seedcore-dev
SEEDCORE_STAGE=dev
COG_APP_NAME=seedcore-dev-dev-cognitive_core
COG_MIN_READY=1
RAY_ADDRESS=ray://seedcore-svc-head-svc:10001
RAY_NAMESPACE=seedcore-dev
SEEDCORE_API_ADDRESS=seedcore-api-dev:80
```

### Ray Service Environment Variables
From `rayservice.yaml`, the Ray head and worker pods also have these environment variables:
```bash
RAY_NAMESPACE=seedcore-dev
SEEDCORE_NS=seedcore-dev
XGB_STORAGE_PATH=/app/data/models
```

## Useful Commands

### Cluster Management
```bash
# Check cluster status
kind get clusters
kubectl cluster-info --context kind-seedcore-dev

# Switch context
kubectl config use-context kind-seedcore-dev

# Check current context
kubectl config current-context

# Delete cluster
kind delete cluster --name seedcore-dev
```

### Pod Management
```bash
# List all pods
kubectl get pods -n seedcore-dev

# Get current Ray head pod name
kubectl get pods -n seedcore-dev -l ray.io/node-type=head -o jsonpath='{.items[0].metadata.name}'

# Get current Ray worker pod names
kubectl get pods -n seedcore-dev -l ray.io/node-type=worker -o jsonpath='{.items[*].metadata.name}'

# Get pod details
kubectl describe pod <pod-name> -n seedcore-dev

# Execute command in pod
kubectl exec -it <pod-name> -n seedcore-dev -- /bin/bash

# View pod logs
kubectl logs <pod-name> -n seedcore-dev -f
```

### Service Management
```bash
# List all services
kubectl get svc -n seedcore-dev

# Get service details
kubectl describe svc <service-name> -n seedcore-dev

# Check endpoints
kubectl get endpoints -n seedcore-dev
```

### Database Access
```bash
# MySQL
kubectl exec -it mysql-5cbdbbbb86-wgmz7 -n seedcore-dev -- mysql -u root -p

# PostgreSQL
kubectl exec -it postgresql-f6cd57587-dpsq4 -n seedcore-dev -- psql -U postgres

# Neo4j (via HTTP)
kubectl port-forward svc/neo4j 7474:7474 -n seedcore-dev
# Then access http://localhost:7474

# Redis
kubectl exec -it redis-master-0 -n seedcore-dev -- redis-cli
```

### Database Credentials (from setup-cores.sh)
```bash
# PostgreSQL: postgres/password
# MySQL: seedcore/password  
# Neo4j: neo4j/password
# Redis: no authentication
```

### Database Connection Strings
```bash
# PostgreSQL: postgresql://postgres:password@postgresql:5432/postgres
# MySQL: mysql+mysqlconnector://seedcore:password@mysql:3306/seedcore
# Redis: redis-master:6379
# Neo4j: bolt://neo4j:7687 (user: neo4j, password: password)
```

### Ray Management
```bash
# Check Ray cluster status (use current pod name)
kubectl exec -it seedcore-svc-k68dc-head-vpg4j -n seedcore-dev -- ray status

# Access Ray dashboard
kubectl port-forward svc/seedcore-svc-head-svc 8265:8265 -n seedcore-dev
# Then access http://localhost:8265

# Submit Ray job (use current pod name)
kubectl exec -it seedcore-svc-k68dc-head-vpg4j -n seedcore-dev -- ray job submit --working-dir /project -- python your_script.py

# Check RayService status
kubectl -n seedcore-dev get rayservice seedcore-svc -o yaml

# Check RayCluster status
kubectl -n seedcore-dev get raycluster -l ray.io/rayservice=seedcore-svc

# Get current pod names (for reference)
kubectl get pods -n seedcore-dev -l ray.io/node-type=head
kubectl get pods -n seedcore-dev -l ray.io/node-type=worker

# Example: Execute commands using current pod names dynamically
HEAD_POD=$(kubectl get pods -n seedcore-dev -l ray.io/node-type=head -o jsonpath='{.items[0].metadata.name}')
kubectl exec -it $HEAD_POD -n seedcore-dev -- ray status
```

## Troubleshooting

### Common Issues

#### Pod Not Starting
```bash
# Check pod events
kubectl describe pod <pod-name> -n seedcore-dev

# Check pod logs
kubectl logs <pod-name> -n seedcore-dev
```

#### Service Not Accessible
```bash
# Check service endpoints
kubectl get endpoints <service-name> -n seedcore-dev

# Check service configuration
kubectl describe svc <service-name> -n seedcore-dev
```

#### Port Forward Issues
```bash
# Check if port is already in use
netstat -tulpn | grep :<port>

# Kill existing port forward
pkill -f "kubectl.*port-forward.*:<port>"
```

### Debug Commands
```bash
# Check cluster resources
kubectl top nodes
kubectl top pods -n seedcore-dev

# Check events
kubectl get events -n seedcore-dev --sort-by='.lastTimestamp'

# Check resource quotas
kubectl describe resourcequota -n seedcore-dev
```

## Deployment Scripts

### Core Setup Scripts
- **`setup-kind-only.sh`**: Creates and configures the Kind cluster with project code mounting
- **`setup-cores.sh`**: Deploys databases (PostgreSQL, MySQL, Redis, Neo4j) using Helm charts
- **`setup-ray.sh`**: Deploys KubeRay operator and RayService with your application
- **`setup-api.sh`**: Deploys standalone API service (optional, separate from Ray Serve)

### Additional Scripts
- **`init_databases_k8s.sh`**: Initializes database schemas and data
- **`port-forward.sh`**: Sets up port forwarding for development access
- **`cleanup-datastores.sh`**: Cleans up database deployments
- **`debug-cluster.sh`**: Provides debugging information for the cluster

## Development Workflow

### 1. Start Cluster
```bash
cd deploy
./setup-kind-only.sh
```

### 2. Deploy Services
```bash
# Deploy databases and Ray services
./setup-ray.sh

# Deploy standalone API (optional)
./setup-api.sh

# Initialize databases
./init_databases_k8s.sh
```

### 3. Port Forward
```bash
# Start port forwarding
./port-forward.sh
```

### 4. Development
- Access Ray dashboard at `http://localhost:8265`
- Use Ray client at `localhost:10001`
- Access HTTP API (Serve) at `localhost:8000`
- Access Standalone API at `localhost:8002` (if deployed)

### 5. Cleanup
```bash
# Stop port forwarding
pkill -f "kubectl.*port-forward"

# Delete cluster (when done)
kind delete cluster --name seedcore-dev
```

## File Mounts
The Kind cluster is configured with the following mounts:

### Kind Cluster Mounts
- **Host Path**: `/home/ubuntu/project/seedcore`
- **Container Path**: `/project`
- **Purpose**: Access to project code from within the cluster

### Ray Service Mounts
- **Project Source Volume**: 
  - **Host Path**: `/project` (inside Kind node)
  - **Container Path**: `/project`
  - **Purpose**: Access to project code in Ray head and worker pods
- **XGB Model Storage**: 
  - **Type**: PersistentVolumeClaim (`xgb-pvc`)
  - **Container Path**: `/app/data`
  - **Purpose**: Storage for XGBoost models

### Standalone API Mounts
- **Project Source Volume**: 
  - **Host Path**: `/project` (inside Kind node)
  - **Container Path**: `/app`
  - **Purpose**: Access to project code in standalone API pods

## KubeRay Operator
The KubeRay operator manages the Ray cluster lifecycle and is installed in the `kuberay-system` namespace.

**Current Operator Status:**
- **Namespace**: `kuberay-system`
- **Pod**: `kuberay-operator-5ff4747794-v4xnj`
- **Status**: Running (1/1)
- **Restarts**: 2 (last restart 8h ago)
- **Age**: 2d1h

**Operator Management Commands:**
```bash
# Check operator status
kubectl get pods -n kuberay-system
kubectl get pods -A | grep kuberay-operator

# Check operator logs
kubectl logs -n kuberay-system deployment/kuberay-operator

# Check operator deployment
kubectl get deployment -n kuberay-system
```

## Notes
- All services run in the `seedcore-dev` namespace
- The cluster uses containerd with custom mounts
- Ray services are configured for distributed computing with Ray 2.33.0
- Database services are persistent and maintain data across restarts
- Use `kubectl` commands with `-n seedcore-dev` flag for namespace-specific operations
- The setup uses Helm charts for databases (PostgreSQL, MySQL, Redis, Neo4j)
- KubeRay operator manages the Ray cluster lifecycle
- Both Ray head and worker pods have resource limits and health checks configured

## Quick Verification Commands
To verify your current cluster state:
```bash
# Check current services
kubectl get svc -n seedcore-dev

# Check current pods
kubectl get pods -n seedcore-dev

# Check RayService status
kubectl get rayservice -n seedcore-dev

# Check RayCluster status
kubectl get raycluster -n seedcore-dev

# Check KubeRay operator status
kubectl get pods -n kuberay-system
kubectl get pods -A | grep kuberay-operator
```
