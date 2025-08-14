# Data Store Deployment Guide

This guide explains how to deploy lightweight data stores (PostgreSQL, MySQL, Redis, Neo4j) to your Kubernetes cluster for use with SeedCore applications.

## Overview

The data stores are configured to use cluster DNS for networking, ensuring consistent environments and avoiding host bridging issues. All services are deployed with minimal resource requirements suitable for development and testing.

**Current Status**: All services are tested and working in the seedcore-dev namespace.

## Prerequisites

- Kubernetes cluster (kind, minikube, or cloud provider)
- Helm 3.x installed
- kubectl configured to access your cluster
- Docker images available locally (as mentioned in your requirements)

## Data Store Images

The following Docker images are used:
- **PostgreSQL**: `pgvector/pgvector:pg16` (with pgvector extension)
- **MySQL**: `mysql:8.0`
- **Redis**: `bitnami/redis:8.2.0` (via Bitnami Helm chart)
- **Neo4j**: `neo4j:5.15` (via official Neo4j Helm chart)

## Quick Deployment

### 1. Deploy All Data Stores

```bash
# Make scripts executable
chmod +x deploy/deploy-datastores.sh
chmod +x deploy/cleanup-datastores.sh

# Deploy all data stores
./deploy/deploy-datastores.sh
```

### 2. Verify Deployment

```bash
# Check all pods are running
kubectl get pods -n seedcore-dev

# Check services
kubectl get svc -n seedcore-dev

# Check persistent volume claims
kubectl get pvc -n seedcore-dev
```

## Individual Helm Charts

### PostgreSQL with pgvector

```bash
helm install postgresql ./deploy/helm/postgresql \
  --namespace seedcore-dev \
  --wait
```

**Features:**
- PostgreSQL 16 with pgvector extension for vector operations
- Direct connections (no PgBouncer for simplicity)
- Persistent storage (1Gi)
- Minimal resource usage: 100m CPU, 256Mi memory

### MySQL

```bash
helm install mysql ./deploy/helm/mysql \
  --namespace seedcore-dev \
  --wait
```

**Features:**
- MySQL 8.0
- Persistent storage (1Gi)
- Minimal resource usage: 100m CPU, 256Mi memory

### Redis

```bash
helm install redis bitnami/redis \
  --namespace seedcore-dev \
  --set auth.enabled=false \
  --set master.persistence.size=512Mi \
  --wait
```

**Features:**
- Redis 8.2.0 via Bitnami Helm chart
- Persistent storage (512Mi)
- Minimal resource usage: 50m CPU, 64Mi memory
- No authentication (development setup)

### Neo4j

```bash
helm install neo4j neo4j/neo4j \
  --namespace seedcore-dev \
  --wait \
  --set neo4j.name=neo4j \
  --set neo4j.password=password \
  --set neo4j.resources.requests.cpu=500m \
  --set neo4j.resources.requests.memory=2Gi \
  --set neo4j.resources.limits.cpu=1000m \
  --set neo4j.resources.limits.memory=4Gi \
  --set neo4j.volumeSize=2Gi \
  --set volumes.data.mode=defaultStorageClass
```

**Features:**
- Neo4j 5.15 (official Helm chart)
- Persistent storage (2Gi)
- Resource usage: 500m CPU, 2Gi memory (requests)
- Uses official Neo4j Helm repository

## Connection Strings

Once deployed, your applications can connect using these environment variables:

```bash
# PostgreSQL (direct connection)
PG_DSN=postgresql://postgres:password@postgresql:5432/postgres

# MySQL
MYSQL_DATABASE_URL=mysql+mysqlconnector://seedcore:password@mysql:3306/seedcore

# Redis
REDIS_HOST=redis-master
REDIS_PORT=6379

# Neo4j
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
```

## Service Endpoints

All services are accessible within the cluster using these DNS names:

- **PostgreSQL**: `postgresql.seedcore-dev.svc.cluster.local:5432`
- **MySQL**: `mysql.seedcore-dev.svc.cluster.local:3306`
- **Redis**: `redis-master.seedcore-dev.svc.cluster.local:6379`
- **Neo4j**: `neo4j.seedcore-dev.svc.cluster.local:7687`

## Default Credentials

- **PostgreSQL**: `postgres/password`
- **MySQL**: `seedcore/password`
- **Neo4j**: `neo4j/password`
- **Redis**: No authentication

## Resource Requirements

Total cluster resources needed:
- **CPU**: 1150m (requests), 2.5 (limits)
- **Memory**: 2.32Gi (requests), 6.16Gi (limits)
- **Storage**: 4.5Gi (PostgreSQL: 1Gi, MySQL: 1Gi, Redis: 512Mi, Neo4j: 2Gi)

## Configuration Updates

The SeedCore API and Serve deployments have been updated to include these database connection strings. The configurations are available in:

- **Kustomize**: `deploy/kustomize/base/`
- **Helm**: `deploy/helm/seedcore-api/` and `deploy/helm/seedcore-serve/`

## Troubleshooting

### Check Pod Logs

```bash
# PostgreSQL
kubectl logs -n seedcore-dev -l app.kubernetes.io/name=postgresql

# MySQL
kubectl logs -n seedcore-dev -l app.kubernetes.io/name=mysql

# Redis
kubectl logs -n seedcore-dev -l app.kubernetes.io/name=redis

# Neo4j
kubectl logs -n seedcore-dev -l app.kubernetes.io/name=neo4j
```

### Check Service Connectivity

```bash
# Test PostgreSQL connection
kubectl run -n seedcore-dev test-postgres --rm -i --tty --image postgres:16 -- psql -h postgresql-pgbouncer -U postgres -d postgres

# Test MySQL connection
kubectl run -n seedcore-dev test-mysql --rm -i --tty --image mysql:8.0 -- mysql -h mysql -u seedcore -pseedcore seedcore

# Test Redis connection
kubectl run -n seedcore-dev test-redis --rm -i --tty --image redis:7.2-alpine -- redis-cli -h redis ping

# Test Neo4j connection
kubectl run -n seedcore-dev test-neo4j --rm -i --tty --image neo4j:5.15 -- cypher-shell -a neo4j:7687 -u neo4j -p password
```

## Cleanup

To remove all data stores:

```bash
./deploy/cleanup-datastores.sh
```

**Note**: By default, Persistent Volume Claims (PVCs) are not removed to preserve your data. Uncomment the PVC removal line in the cleanup script if you want to remove all data.

## Benefits of Cluster DNS Approach

✅ **Easiest networking** - No complex port forwarding or host bridging
✅ **Consistent environments** - Same connection strings across dev/staging/prod
✅ **No host bridging weirdness** - Clean Kubernetes-native networking
✅ **Scalable** - Easy to add replicas or move to different nodes
✅ **Secure** - Services only accessible within the cluster by default

## Next Steps

1. Deploy the data stores using the provided script
2. Verify all services are running correctly
3. Update your application configurations if needed
4. Test connectivity from your SeedCore applications
5. Monitor resource usage and adjust limits as needed
