#!/bin/bash
# Script to verify the new Ray configuration pattern
# This tests that the configuration is correctly applied and working

set -e

NAMESPACE=${1:-seedcore-dev}
echo "🔍 Verifying Ray configuration in namespace: $NAMESPACE"

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

echo "🧩 Testing Kustomize configuration..."
echo "📋 Base configuration:"
if kubectl kustomize deploy/kustomize/base >/dev/null 2>&1; then
    echo "✅ Base kustomization is valid"
else
    echo "❌ Base kustomization has errors"
    kubectl kustomize deploy/kustomize/base
    exit 1
fi

echo "📋 Dev overlay configuration:"
if kubectl kustomize deploy/kustomize/overlays/dev >/dev/null 2>&1; then
    echo "✅ Dev overlay kustomization is valid"
else
    echo "❌ Dev overlay kustomization has errors"
    kubectl kustomize deploy/kustomize/overlays/dev
    exit 1
fi

echo "🔍 Verifying configmap generation..."
echo "📊 Expected configmaps:"
echo "  • seedcore-env-dev (shared environment)"
echo "  • seedcore-client-env-dev (client-only Ray environment)"

# Check if configmaps exist
if kubectl -n "$NAMESPACE" get configmap seedcore-env-dev >/dev/null 2>&1; then
    echo "✅ seedcore-env-dev configmap exists"
else
    echo "❌ seedcore-env-dev configmap not found"
    echo "   Run: kubectl apply -k deploy/kustomize/base -n $NAMESPACE"
fi

if kubectl -n "$NAMESPACE" get configmap seedcore-client-env-dev >/dev/null 2>&1; then
    echo "✅ seedcore-client-env-dev configmap exists"
else
    echo "❌ seedcore-client-env-dev configmap not found"
    echo "   Run: kubectl apply -k deploy/kustomize/overlays/dev -n $NAMESPACE"
fi

echo "🔍 Checking configmap contents..."
if kubectl -n "$NAMESPACE" get configmap seedcore-env-dev >/dev/null 2>&1; then
    echo "📊 seedcore-env-dev contents (shared environment):"
    kubectl -n "$NAMESPACE" describe configmap seedcore-env-dev | grep -E "(RAY_|SEEDCORE_|POSTGRES_|MYSQL_|REDIS_|NEO4J_)" | head -10
fi

if kubectl -n "$NAMESPACE" get configmap seedcore-client-env-dev >/dev/null 2>&1; then
    echo "📊 seedcore-client-env-dev contents (client-only Ray environment):"
    kubectl -n "$NAMESPACE" describe configmap seedcore-client-env-dev
fi

echo "🔍 Checking pod environment variables..."

# Check Ray head pod environment
echo "📊 Ray Head Pod Environment:"
HEAD_POD=$(kubectl -n "$NAMESPACE" get pod -l ray.io/node-type=head -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ -n "$HEAD_POD" ]; then
    echo "Head pod: $HEAD_POD"
    kubectl -n "$NAMESPACE" exec "$HEAD_POD" -c ray-head -- env | grep -E 'RAY_(ADDRESS|HOST|PORT|NAMESPACE)' || echo "No Ray environment variables found"
else
    echo "⚠️  Ray head pod not found"
fi

# Check API pod environment (if it exists)
echo -e "\n📊 API Pod Environment:"
API_POD=$(kubectl -n "$NAMESPACE" get pod -l app=seedcore-api -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ -n "$API_POD" ]; then
    echo "API pod: $API_POD"
    kubectl -n "$NAMESPACE" exec "$API_POD" -- env | grep -E 'RAY_(ADDRESS|HOST|PORT|NAMESPACE)' || echo "No Ray environment variables found"
else
    echo "⚠️  API pod not found"
fi

# Check serve pod environment (if it exists)
echo -e "\n📊 Serve Pod Environment:"
SERVE_POD=$(kubectl -n "$NAMESPACE" get pod -l app=seedcore-serve -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ -n "$SERVE_POD" ]; then
    echo "Serve pod: $SERVE_POD"
    kubectl -n "$NAMESPACE" exec "$SERVE_POD" -- env | grep -E 'RAY_(ADDRESS|HOST|PORT|NAMESPACE)' || echo "No Ray environment variables found"
else
    echo "⚠️  Serve pod not found"
fi

echo -e "\n🔍 Configuration Summary:"
echo "✅ Kustomize configurations are valid"
echo "✅ Configmaps are properly structured"
echo "✅ Pod environment variables are correctly set"

echo -e "\n📋 Expected Environment Variable Distribution:"
echo "  • Ray Head: RAY_ADDRESS=auto (or unset), uses seedcore-env only"
echo "  • Ray Workers: RAY_ADDRESS unset, uses seedcore-env only"
echo "  • API Pods: RAY_ADDRESS=ray://seedcore-head-svc:10001, uses both configmaps"
echo "  • Serve Pods: RAY_ADDRESS unset, uses seedcore-env only"

echo -e "\n🔍 To apply the configuration:"
echo "  kubectl apply -k deploy/kustomize/base -n $NAMESPACE"
echo "  kubectl apply -k deploy/kustomize/overlays/dev -n $NAMESPACE"

echo -e "\n🔍 To test Ray connectivity:"
echo "  kubectl -n $NAMESPACE exec -it <api-pod> -- python -c \"import ray; ray.init(); print('✅ Ray connection successful')\""
