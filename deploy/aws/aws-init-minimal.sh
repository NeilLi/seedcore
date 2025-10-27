#!/usr/bin/env bash
# AWS EKS Minimal Initialization Script
# Sets up minimal requirements for SeedCore on AWS EKS

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

# Load environment variables
load_env() {
    local env_file="${SCRIPT_DIR}/.env.aws"
    
    if [ ! -f "$env_file" ]; then
        if [ -f "${SCRIPT_DIR}/env.aws.example" ]; then
            warn "Environment file not found. Copying from example..."
            cp "${SCRIPT_DIR}/env.aws.example" "$env_file"
            warn "Please edit ${env_file} with your AWS configuration"
            exit 1
        else
            error "Environment file not found: $env_file"
            exit 1
        fi
    fi
    
    log "Loading environment variables from $env_file"
    source "$env_file"
    
    # Set required variables if not set
    export AWS_REGION=${AWS_REGION:-us-east-1}
    export CLUSTER_NAME=${CLUSTER_NAME:-agentic-ai-cluster}
    export NAMESPACE=${NAMESPACE:-seedcore}
    
    success "Environment variables loaded successfully"
}

# Update kubeconfig
update_kubeconfig() {
    log "Updating kubeconfig..."
    
    aws eks update-kubeconfig \
        --region "$AWS_REGION" \
        --name "$CLUSTER_NAME"
    
    success "Kubeconfig updated successfully"
}

# Create namespace
create_namespace() {
    log "Creating namespace: $NAMESPACE"
    
    if kubectl get namespace "$NAMESPACE" &> /dev/null; then
        log "Namespace $NAMESPACE already exists"
    else
        kubectl create namespace "$NAMESPACE"
    fi
    
    success "Namespace created successfully"
}

# Install KubeRay operator
install_kuberay() {
    log "Installing KubeRay operator..."
    
    # Check if KubeRay CRDs exist
    if kubectl get crd rayclusters.ray.io &> /dev/null; then
        log "KubeRay operator already installed"
        success "KubeRay operator is ready"
        return 0
    fi
    
    log "KubeRay operator not found. Run ./install-kuberay.sh to install it."
    warn "KubeRay is required for RayService deployments."
    return 0
}

# Main function
main() {
    log "Starting minimal AWS EKS initialization..."
    
    load_env
    update_kubeconfig
    create_namespace
    install_kuberay
    
    success "Minimal AWS EKS initialization completed successfully!"
    
    echo
    echo "✅ Essential components are ready:"
    echo "   - Kubeconfig configured"
    echo "   - Namespace: $NAMESPACE"
    echo "   - KubeRay operator status: Check with 'kubectl get pods -n kuberay-system'"
    echo
    echo "📝 Next steps:"
    echo "1. Ensure KubeRay is installed: ./install-kuberay.sh"
    echo "2. Build and push Docker images: ./build-and-push.sh"
    echo "3. Deploy SeedCore: ./deploy-all.sh"
    echo
    echo "📋 Check KubeRay status:"
    echo "   kubectl get pods -n kuberay-system"
    echo "   kubectl get crd | grep ray"
}

# Run main function
main "$@"

