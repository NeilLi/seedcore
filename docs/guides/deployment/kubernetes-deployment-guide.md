# Kubernetes Deployment Guide

This guide provides comprehensive instructions for deploying SeedCore on Kubernetes using Kind, KubeRay, and Helm charts.

## 🚀 Prerequisites

Before you begin, ensure you have:

- **Docker** installed and running
- **Kind** (Kubernetes in Docker) installed
- **kubectl** configured
- **Helm 3.x** installed
- **Git** for cloning the repository

## 📋 Quick Start

### 1. Clone and Setup

```bash
git clone https://github.com/your-org/seedcore.git
cd seedcore/deploy
```

### 2. Run Complete Setup

```bash
# Make scripts executable
chmod +x setup-kind-ray.sh deploy-datastores.sh

# Run complete setup (creates cluster, installs Ray, deploys data stores)
./setup-kind-ray.sh
```

This single command will:
- Create a Kind Kubernetes cluster
- Install KubeRay operator
- Deploy Ray cluster with head + 2 workers
- Deploy all data stores (PostgreSQL, MySQL, Redis, Neo4j)
- Test connectivity

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Kind Kubernetes Cluster                  │
├─────────────────────────────────────────────────────────────┤
│  Namespace: seedcore-dev                                   │
│                                                             │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │   Ray Cluster   │    │   Data Stores   │                │
│  │                 │    │                 │                │
│  │ • Head Node     │    │ • PostgreSQL    │                │
│  │ • 2 Workers     │    │ • MySQL         │                │
│  │ • KubeRay Ops   │    │ • Redis         │                │
│  └─────────────────┘    │ • Neo4j         │                │
│           │              └─────────────────┘                │
│           │                       │                         │
│           └───────────────────────┼─────────────────────────┘
│                                   │                         │
│                    ┌─────────────────┐                     │
│                    │   Applications  │                     │
│                    │                 │                     │
│                    │ • SeedCore API  │                     │
│                    │ • Ray Serve     │                     │
│                    │ • Dashboards    │                     │
│                    └─────────────────┘                     │
└─────────────────────────────────────────────────────────────┘
```

## 🔧 Detailed Setup Steps

### Step 1: Create Kind Cluster

```bash
# Create cluster with custom configuration
kind create cluster --name seedcore-dev --image kindest/node:v1.30.0 --config kind-config.yaml

# Verify cluster
kubectl cluster-info --context kind-seedcore-dev
```

### Step 2: Install KubeRay Operator

```bash
# Add KubeRay Helm repository
helm repo add kuberay https://ray-project.github.io/kuberay-helm/
helm repo update

# Install KubeRay operator
helm install kuberay-operator kuberay/kuberay-operator \
  --namespace kuberay-system \
  --create-namespace \
  --wait

# Verify operator installation
kubectl get pods -n kuberay-system
```

### Step 3: Deploy Ray Cluster

```bash
# Create namespace
kubectl create namespace seedcore-dev

# Deploy Ray cluster
kubectl apply -f kustomize/base/raycluster.yaml -n seedcore-dev

# Wait for Ray cluster to be ready
kubectl wait --for=condition=ready pod -l ray.io/node-type=head -n seedcore-dev --timeout=300s
```

### Step 4: Deploy Data Stores

```bash
# Deploy all data stores
./deploy-datastores.sh

# Or deploy individually:
helm upgrade --install postgresql ./helm/postgresql --namespace seedcore-dev --wait
helm upgrade --install mysql ./helm/mysql --namespace seedcore-dev --wait
helm upgrade --install redis bitnami/redis --namespace seedcore-dev --set auth.enabled=false --wait
helm upgrade --install neo4j neo4j/neo4j --namespace seedcore-dev --set neo4j.name=neo4j --set neo4j.password=password --set volumes.data.mode=defaultStorageClass --wait
```

## 🌐 Service Endpoints

### Ray Cluster
- **Head Service**: `seedcore-head-svc.seedcore-dev.svc.cluster.local`
- **Client Port**: 10001 (for applications)
- **Dashboard Port**: 8265 (for monitoring)
- **GCS Port**: 6380 (for workers)

### Data Stores
- **PostgreSQL**: `postgresql.seedcore-dev.svc.cluster.local:5432`
- **MySQL**: `mysql.seedcore-dev.svc.cluster.local:3306`
- **Redis**: `redis-master.seedcore-dev.svc.cluster.local:6379`
- **Neo4j**: `neo4j.seedcore-dev.svc.cluster.local:7687`

## 🔑 Default Credentials

| Service | Username | Password | Database |
|---------|----------|----------|----------|
| PostgreSQL | postgres | password | postgres |
| MySQL | seedcore | password | seedcore |
| Neo4j | neo4j | password | - |
| Redis | - | - | no auth |

## 📊 Monitoring and Management

### Check Cluster Status

```bash
# All resources
kubectl get all -n seedcore-dev

# Ray cluster status
kubectl get raycluster -n seedcore-dev

# Data store pods
kubectl get pods -n seedcore-dev -l app.kubernetes.io/name

# Services
kubectl get svc -n seedcore-dev
```

### Access Dashboards

```bash
# Ray Dashboard
kubectl port-forward -n seedcore-dev svc/seedcore-head-svc 8265:8265

# Neo4j Browser
kubectl port-forward -n seedcore-dev svc/neo4j 7474:7474

# Grafana (if deployed)
kubectl port-forward -n seedcore-dev svc/grafana 3000:3000
```

### Scaling Operations

```bash
# Scale Ray workers
kubectl scale raycluster seedcore --replicas=5 -n seedcore-dev

# Check scaling status
kubectl get raycluster seedcore -n seedcore-dev -o yaml | grep -A 5 "workerGroupSpecs"
```

## 🧪 Testing Connectivity

### Test Ray Cluster

```bash
# Test Ray connection
kubectl run ray-test --rm -it --image rayproject/ray:2.33.0-py310 \
  --restart=Never --namespace=seedcore-dev -- \
  python -c "import ray; ray.init(address='ray://seedcore-head-svc:10001', namespace='seedcore-dev'); print('Connected!'); print('Resources:', ray.cluster_resources()); ray.shutdown()"
```

### Test Data Store Connections

```bash
# Test PostgreSQL
kubectl run postgres-test --rm -it --image postgres:16 --restart=Never --namespace=seedcore-dev -- \
  psql -h postgresql -U postgres -d postgres -c "SELECT version();"

# Test Redis
kubectl run redis-test --rm -it --image redis:7-alpine --restart=Never --namespace=seedcore-dev -- \
  redis-cli -h redis-master ping

# Test Neo4j
kubectl run neo4j-test --rm -it --image neo4j:5.15 --restart=Never --namespace=seedcore-dev -- \
  cypher-shell -a neo4j://neo4j:7687 -u neo4j -p password -c "RETURN 1 as test"
```

## 🔧 Configuration Customization

### Ray Cluster Configuration

Edit `deploy/kustomize/base/raycluster.yaml`:

```yaml
spec:
  headGroupSpec:
    rayStartParams:
      dashboard-host: "0.0.0.0"
    template:
      spec:
        containers:
        - name: ray-head
          resources:
            requests: { cpu: "1000m", memory: "2Gi" }
            limits: { cpu: "2000m", memory: "4Gi" }
  workerGroupSpecs:
  - groupName: small
    replicas: 5  # Change number of workers
    template:
      spec:
        containers:
        - name: ray-worker
          resources:
            requests: { cpu: "1000m", memory: "2Gi" }
            limits: { cpu: "2000m", memory: "4Gi" }
```

### Data Store Configuration

Edit individual Helm chart values in `deploy/helm/`:

```bash
# PostgreSQL
helm upgrade postgresql ./helm/postgresql --namespace seedcore-dev \
  --set postgresql.primary.resources.requests.cpu=500m \
  --set postgresql.primary.resources.requests.memory=1Gi

# Redis
helm upgrade redis bitnami/redis --namespace seedcore-dev \
  --set master.resources.requests.cpu=200m \
  --set master.resources.requests.memory=512Mi
```

## 🚨 Troubleshooting

### Common Issues

#### Ray Workers Not Connecting
```bash
# Check worker logs
kubectl logs seedcore-small-worker-* -n seedcore-dev

# Verify head service
kubectl get svc seedcore-head-svc -n seedcore-dev

# Check Ray cluster status
kubectl describe raycluster seedcore -n seedcore-dev
```

#### Data Store Connection Issues
```bash
# Check service endpoints
kubectl get endpoints -n seedcore-dev

# Verify pod health
kubectl get pods -n seedcore-dev

# Check service logs
kubectl logs <pod-name> -n seedcore-dev
```

#### Resource Constraints
```bash
# Check node resources
kubectl describe node seedcore-dev-control-plane

# Check pod resource usage
kubectl top pods -n seedcore-dev
```

### Debug Commands

```bash
# Get detailed Ray cluster info
kubectl describe raycluster seedcore -n seedcore-dev

# Check events
kubectl get events -n seedcore-dev --sort-by='.lastTimestamp'

# Check pod status
kubectl get pods -n seedcore-dev -o wide

# Check service endpoints
kubectl get endpoints -n seedcore-dev
```

## 🧹 Cleanup

### Remove Everything

```bash
# Delete Ray cluster
kubectl delete raycluster seedcore -n seedcore-dev

# Delete data stores
helm uninstall postgresql -n seedcore-dev
helm uninstall mysql -n seedcore-dev
helm uninstall redis -n seedcore-dev
helm uninstall neo4j -n seedcore-dev

# Delete namespace
kubectl delete namespace seedcore-dev

# Delete Kind cluster
kind delete cluster --name seedcore-dev
```

### Partial Cleanup

```bash
# Remove only data stores
./cleanup-datastores.sh

# Remove only Ray cluster
kubectl delete raycluster seedcore -n seedcore-dev
```

## 📚 Additional Resources

- [KubeRay Documentation](https://ray-project.github.io/kuberay/)
- [Kind Documentation](https://kind.sigs.k8s.io/)
- [Helm Documentation](https://helm.sh/docs/)
- [Ray Documentation](https://docs.ray.io/)

## 🎯 Next Steps

After successful deployment:

1. **Deploy Applications**: Use `kubectl apply -k kustomize/base/`
2. **Configure Monitoring**: Set up Prometheus and Grafana
3. **Scale Resources**: Adjust CPU/memory based on usage
4. **Production Hardening**: Update passwords, enable TLS, configure backups
5. **CI/CD Integration**: Automate deployments with GitOps workflows


