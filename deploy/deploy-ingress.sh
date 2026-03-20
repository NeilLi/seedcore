#!/bin/bash
set -e

# Resolve script directory for robust relative paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="${NAMESPACE:-seedcore-dev}"
SERVICE_NAME="${SERVICE_NAME:-seedcore-api}"
INGRESS_HOST="${INGRESS_HOST:-localhost}"
ORCHESTRATOR_HOST="${ORCHESTRATOR_HOST:-orchestrator.localhost}"
RAY_STABLE_SERVICE_NAME="${RAY_STABLE_SERVICE_NAME:-seedcore-svc-stable-svc}"

echo "🚀 Deploying SeedCore Ingress Routing Configuration..."

# Set environment variables for the ingress configuration
export NAMESPACE
export SERVICE_NAME
export INGRESS_HOST
export ORCHESTRATOR_HOST

echo "📋 Configuration:"
echo "  Namespace: $NAMESPACE"
echo "  Service Name: $SERVICE_NAME"
echo "  Ingress Host: $INGRESS_HOST"
echo "  Orchestrator Host: $ORCHESTRATOR_HOST"

# Check if we're in a Kind cluster
if kubectl config current-context | grep -q "kind"; then
    echo "✅ Detected Kind cluster"
    # For Kind, we'll use localhost and port-forwarding
    echo "ℹ️  Note: For Kind clusters, you'll need to set up port-forwarding to access the ingress"
else
    echo "ℹ️  Non-Kind cluster detected. Update INGRESS_HOST and ORCHESTRATOR_HOST as needed."
fi

# Check if services exist
echo "🔍 Checking required services..."
if ! kubectl get service $SERVICE_NAME -n $NAMESPACE >/dev/null 2>&1; then
    echo "❌ Error: Service $SERVICE_NAME not found in namespace $NAMESPACE"
    exit 1
fi

if ! kubectl get service "$RAY_STABLE_SERVICE_NAME" -n "$NAMESPACE" >/dev/null 2>&1; then
    echo "❌ Error: Service $RAY_STABLE_SERVICE_NAME not found in namespace $NAMESPACE"
    exit 1
fi

echo "✅ All required services found"

# Deploy the ingress
echo "📦 Deploying ingress configuration..."

# Create a temporary file with substituted variables
TEMP_FILE=$(mktemp)
envsubst < "${SCRIPT_DIR}/k8s/ingress-routing.yaml" > "$TEMP_FILE"

# Deploy the ingress
kubectl apply -f "$TEMP_FILE"

# Clean up
rm "$TEMP_FILE"

echo "✅ Ingress routing configuration deployed successfully!"

# Show the deployed ingress
echo "📋 Deployed ingress:"
kubectl get ingress -n $NAMESPACE

echo ""
echo "🔗 Access URLs (after setting up port-forwarding for Kind):"
echo "  API: http://$INGRESS_HOST/api/v1/tasks"
echo "  Organism: http://$INGRESS_HOST/organism/health"
echo "  Orchestrator: http://$INGRESS_HOST/orchestrator/health"
echo "  Pipeline: http://$INGRESS_HOST/pipeline/create-task"
echo ""
echo "📝 To set up port-forwarding for Kind cluster:"
echo "  kubectl port-forward -n $NAMESPACE service/$SERVICE_NAME 8002:8002"
echo "  kubectl port-forward -n $NAMESPACE service/$RAY_STABLE_SERVICE_NAME 8000:8000"
