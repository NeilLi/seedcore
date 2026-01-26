#!/bin/bash

# Deploy Minimal Data Stores to Kubernetes Cluster
# This script installs only PostgreSQL and Redis using Helm

set -e

# Resolve script directory for robust relative paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🚀 Deploying minimal data stores (PostgreSQL + Redis) to Kubernetes cluster..."

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

echo "✅ PostgreSQL and Redis deployed successfully!"
echo ""
echo "🔍 Checking deployment status..."
kubectl get pods -n seedcore-dev

echo ""
echo "🌐 Data store endpoints:"
echo "  PostgreSQL: postgresql.seedcore-dev.svc.cluster.local:5432"
echo "  Redis: redis.seedcore-dev.svc.cluster.local:6379"
echo ""
echo "🔑 Default credentials:"
echo "  PostgreSQL: postgres/password"
echo "  Redis: no authentication"
echo ""
echo "📋 Connection strings for applications:"
echo "  PG_DSN=postgresql://postgres:password@postgresql:5432/postgres"
echo "  REDIS_HOST=redis REDIS_PORT=6379"
echo ""
echo "💡 Note: PgBouncer has been removed for simplicity. Use direct PostgreSQL connections."
