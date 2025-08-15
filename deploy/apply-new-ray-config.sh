#!/bin/bash
# Script to apply the new Ray configuration with separate configmaps
# This implements the new pattern where:
# - Head/worker pods use shared env only (no RAY_ADDRESS)
# - Client pods use shared + client env (with RAY_ADDRESS)

set -e

NAMESPACE=${1:-seedcore-dev}
echo "Applying new Ray configuration to namespace: $NAMESPACE"

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check prerequisites
if ! command_exists kubectl; then
    echo "❌ kubectl not found. Please install kubectl first."
    exit 1
fi

if ! command_exists kustomize; then
    echo "❌ kustomize not found. Please install kustomize first."
    echo "You can install it with: go install sigs.k8s.io/kustomize/kustomize/v5@latest"
    exit 1
fi

echo "🔍 Checking current namespace..."
if ! kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
    echo "❌ Namespace $NAMESPACE does not exist. Please create it first."
    exit 1
fi

echo "📋 Applying base configuration (creates seedcore-env configmap)..."
kubectl apply -k deploy/kustomize/base -n "$NAMESPACE"

echo "📋 Applying dev overlay (adds seedcore-client-env configmap)..."
kubectl apply -k deploy/kustomize/overlays/dev -n "$NAMESPACE"

echo "🔄 Restarting Ray head pod to pick up changes..."
# Find and delete the head pod to trigger restart
HEAD_POD=$(kubectl -n "$NAMESPACE" get pod -l ray.io/node-type=head -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ -n "$HEAD_POD" ]; then
    echo "Deleting head pod: $HEAD_POD"
    kubectl -n "$NAMESPACE" delete pod "$HEAD_POD"
else
    echo "⚠️  No Ray head pod found. This is normal if Ray hasn't been deployed yet."
fi

echo "⏳ Waiting for pods to be ready..."
kubectl -n "$NAMESPACE" wait --for=condition=ready pod -l ray.io/node-type=head --timeout=300s 2>/dev/null || echo "⚠️  Ray head pod not ready yet"

echo "🔍 Verifying environment variable configuration..."

# Check head pod environment
echo "📊 Ray Head Pod Environment:"
HEAD_POD=$(kubectl -n "$NAMESPACE" get pod -l ray.io/node-type=head -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ -n "$HEAD_POD" ]; then
    kubectl -n "$NAMESPACE" exec "$HEAD_POD" -c ray-head -- env | grep -E 'RAY_(ADDRESS|HOST|PORT|NAMESPACE)' || echo "No Ray environment variables found"
else
    echo "⚠️  Ray head pod not found"
fi

# Check API pod environment (if it exists)
echo -e "\n📊 API Pod Environment:"
API_POD=$(kubectl -n "$NAMESPACE" get pod -l app=seedcore-api -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ -n "$API_POD" ]; then
    kubectl -n "$NAMESPACE" exec "$API_POD" -- env | grep -E 'RAY_(ADDRESS|HOST|PORT|NAMESPACE)' || echo "No Ray environment variables found"
else
    echo "⚠️  API pod not found"
fi

# Check serve pod environment (if it exists)
echo -e "\n📊 Serve Pod Environment:"
SERVE_POD=$(kubectl -n "$NAMESPACE" get pod -l app=seedcore-serve -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ -n "$SERVE_POD" ]; then
    kubectl -n "$NAMESPACE" exec "$SERVE_POD" -- env | grep -E 'RAY_(ADDRESS|HOST|PORT|NAMESPACE)' || echo "No Ray environment variables found"
else
    echo "⚠️  Serve pod not found"
fi

echo -e "\n✅ New Ray configuration applied successfully!"
echo ""
echo "📋 Summary of changes:"
echo "  • Base configmap (seedcore-env): Contains shared environment variables"
echo "  • Client configmap (seedcore-client-env): Contains RAY_ADDRESS and client-specific vars"
echo "  • Head/worker pods: Use shared env only (RAY_ADDRESS=auto or unset)"
echo "  • Client pods: Use both shared + client env (with full RAY_ADDRESS)"
echo ""
echo "🔍 To verify the configuration:"
echo "  kubectl -n $NAMESPACE get configmaps"
echo "  kubectl -n $NAMESPACE describe configmap seedcore-env"
echo "  kubectl -n $NAMESPACE describe configmap seedcore-client-env"
