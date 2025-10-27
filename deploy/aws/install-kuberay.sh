#!/usr/bin/env bash
# Install KubeRay Operator for EKS
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load environment variables
if [ -f "${SCRIPT_DIR}/.env.aws" ]; then
    source "${SCRIPT_DIR}/.env.aws"
fi

echo "🔧 Installing KubeRay Operator..."

# Set AWS credentials (override with environment variables)
export AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID:-ASIAYJXTNHY6XMYVH47G}
export AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY:-sgQv5gtd5N83OfoxfXlW21ZFYd6fnKrXakqW+dq8}
export AWS_SESSION_TOKEN="IQoJb3JpZ2luX2VjEOL//////////wEaCXVzLXdlc3QtMiJHMEUCIAws4Ubae1GaoZhN0eYk/XdjnFvCoLHMPa73aVCVdh98AiEAleV6XCTW+F0vZ08WV9XPbD8Q5Rou6Vs/O8J4DcyC6B0qqgIIm///////////ARADGgw1NzA2NjczODQzODEiDC8kTWRMWcF2q4Enhir+ATPnOSWfVkQyEAw9yyohAYtPqQ32+Zto8GhYsG7gwZgA5Y5Lu10TZ9hX+W4g0O+fKWzA5/Hd4FeXRklg5gMfKprTRAnTWReGwXLKfil6x+tzlocx81ki5Q8BHsHONtECY3bt7Y14OTj8tLKMTOfw1yDa5CcoXaF5MHlTgemNLFA+8b94arxRK4edZ5nIkdSBZL9cY6df5NERwkffC56ECG6zq9Y+UNV0DhtdTyvExAe4h6tSX5ZzwRD4GJ1AUy19bcFjJZO63E9puKnkf5D/xZvRtWJsgokaUeR0H7aS0hf5oCX9syEAjyC6ReEBHyvtZBOEsMtZw/Yo8qhbXXf3MKic+8cGOp0Bvib0FE1Xtmu78FiYtcgD+AyVAnGq6cwgELVYnxxv4YJnDiS8zxFwQ6/gMDhPDtaEZ9taqZcMssyR12rBWEYYb67tTUoL8UJHKSlORyxZhfmoeFOdYDbzXSEg7ai370KHqkeZV5kFYuQCkCO0NbgE4oCJ0nXD/XDJMCJ6P51uZNLI9X9fieS8Zbq7rFpPG45TMqu0iOSV1y4sLM4FCQ=="
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

