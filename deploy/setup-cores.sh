#!/bin/bash

# Deploy Data Stores to Kubernetes Cluster
# This script installs PostgreSQL, MySQL, Redis, and Neo4j using Helm

set -e

# Resolve script directory for robust relative paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🚀 Deploying data stores to Kubernetes cluster..."

# Create namespace if it doesn't exist
kubectl create namespace seedcore-dev --dry-run=client -o yaml | kubectl apply -f -

# Deploy PostgreSQL with pgvector (PgBouncer disabled)
echo "📦 Deploying PostgreSQL with pgvector..."
helm upgrade --install postgresql "${SCRIPT_DIR}/helm/postgresql" \
  --namespace seedcore-dev \
  --set pgbouncer.enabled=false \
  --wait \
  --timeout 20m \
  --debug

# Deploy MySQL
echo "📦 Deploying MySQL..."
helm upgrade --install mysql "${SCRIPT_DIR}/helm/mysql" \
  --namespace seedcore-dev \
  --wait \
  --timeout 10m

# Deploy Redis using official Redis image (more reliable than Bitnami)
echo "📦 Deploying Redis using official image..."
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
  namespace: seedcore-dev
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:7.2-alpine
        ports:
        - containerPort: 6379
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
        command: ["redis-server", "--appendonly", "yes"]
        volumeMounts:
        - name: redis-data
          mountPath: /data
      volumes:
      - name: redis-data
        emptyDir: {}
---
apiVersion: v1
kind: Service
metadata:
  name: redis
  namespace: seedcore-dev
spec:
  selector:
    app: redis
  ports:
  - port: 6379
    targetPort: 6379
EOF

# Deploy Neo4j using official Helm chart
echo "📦 Deploying Neo4j using official Helm chart..."
if ! helm repo list | grep -q neo4j; then
  echo "📦 Adding Neo4j Helm repository..."
  helm repo add neo4j https://helm.neo4j.com/neo4j
  helm repo update
fi
helm upgrade --install neo4j neo4j/neo4j \
  --namespace seedcore-dev \
  --wait \
  --timeout 10m \
  --set neo4j.name=neo4j \
  --set neo4j.password=password \
  --set neo4j.resources.requests.cpu=500m \
  --set neo4j.resources.requests.memory=2Gi \
  --set neo4j.resources.limits.cpu=1000m \
  --set neo4j.resources.limits.memory=4Gi \
  --set neo4j.volumeSize=2Gi \
  --set volumes.data.mode=defaultStorageClass \
  --set services.neo4j.enabled=false \
  --set loadbalancer=exclude

# Deploy RAGFlow service
# echo "📦 Deploying RAGFlow..."
# helm upgrade --install ragflow "${SCRIPT_DIR}/helm/ragflow" \
#  --namespace seedcore-dev \
#  --set database.host=postgresql.seedcore-dev.svc.cluster.local \
#  --set database.user=postgres \
#  --set database.password=password \
#  --set redis.host=redis-master.seedcore-dev.svc.cluster.local \
#  --set neo4j.uri=bolt://neo4j.seedcore-dev.svc.cluster.local:7687 \
#  --wait \
#  --timeout 10m

echo "✅ All data stores and RAGFlow deployed successfully!"
echo ""
echo "🔍 Checking deployment status..."
kubectl get pods -n seedcore-dev

echo ""
echo "🌐 Data store endpoints:"
echo "  PostgreSQL: postgresql.seedcore-dev.svc.cluster.local:5432"
echo "  MySQL: mysql.seedcore-dev.svc.cluster.local:3306"
echo "  Redis: redis.seedcore-dev.svc.cluster.local:6379"
echo "  Neo4j: neo4j.seedcore-dev.svc.cluster.local:7687"
echo "  RAGFlow: ragflow.seedcore-dev.svc.cluster.local:8080"
echo ""
echo "🔑 Default credentials:"
echo "  PostgreSQL: postgres/password"
echo "  MySQL: seedcore/password"
echo "  Neo4j: neo4j/password"
echo "  Redis: no authentication"
echo ""
echo "📋 Connection strings for applications:"
echo "  PG_DSN=postgresql://postgres:password@postgresql:5432/postgres"
echo "  MYSQL_DATABASE_URL=mysql+mysqlconnector://seedcore:password@mysql:3306/seedcore"
echo "  REDIS_HOST=redis REDIS_PORT=6379"
echo "  NEO4J_URI=bolt://neo4j:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=password"
echo "  RAGFLOW_API_URL=http://ragflow:8080"
echo ""
echo "💡 Note: PgBouncer has been removed for simplicity. Use direct PostgreSQL connections."
