#!/bin/bash
set -euo pipefail

echo "🚀 Deploying SeedCore API to Kubernetes"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    local status=$1
    local message=$2
    if [ "$status" = "OK" ]; then
        echo -e "${GREEN}✅ $message${NC}"
    elif [ "$status" = "WARN" ]; then
        echo -e "${YELLOW}⚠️  $message${NC}"
    elif [ "$status" = "INFO" ]; then
        echo -e "${BLUE}ℹ️  $message${NC}"
    else
        echo -e "${RED}❌ $message${NC}"
    fi
}

# Default values
NAMESPACE=${1:-"seedcore-dev"}
IMAGE_NAME="seedcore-app:latest"
CLUSTER_NAME=${2:-"seedcore"}

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    print_status "ERROR" "kubectl is not installed. Please install it first."
    exit 1
fi

# Check if kind is available
if ! command -v kind &> /dev/null; then
    print_status "ERROR" "kind is not installed. Please install it first."
    exit 1
fi

# Check if namespace exists
print_status "INFO" "Checking namespace $NAMESPACE..."
if ! kubectl get namespace "$NAMESPACE" &> /dev/null; then
    print_status "WARN" "Namespace $NAMESPACE does not exist. Creating it..."
    kubectl create namespace "$NAMESPACE"
    print_status "OK" "Namespace $NAMESPACE created"
else
    print_status "OK" "Namespace $NAMESPACE exists"
fi

# Check if image exists locally
print_status "INFO" "Checking if image $IMAGE_NAME exists locally..."
if ! docker images | grep -q "seedcore-app.*latest"; then
    print_status "ERROR" "Image $IMAGE_NAME not found locally. Please build it first with:"
    echo "   docker build -f docker/Dockerfile.app -t seedcore-app:latest ."
    exit 1
fi
print_status "OK" "Image $IMAGE_NAME found locally"

# Load image into kind cluster
print_status "INFO" "Loading image $IMAGE_NAME into kind cluster $CLUSTER_NAME..."
if kind load docker-image "$IMAGE_NAME" --name "$CLUSTER_NAME"; then
    print_status "OK" "Image loaded into kind cluster successfully"
else
    print_status "ERROR" "Failed to load image into kind cluster"
    exit 1
fi

# Check if Ray cluster is running
print_status "INFO" "Checking if Ray cluster is running..."
if ! kubectl get pods -n "$NAMESPACE" -l ray.io/cluster=seedcore --no-headers | grep -q Running; then
    print_status "WARN" "Ray cluster does not appear to be running. Continuing anyway..."
else
    print_status "OK" "Ray cluster is running"
fi

# Check if data stores are running
print_status "INFO" "Checking data store status..."
DATA_STORES=("postgresql" "mysql" "redis" "neo4j")
for store in "${DATA_STORES[@]}"; do
    if kubectl get pods -n "$NAMESPACE" -l app="$store" --no-headers | grep -q Running; then
        print_status "OK" "$store is running"
    else
        print_status "WARN" "$store is not running"
    fi
done

# Check if seedcore-serve is already deployed (optional dependency)
print_status "INFO" "Checking if seedcore-serve is deployed..."
if kubectl get deployment seedcore-serve-dev -n "$NAMESPACE" &> /dev/null; then
    print_status "OK" "seedcore-serve is deployed (optional dependency)"
else
    print_status "INFO" "seedcore-serve is not deployed (optional dependency)"
fi

# Deploy seedcore-api
print_status "INFO" "Deploying seedcore-api to namespace $NAMESPACE..."

cat <<EOF | kubectl -n "$NAMESPACE" apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: seedcore-api-dev
  labels: { app: seedcore-api }
spec:
  replicas: 1
  selector: { matchLabels: { app: seedcore-api } }
  template:
    metadata:
      labels: { app: seedcore-api }
    spec:
      containers:
      - name: api
        image: seedcore-app:latest
        imagePullPolicy: IfNotPresent
        env:
        - name: RAY_ADDRESS
          value: ray://seedcore-head-svc:10001
        - name: RAY_NAMESPACE
          value: seedcore-dev
        - name: SEEDCORE_NS
          value: seedcore-dev
        - name: API_HOST
          value: "0.0.0.0"
        - name: API_PORT
          value: "8002"
        - name: PYTHONPATH
          value: /app:/app/src
        # Database connections
        - name: PG_DSN
          value: postgresql://postgres:password@postgresql:5432/postgres
        - name: MYSQL_DATABASE_URL
          value: mysql+mysqlconnector://seedcore:password@mysql:3306/seedcore
        - name: REDIS_HOST
          value: redis-master
        - name: REDIS_PORT
          value: "6379"
        - name: NEO4J_URI
          value: bolt://neo4j:7687
        - name: NEO4J_USER
          value: neo4j
        - name: NEO4J_PASSWORD
          value: password
        ports:
        - containerPort: 8002
          name: http
        resources:
          requests:
            cpu: "200m"
            memory: "256Mi"
          limits:
            cpu: "1"
            memory: "512Mi"
        readinessProbe:
          httpGet:
            path: /health
            port: http
          initialDelaySeconds: 30
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /health
            port: http
          initialDelaySeconds: 60
          periodSeconds: 30
---
apiVersion: v1
kind: Service
metadata:
  name: seedcore-api-dev
  labels: { app: seedcore-api }
spec:
  selector: { app: seedcore-api }
  ports:
  - name: http
    port: 80
    targetPort: http
  type: ClusterIP
EOF

if [ $? -eq 0 ]; then
    print_status "OK" "seedcore-api deployment applied successfully"
else
    print_status "ERROR" "Failed to apply seedcore-api deployment"
    exit 1
fi

# Wait for deployment to be ready
print_status "INFO" "Waiting for seedcore-api deployment to be ready..."
kubectl wait --for=condition=available --timeout=300s deployment/seedcore-api-dev -n "$NAMESPACE"

if [ $? -eq 0 ]; then
    print_status "OK" "seedcore-api deployment is ready"
else
    print_status "WARN" "seedcore-api deployment may not be fully ready yet"
fi

# Check deployment status
print_status "INFO" "Checking deployment status..."
kubectl get deployment seedcore-api-dev -n "$NAMESPACE"
kubectl get pods -n "$NAMESPACE" -l app=seedcore-api

# Check service status
print_status "INFO" "Checking service status..."
kubectl get svc seedcore-api-dev -n "$NAMESPACE"

# Show logs
print_status "INFO" "Showing recent logs from seedcore-api..."
kubectl logs -n "$NAMESPACE" deployment/seedcore-api-dev --tail=50

# Check overall cluster status
print_status "INFO" "Checking overall cluster status..."
echo ""
echo "📊 All Deployments in $NAMESPACE:"
kubectl get deployments -n "$NAMESPACE"
echo ""
echo "📊 All Services in $NAMESPACE:"
kubectl get svc -n "$NAMESPACE"
echo ""
echo "📊 All Pods in $NAMESPACE:"
kubectl get pods -n "$NAMESPACE"

echo ""
print_status "OK" "🎉 seedcore-api deployment completed!"
echo ""
echo "📊 Deployment Status:"
echo "   - Namespace: $NAMESPACE"
echo "   - Deployment: seedcore-api-dev"
echo "   - Service: seedcore-api-dev"
echo "   - Port: 80 (internal) -> 8002 (container)"
echo ""
echo "🔧 Useful Commands:"
echo "   - Watch pods: kubectl -n $NAMESPACE get pods -w"
echo "   - Check logs: kubectl -n $NAMESPACE logs deployment/seedcore-api-dev -f"
echo "   - Port forward: kubectl -n $NAMESPACE port-forward svc/seedcore-api-dev 8003:80"
echo "   - Test health: kubectl -n $NAMESPACE exec -it \$(kubectl -n $NAMESPACE get pod -l app=seedcore-api -o jsonpath='{.items[0].metadata.name}') -- curl http://localhost:8002/health"
echo ""
echo "🚀 Next steps:"
echo "   1. Monitor pod startup: kubectl -n $NAMESPACE get pods -w"
echo "   2. Check for any errors in logs"
echo "   3. Test the health endpoint once ready"
echo "   4. Test API endpoints via port-forward"
echo "   5. Verify Ray cluster connectivity"
echo ""
echo "🌐 Service Endpoints:"
echo "   - seedcore-serve: http://seedcore-serve-dev.$NAMESPACE.svc.cluster.local:80"
echo "   - seedcore-api: http://seedcore-api-dev.$NAMESPACE.svc.cluster.local:80"
echo "   - Ray Dashboard: http://seedcore-head-svc.$NAMESPACE.svc.cluster.local:8265"


