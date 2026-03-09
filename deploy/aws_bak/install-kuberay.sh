#!/usr/bin/env bash
# Install KubeRay Operator for EKS
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load environment variables
if [ -f "${SCRIPT_DIR}/.env.aws" ]; then
    source "${SCRIPT_DIR}/.env.aws"
fi

echo "🔧 Installing KubeRay Operator..."

# Set AWS credentials from environment variables
# IMPORTANT: Do not hardcode credentials. Set them via environment or .env.aws file
if [ -z "${AWS_ACCESS_KEY_ID:-}" ]; then
    echo "ERROR: AWS_ACCESS_KEY_ID not set. Please export it or create .env.aws file"
    exit 1
fi
if [ -z "${AWS_SECRET_ACCESS_KEY:-}" ]; then
    echo "ERROR: AWS_SECRET_ACCESS_KEY not set. Please export it or create .env.aws file"
    exit 1
fi
export AWS_ACCESS_KEY_ID
export AWS_SECRET_ACCESS_KEY
export AWS_SESSION_TOKEN=${AWS_SESSION_TOKEN:-}
export AWS_REGION=${AWS_REGION:-us-east-1}
export CLUSTER_NAME=${CLUSTER_NAME:-agentic-ai-cluster}

# Update kubeconfig
echo "📋 Updating kubeconfig..."
aws eks update-kubeconfig --region ${AWS_REGION} --name ${CLUSTER_NAME} >/dev/null 2>&1
echo "✅ Connected to cluster: ${CLUSTER_NAME}"

# Install Helm if not present
if ! command -v helm &> /dev/null; then
    echo "⚠️  Helm not found. Installing Helm..."
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
    echo "✅ Helm installed"
fi

# Add KubeRay Helm repo
echo "📦 Adding KubeRay Helm repository..."
helm repo add kuberay https://ray-project.github.io/kuberay-helm/ 2>/dev/null || true
helm repo update >/dev/null 2>&1

# Create namespace
echo "🔨 Creating kuberay-system namespace..."
kubectl create namespace kuberay-system --dry-run=client -o yaml | kubectl apply -f - >/dev/null

# Check if already installed
if helm list -n kuberay-system | grep -q kuberay-operator; then
    echo "✅ KubeRay operator already installed"
    echo "📊 Current status:"
    kubectl get pods -n kuberay-system
else
    # Install KubeRay operator
    echo "🚀 Installing KubeRay operator..."
    helm install kuberay-operator kuberay/kuberay-operator \
        --namespace kuberay-system \
        --wait \
        --timeout 10m
    
    echo "✅ KubeRay operator installed successfully!"
fi

# Wait for pods to be ready
echo "⏳ Waiting for KubeRay operator to be ready..."
kubectl wait --for=condition=ready pod \
    -l app.kubernetes.io/name=kuberay-operator \
    -n kuberay-system \
    --timeout=300s 2>/dev/null || true

# Show status
echo ""
echo "📊 KubeRay Operator Status:"
kubectl get pods -n kuberay-system
kubectl get crd | grep ray.io

echo ""
echo "✅ Done! KubeRay is ready for RayService deployments."

