#!/bin/bash
set -euo pipefail

echo "🚀 Deploying SeedCore Serve to Kubernetes (Non-Kind)"

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
IMAGE_NAME=${2:-"seedcore-serve:latest"}

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    print_status "ERROR" "kubectl is not installed. Please install it first."
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
if ! docker images | grep -q "seedcore-serve.*latest"; then
    print_status "ERROR" "Image $IMAGE_NAME not found locally. Please build it first with:"
    echo "   docker build -f docker/Dockerfile.serve -t seedcore-serve:latest ."
    exit 1
fi
print_status "OK" "Image $IMAGE_NAME found locally"

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
    # Try different label selectors for each store
    case $store in
        "postgresql")
            if kubectl get pods -n "$NAMESPACE" --no-headers | grep -q "postgresql.*Running"; then
                print_status "OK" "$store is running"
            else
                print_status "WARN" "$store is not running"
            fi
            ;;
        "mysql")
            if kubectl get pods -n "$NAMESPACE" --no-headers | grep -q "mysql.*Running"; then
                print_status "OK" "$store is running"
            else
                print_status "WARN" "$store is not running"
            fi
            ;;
        "redis")
            if kubectl get pods -n "$NAMESPACE" --no-headers | grep -q "redis.*Running"; then
                print_status "OK" "$store is running"
            else
                print_status "WARN" "$store is not running"
            fi
            ;;
        "neo4j")
            if kubectl get pods -n "$NAMESPACE" --no-headers | grep -q "neo4j.*Running"; then
                print_status "OK" "$store is running"
            else
                print_status "WARN" "$store is not running"
            fi
            ;;
    esac
done

# Show image loading options
echo ""
print_status "INFO" "Since you're using a real Kubernetes cluster (not Kind), you need to make your image available."
echo ""
echo "📋 Image Loading Options:"
echo "   1. Use local registry (recommended for development)"
echo "   2. Push to Docker Hub or other registry"
echo "   3. Use imagePullPolicy: Never (if image exists on all nodes)"
echo ""

# Ask user for preference
read -p "Choose option (1-3) or press Enter for option 1: " choice
choice=${choice:-1}

case $choice in
    1)
        print_status "INFO" "Setting up local registry..."
        
        # Check if local registry is running
        if ! docker ps | grep -q "registry:2"; then
            print_status "INFO" "Starting local registry..."
            docker run -d -p 5000:5000 --name registry registry:2
            sleep 5
        fi
        
        # Tag and push to local registry
        print_status "INFO" "Tagging and pushing image to local registry..."
        docker tag seedcore-serve:latest localhost:5000/seedcore-serve:latest
        docker push localhost:5000/seedcore-serve:latest
        
        IMAGE_NAME="localhost:5000/seedcore-serve:latest"
        IMAGE_PULL_POLICY="Always"
        print_status "OK" "Image available at $IMAGE_NAME"
        ;;
    2)
        print_status "INFO" "Please push your image to a registry and provide the full image name."
        read -p "Enter full image name (e.g., your-registry.com/seedcore-serve:latest): " IMAGE_NAME
        IMAGE_PULL_POLICY="Always"
        ;;
    3)
        print_status "INFO" "Using imagePullPolicy: Never (image must exist on all nodes)"
        IMAGE_NAME="seedcore-serve:latest"
        IMAGE_PULL_POLICY="Never"
        ;;
    *)
        print_status "ERROR" "Invalid choice"
        exit 1
        ;;
esac

# Deploy seedcore-serve
print_status "INFO" "Deploying seedcore-serve to namespace $NAMESPACE..."

cat <<EOF | kubectl -n "$NAMESPACE" apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: seedcore-serve-dev
  labels: { app: seedcore-serve }
spec:
  replicas: 1
  selector: { matchLabels: { app: seedcore-serve } }
  template:
    metadata:
      labels: { app: seedcore-serve }
    spec:
      containers:
      - name: serve
        image: $IMAGE_NAME
        imagePullPolicy: $IMAGE_PULL_POLICY
        env:
        - name: RAY_ADDRESS
          value: ray://seedcore-head-svc:10001
        - name: RAY_NAMESPACE
          value: seedcore-dev
        - name: SEEDCORE_NS
          value: seedcore-dev
        - name: SERVE_HTTP_HOST
          value: "0.0.0.0"
        - name: SERVE_HTTP_PORT
          value: "8000"
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
        - containerPort: 8000
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
  name: seedcore-serve-dev
  labels: { app: seedcore-serve }
spec:
  selector: { app: seedcore-serve }
  ports:
  - name: http
    port: 80
    targetPort: http
  type: ClusterIP
EOF

if [ $? -eq 0 ]; then
    print_status "OK" "seedcore-serve deployment applied successfully"
else
    print_status "ERROR" "Failed to apply seedcore-serve deployment"
    exit 1
fi

# Wait for deployment to be ready
print_status "INFO" "Waiting for seedcore-serve deployment to be ready..."
kubectl wait --for=condition=available --timeout=300s deployment/seedcore-serve-dev -n "$NAMESPACE"

if [ $? -eq 0 ]; then
    print_status "OK" "seedcore-serve deployment is ready"
else
    print_status "WARN" "seedcore-serve deployment may not be fully ready yet"
fi

# Check deployment status
print_status "INFO" "Checking deployment status..."
kubectl get deployment seedcore-serve-dev -n "$NAMESPACE"
kubectl get pods -n "$NAMESPACE" -l app=seedcore-serve

# Check service status
print_status "INFO" "Checking service status..."
kubectl get svc seedcore-serve-dev -n "$NAMESPACE"

# Show logs
print_status "INFO" "Showing recent logs from seedcore-serve..."
kubectl logs -n "$NAMESPACE" deployment/seedcore-serve-dev --tail=50

echo ""
print_status "OK" "🎉 seedcore-serve deployment completed!"
echo ""
echo "📊 Deployment Status:"
echo "   - Namespace: $NAMESPACE"
echo "   - Deployment: seedcore-serve-dev"
echo "   - Service: seedcore-serve-dev"
echo "   - Port: 80 (internal)"
echo "   - Image: $IMAGE_NAME"
echo ""
echo "🔧 Useful Commands:"
echo "   - Watch pods: kubectl -n $NAMESPACE get pods -w"
echo "   - Check logs: kubectl -n $NAMESPACE logs deployment/seedcore-serve-dev -f"
echo "   - Port forward: kubectl -n $NAMESPACE port-forward svc/seedcore-serve-dev 8001:80"
echo "   - Test health: kubectl -n $NAMESPACE exec -it \$(kubectl -n $NAMESPACE get pod -l app=seedcore-serve -o jsonpath='{.items[0].metadata.name}') -- curl http://localhost:8000/health"
echo ""
echo "🚀 Next steps:"
echo "   1. Monitor pod startup: kubectl -n $NAMESPACE get pods -w"
echo "   2. Check for any errors in logs"
echo "   3. Test the health endpoint once ready"
echo "   4. Deploy seedcore-api if needed"
