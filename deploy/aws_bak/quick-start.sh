#!/usr/bin/env bash
# Quick Start Script for SeedCore AWS EKS Deployment
# This script provides a guided setup process

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

# Check if .env.aws exists
check_env() {
    if [ ! -f "${SCRIPT_DIR}/.env.aws" ]; then
        warn "Environment file not found. Setting up..."
        
        if [ -f "${SCRIPT_DIR}/env.aws.example" ]; then
            cp "${SCRIPT_DIR}/env.aws.example" "${SCRIPT_DIR}/.env.aws"
            success "Environment file created from template"
            warn "Please edit ${SCRIPT_DIR}/.env.aws with your AWS configuration before continuing"
            echo
            echo "Required configuration:"
            echo "  - AWS_REGION: Your preferred AWS region"
            echo "  - AWS_ACCOUNT_ID: Your AWS account ID"
            echo "  - CLUSTER_NAME: Name for your EKS cluster"
            echo "  - NAMESPACE: Kubernetes namespace"
            echo "  - INGRESS_HOST: Your domain name"
            echo
            echo "After editing the file, run this script again."
            exit 1
        else
            error "Environment template not found. Please check your installation."
            exit 1
        fi
    fi
}

# Interactive setup
interactive_setup() {
    log "Starting interactive setup..."
    
    # Load environment
    source "${SCRIPT_DIR}/.env.aws"
    
    echo
    echo "Current configuration:"
    echo "  AWS Region: $AWS_REGION"
    echo "  AWS Account ID: $AWS_ACCOUNT_ID"
    echo "  Cluster Name: $CLUSTER_NAME"
    echo "  Namespace: $NAMESPACE"
    echo "  Ingress Host: $INGRESS_HOST"
    echo
    
    read -p "Is this configuration correct? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        warn "Please edit ${SCRIPT_DIR}/.env.aws and run this script again."
        exit 1
    fi
}

# Main deployment flow
main() {
    log "SeedCore AWS EKS Quick Start"
    echo "=========================="
    echo
    
    check_env
    interactive_setup
    
    echo
    log "Starting deployment process..."
    echo
    
    # Step 1: Initialize AWS infrastructure
    log "Step 1/5: Initializing AWS infrastructure..."
    "${SCRIPT_DIR}/aws-init.sh"
    echo
    
    # Step 2: Build and push images
    log "Step 2/5: Building and pushing Docker images..."
    "${SCRIPT_DIR}/build-and-push.sh"
    echo
    
    # Step 3: Create environment resources
    log "Step 3/5: Creating environment resources from env.example..."
    "${SCRIPT_DIR}/create-env-resources.sh"
    echo
    
    # Step 4: Deploy services
    log "Step 4/5: Deploying SeedCore services..."
    "${SCRIPT_DIR}/deploy-all.sh"
    echo
    
    # Step 5: Show status
    log "Step 5/5: Deployment complete! Showing status..."
    "${SCRIPT_DIR}/deploy-all.sh status"
    echo
    
    success "SeedCore deployment completed successfully!"
    echo
    echo "Next steps:"
    echo "1. Wait for all services to be ready (may take 5-10 minutes)"
    echo "2. Check service URLs in the status output above"
    echo "3. Test the API endpoints"
    echo "4. Monitor the deployment with: ./deploy-all.sh status"
    echo
    echo "For troubleshooting, see the README.md file"
}

# Run main function
main "$@"
