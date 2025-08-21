#!/bin/bash
# Run Cognitive Service on SeedCore API Pod
# This script acts as a driver, running on the seedcore-api pod,
# to deploy the cognitive service onto the Ray cluster's head node.

set -e

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
    case $status in
        "OK") echo -e "${GREEN}✅ $message${NC}" ;;
        "WARN") echo -e "${YELLOW}⚠️  $message${NC}" ;;
        "INFO") echo -e "${BLUE}ℹ️  $message${NC}" ;;
        "ERROR") echo -e "${RED}❌ $message${NC}" ;;
    esac
}

print_status "INFO" "Deploying Cognitive Service from API pod to Ray head node..."

# Get the script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
COGNITIVE_ENTRYPOINT="$PROJECT_ROOT/entrypoints/cognitive_entrypoint.py"

# Check if the cognitive entrypoint exists
if [ ! -f "$COGNITIVE_ENTRYPOINT" ]; then
    print_status "ERROR" "Cognitive entrypoint not found at: $COGNITIVE_ENTRYPOINT"
    exit 1
fi

# Check if we're likely in a Kubernetes pod environment
if [ -z "$KUBERNETES_SERVICE_HOST" ]; then
    print_status "WARN" "Not in a standard Kubernetes pod environment."
    print_status "INFO" "Ensure Ray is available and network is configured."
else
    print_status "INFO" "Detected Kubernetes environment - good!"
fi

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    print_status "ERROR" "Python 3 is not available"
    exit 1
fi

# Check if required packages are available
print_status "INFO" "Checking required packages..."
if python3 -c "import ray; from ray import serve" 2>/dev/null; then
    RAY_VERSION=$(python3 -c "import ray; print(ray.__version__)" 2>/dev/null || echo "unknown")
    print_status "OK" "Ray and Ray Serve packages are available (Ray v$RAY_VERSION)"
else
    print_status "ERROR" "Required packages (ray, serve) are not available"
    exit 1
fi

# Display configuration
print_status "INFO" "Configuration:"
echo "  - Ray Client Address: ${RAY_ADDRESS:-ray://seedcore-svc-head-svc:10001}"
echo "  - Ray Namespace: ${RAY_NAMESPACE:-seedcore-dev}"
echo "  - Ray Serve URL: ${RAY_SERVE_URL:-http://seedcore-svc-serve-svc:8000}"
echo "  - Cognitive App Name: ${COG_APP_NAME:-sc_cognitive}"

# Test import of the entrypoint
print_status "INFO" "Testing cognitive service entrypoint import..."
if python3 -c "import sys; sys.path.insert(0, '$(dirname "$COGNITIVE_ENTRYPOINT")'); import cognitive_entrypoint" 2>/dev/null; then
    print_status "OK" "Cognitive service entrypoint can be imported successfully"
else
    print_status "WARN" "Cognitive service entrypoint import test failed. Attempting to run anyway..."
fi

# Run the cognitive service
print_status "INFO" "Starting cognitive service deployment..."
print_status "INFO" "Service will be available at route prefix /cognitive"
print_status "INFO" "From any pod in the cluster, test with:"
print_status "INFO" "  curl http://seedcore-svc-serve-svc:8000/cognitive/health"
print_status "INFO" "Press Ctrl+C to stop the deployment driver."

exec python3 "$COGNITIVE_ENTRYPOINT"