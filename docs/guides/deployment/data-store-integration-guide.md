# Data Store Integration Guide

This guide covers the integration and management of data stores in the SeedCore Kubernetes environment, including PostgreSQL, MySQL, Redis, and Neo4j.

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Kubernetes Namespace                     │
│                      seedcore-dev                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │   Ray Cluster   │    │   Data Stores   │                │
│  │                 │    │                 │                │
│  │ • Head Node     │    │ • PostgreSQL    │                │
│  │ • Workers       │    │ • MySQL         │                │
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

## 🚀 Quick Deployment

### Deploy All Data Stores

```bash
# From deploy directory
./deploy-datastores.sh
```

This script will deploy:
- PostgreSQL with pgvector extension
- MySQL with proper resource limits
- Redis cluster (master + replicas)
- Neo4j with optimized configuration

### Individual Deployment

```bash
# PostgreSQL
helm upgrade --install postgresql ./helm/postgresql --namespace seedcore-dev --wait

# MySQL
helm upgrade --install mysql ./helm/mysql --namespace seedcore-dev --wait

# Redis (using Bitnami chart)
helm upgrade --install redis bitnami/redis --namespace seedcore-dev \
  --set auth.enabled=false \
  --set master.persistence.size=512Mi \
  --wait

# Neo4j
helm upgrade --install neo4j neo4j/neo4j --namespace seedcore-dev \
  --set neo4j.name=neo4j \
  --set neo4j.password=password \
  --set volumes.data.mode=defaultStorageClass \
  --wait
```

## 📊 Data Store Details

### 1. PostgreSQL with pgvector

**Purpose**: Vector database for embeddings and similarity search

**Features**:
- PostgreSQL 16 with pgvector extension
- Direct connections (no PgBouncer for simplicity)
- Persistent storage with proper resource limits
- Vector similarity search capabilities

**Configuration**:
```yaml
# deploy/helm/postgresql/values.yaml
image:
  repository: pgvector/pgvector
  tag: "pg16"

postgresql:
  auth:
    postgresPassword: "password"
    database: "postgres"
    username: "postgres"
    password: "password"
  primary:
    resources:
      requests:
        cpu: "100m"
        memory: "256Mi"
      limits:
        cpu: "200m"
        memory: "512Mi"
    persistence:
      enabled: true
      size: "1Gi"
```

**Connection**:
```bash
# Connection string
postgresql://postgres:password@postgresql.seedcore-dev.svc.cluster.local:5432/postgres

# Test connection
kubectl run postgres-test --rm -it --image postgres:16 --restart=Never --namespace=seedcore-dev -- \
  psql -h postgresql -U postgres -d postgres -c "SELECT version();"
```

### 2. MySQL

**Purpose**: Relational database for structured data

**Features**:
- MySQL 8.0 with optimized configuration
- Persistent storage and proper resource management
- SeedCore-specific database and user setup

**Configuration**:
```yaml
# deploy/helm/mysql/values.yaml
image:
  repository: mysql
  tag: "8.0"

mysql:
  auth:
    rootPassword: "password"
    database: "seedcore"
    username: "seedcore"
    password: "password"
  primary:
    resources:
      requests:
        cpu: "100m"
        memory: "256Mi"
      limits:
        cpu: "200m"
        memory: "512Mi"
    persistence:
      enabled: true
      size: "1Gi"
```

**Connection**:
```bash
# Connection string
mysql+mysqlconnector://seedcore:password@mysql.seedcore-dev.svc.cluster.local:3306/seedcore

# Test connection
kubectl run mysql-test --rm -it --image mysql:8.0 --restart=Never --namespace=seedcore-dev -- \
  mysql -h mysql -u seedcore -ppassword -e "SELECT VERSION();"
```

### 3. Redis Cluster

**Purpose**: In-memory caching and session storage

**Features**:
- Redis 8.2.0 via Bitnami Helm chart
- Master + 3 replicas for high availability
- No authentication (development setup)
- Persistent storage for data durability

**Configuration**:
```bash
helm upgrade --install redis bitnami/redis --namespace seedcore-dev \
  --set auth.enabled=false \
  --set master.persistence.size=512Mi \
  --set master.resources.requests.cpu=50m \
  --set master.resources.requests.memory=64Mi \
  --set master.resources.limits.cpu=100m \
  --set master.resources.limits.memory=128Mi \
  --wait
```

**Connection**:
```bash
# Connection string
redis://redis-master.seedcore-dev.svc.cluster.local:6379

# Test connection
kubectl run redis-test --rm -it --image redis:7-alpine --restart=Never --namespace=seedcore-dev -- \
  redis-cli -h redis-master ping
```

### 4. Neo4j

**Purpose**: Graph database for relationship modeling

**Features**:
- Neo4j Community Edition
- Proper resource limits and persistence
- Bolt and HTTP protocols
- Graph database capabilities

**Configuration**:
```bash
helm upgrade --install neo4j neo4j/neo4j --namespace seedcore-dev \
  --set neo4j.name=neo4j \
  --set neo4j.password=password \
  --set neo4j.resources.requests.cpu=500m \
  --set neo4j.resources.requests.memory=2Gi \
  --set neo4j.resources.limits.cpu=1000m \
  --set neo4j.resources.limits.memory=4Gi \
  --set neo4j.volumeSize=2Gi \
  --set volumes.data.mode=defaultStorageClass \
  --set services.neo4j.enabled=false \
  --set loadbalancer=exclude \
  --wait
```

**Connection**:
```bash
# Connection string
bolt://neo4j.seedcore-dev.svc.cluster.local:7687

# Test connection
kubectl run neo4j-test --rm -it --image neo4j:5.15 --restart=Never --namespace=seedcore-dev -- \
  cypher-shell -a neo4j://neo4j:7687 -u neo4j -p password -c "RETURN 1 as test"
```

## 🔧 Configuration Management

### Environment Variables

Set these in your application deployments:

```yaml
env:
- name: PG_DSN
  value: "postgresql://postgres:password@postgresql:5432/postgres"
- name: MYSQL_DATABASE_URL
  value: "mysql+mysqlconnector://seedcore:password@mysql:3306/seedcore"
- name: REDIS_HOST
  value: "redis-master"
- name: REDIS_PORT
  value: "6379"
- name: NEO4J_URI
  value: "bolt://neo4j:7687"
- name: NEO4J_USER
  value: "neo4j"
- name: NEO4J_PASSWORD
  value: "password"
```

### Resource Management

**Total Resource Requirements**:
- **CPU**: 1150m (requests), 2.5 (limits)
- **Memory**: 2.32Gi (requests), 6.16Gi (limits)
- **Storage**: 4.5Gi total

**Individual Service Resources**:
```yaml
# PostgreSQL
requests: { cpu: "100m", memory: "256Mi" }
limits: { cpu: "200m", memory: "512Mi" }

# MySQL
requests: { cpu: "100m", memory: "256Mi" }
limits: { cpu: "200m", memory: "512Mi" }

# Redis
requests: { cpu: "50m", memory: "64Mi" }
limits: { cpu: "100m", memory: "128Mi" }

# Neo4j
requests: { cpu: "500m", memory: "2Gi" }
limits: { cpu: "1000m", memory: "4Gi" }
```

## 📊 Monitoring and Health Checks

### Service Status

```bash
# Check all data store pods
kubectl get pods -n seedcore-dev -l app.kubernetes.io/name

# Check services
kubectl get svc -n seedcore-dev

# Check persistent volumes
kubectl get pvc -n seedcore-dev
```

### Health Monitoring

```bash
# PostgreSQL health
kubectl exec -n seedcore-dev deployment/postgresql -- pg_isready -h localhost

# MySQL health
kubectl exec -n seedcore-dev deployment/mysql -- mysqladmin ping -h localhost

# Redis health
kubectl exec -n seedcore-dev statefulset/redis-master -- redis-cli ping

# Neo4j health
kubectl exec -n seedcore-dev statefulset/neo4j -- cypher-shell -a neo4j://localhost:7687 -u neo4j -p password -c "RETURN 1"
```

### Log Monitoring

```bash
# PostgreSQL logs
kubectl logs -n seedcore-dev deployment/postgresql

# MySQL logs
kubectl logs -n seedcore-dev deployment/mysql

# Redis logs
kubectl logs -n seedcore-dev statefulset/redis-master

# Neo4j logs
kubectl logs -n seedcore-dev statefulset/neo4j
```

## 🔒 Security Considerations

### Development vs Production

**Development (Current Setup)**:
- Default passwords for simplicity
- No TLS encryption
- Internal cluster access only
- No authentication for Redis

**Production Hardening**:
```bash
# Use secrets for passwords
kubectl create secret generic db-credentials \
  --from-literal=postgres-password=secure-password \
  --from-literal=mysql-password=secure-password \
  --from-literal=neo4j-password=secure-password \
  -n seedcore-dev

# Enable TLS
# Configure network policies
# Set up authentication for Redis
# Use external load balancers
```

### Network Security

```yaml
# Network policies (example)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: data-store-access
  namespace: seedcore-dev
spec:
  podSelector:
    matchLabels:
      app: seedcore-api
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: seedcore-api
    ports:
    - protocol: TCP
      port: 5432  # PostgreSQL
    - protocol: TCP
      port: 3306  # MySQL
    - protocol: TCP
      port: 6379  # Redis
    - protocol: TCP
      port: 7687  # Neo4j
```

## 🚨 Troubleshooting

### Common Issues

#### Connection Refused
```bash
# Check if pods are running
kubectl get pods -n seedcore-dev

# Check service endpoints
kubectl get endpoints -n seedcore-dev

# Check pod logs
kubectl logs <pod-name> -n seedcore-dev
```

#### Resource Constraints
```bash
# Check node resources
kubectl describe node seedcore-dev-control-plane

# Check pod resource usage
kubectl top pods -n seedcore-dev

# Check events
kubectl get events -n seedcore-dev --sort-by='.lastTimestamp'
```

#### Storage Issues
```bash
# Check persistent volumes
kubectl get pv,pvc -n seedcore-dev

# Check storage class
kubectl get storageclass

# Check pod events
kubectl describe pod <pod-name> -n seedcore-dev
```

### Debug Commands

```bash
# Get detailed service info
kubectl describe svc <service-name> -n seedcore-dev

# Check pod status
kubectl get pods -n seedcore-dev -o wide

# Check service endpoints
kubectl get endpoints -n seedcore-dev

# Check events
kubectl get events -n seedcore-dev --sort-by='.lastTimestamp'
```

## 🧹 Cleanup and Maintenance

### Backup Strategies

**PostgreSQL**:
```bash
# Create backup
kubectl exec -n seedcore-dev deployment/postgresql -- \
  pg_dump -h localhost -U postgres postgres > backup.sql

# Restore backup
kubectl exec -i -n seedcore-dev deployment/postgresql -- \
  psql -h localhost -U postgres postgres < backup.sql
```

**MySQL**:
```bash
# Create backup
kubectl exec -n seedcore-dev deployment/mysql -- \
  mysqldump -h localhost -u seedcore -ppassword seedcore > backup.sql

# Restore backup
kubectl exec -i -n seedcore-dev deployment/mysql -- \
  mysql -h localhost -u seedcore -ppassword seedcore < backup.sql
```

**Redis**:
```bash
# Create backup
kubectl exec -n seedcore-dev statefulset/redis-master -- \
  redis-cli --rdb /tmp/backup.rdb

# Copy backup from pod
kubectl cp seedcore-dev/redis-master-0:/tmp/backup.rdb ./backup.rdb
```

### Cleanup Commands

```bash
# Remove all data stores
helm uninstall postgresql -n seedcore-dev
helm uninstall mysql -n seedcore-dev
helm uninstall redis -n seedcore-dev
helm uninstall neo4j -n seedcore-dev

# Remove persistent volumes (WARNING: destroys data)
kubectl delete pvc --all -n seedcore-dev

# Remove namespace
kubectl delete namespace seedcore-dev
```

## 📚 Additional Resources

- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [MySQL Documentation](https://dev.mysql.com/doc/)
- [Redis Documentation](https://redis.io/documentation)
- [Neo4j Documentation](https://neo4j.com/docs/)
- [Kubernetes Storage](https://kubernetes.io/docs/concepts/storage/)
- [Helm Charts](https://helm.sh/docs/chart_template_guide/)

## 🎯 Next Steps

After successful data store deployment:

1. **Test Connections**: Verify all services are accessible
2. **Configure Applications**: Update application configurations with connection strings
3. **Set Up Monitoring**: Configure Prometheus and Grafana for data store metrics
4. **Implement Backups**: Set up automated backup strategies
5. **Production Hardening**: Update passwords, enable TLS, configure network policies
6. **Performance Tuning**: Optimize resource allocation based on usage patterns


