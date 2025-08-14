#!/bin/bash
set -euo pipefail

echo "🔍 Debugging Kind Cluster Status"

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

CLUSTER_NAME="seedcore"

echo "🔍 Checking Kind cluster status..."

# Check if kind is available
if ! command -v kind &> /dev/null; then
    print_status "ERROR" "kind is not installed"
    exit 1
fi

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    print_status "ERROR" "kubectl is not installed"
    exit 1
fi

# Check Kind clusters
echo "📋 Kind clusters:"
kind get clusters

# Check if our cluster exists
if kind get clusters | grep -q "$CLUSTER_NAME"; then
    print_status "OK" "Cluster $CLUSTER_NAME exists"
    
    # Check cluster nodes
    echo "📋 Cluster nodes:"
    kind get nodes --name "$CLUSTER_NAME"
    
    # Check Docker containers
    echo "📋 Docker containers for $CLUSTER_NAME:"
    docker ps -a | grep "$CLUSTER_NAME" || echo "No containers found"
    
    # Check if control plane is running
    if docker ps | grep -q "${CLUSTER_NAME}-control-plane"; then
        print_status "OK" "Control plane container is running"
        
        # Check cluster info
        echo "📋 Cluster info:"
        kubectl cluster-info --context "kind-$CLUSTER_NAME" || print_status "WARN" "Cannot get cluster info"
        
        # Check nodes
        echo "📋 Kubernetes nodes:"
        kubectl get nodes --context "kind-$CLUSTER_NAME" || print_status "WARN" "Cannot get nodes"
        
        # Check namespaces
        echo "📋 Namespaces:"
        kubectl get namespaces --context "kind-$CLUSTER_NAME" || print_status "WARN" "Cannot get namespaces"
        
    else
        print_status "ERROR" "Control plane container is NOT running"
        echo "📋 Stopped containers:"
        docker ps -a | grep "$CLUSTER_NAME"
        
        # Check container logs
        echo "📋 Control plane container logs:"
        docker logs "${CLUSTER_NAME}-control-plane" 2>/dev/null || echo "Cannot get logs"
    fi
else
    print_status "WARN" "Cluster $CLUSTER_NAME does not exist"
fi

# Check system resources
echo ""
echo "💻 System Resources:"
echo "📊 Memory:"
free -h

echo "📊 Disk space:"
df -h | head -5

echo "📊 Docker resources:"
docker system df

# Check Docker daemon status
echo "📊 Docker daemon status:"
docker info | grep -E "(Containers|Images|Storage Driver|Kernel Version)" || print_status "WARN" "Cannot get Docker info"

echo ""
print_status "INFO" "Debug information collected. Check the output above for issues."


