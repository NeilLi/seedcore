#!/bin/bash
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-seedcore-dev}"
RECREATE_CLUSTER="${RECREATE_CLUSTER:-false}"

# Detect interactive shell (TTY check)
if [[ -t 0 ]]; then
    INTERACTIVE=true
else
    INTERACTIVE=false
fi

echo "🚀 Starting Kind cluster only..."

# Check if cluster already exists (exact match - Debian-safe)
if kind get clusters 2>/dev/null | grep -Fxq "$CLUSTER_NAME"; then
    echo "⚠️  Cluster $CLUSTER_NAME already exists"

    # Environment variable takes precedence (CI/automation)
    if [[ "$RECREATE_CLUSTER" == "true" ]]; then
        echo "🗑️  Deleting existing cluster (RECREATE_CLUSTER=true)..."
        kind delete cluster --name "$CLUSTER_NAME"
    elif [[ "$INTERACTIVE" == true ]]; then
        # Only prompt in interactive shells
        read -r -p "Do you want to delete and recreate it? (y/N): " reply
        case "$reply" in
            y|Y)
                echo "🗑️  Deleting existing cluster..."
                kind delete cluster --name "$CLUSTER_NAME"
                ;;
            *)
                echo "✅ Using existing cluster"
                exit 0
                ;;
        esac
    else
        # Non-interactive: use existing cluster
        echo "ℹ️  Non-interactive shell detected — using existing cluster"
        echo "   Set RECREATE_CLUSTER=true to force recreation"
        exit 0
    fi
fi

# Generate kind-config.yaml with dynamic project root
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SEEDCORE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
KIND_CONFIG="${SCRIPT_DIR}/kind-config.yaml"

cat > "$KIND_CONFIG" <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    image: kindest/node:v1.30.0
    extraMounts:
      - hostPath: ${SEEDCORE_ROOT}
        containerPath: /project
EOF

# Create Kind cluster
echo "📦 Creating Kind cluster with kindest/node:v1.30.0..."
kind create cluster --name "$CLUSTER_NAME" --image kindest/node:v1.30.0 --config "$KIND_CONFIG"

# Verify cluster
echo "🔍 Verifying cluster..."
kubectl cluster-info --context "kind-$CLUSTER_NAME"

echo "✅ Kind cluster '$CLUSTER_NAME' is ready!"
echo ""
echo "�� Useful commands:"
echo "   - Check nodes: kubectl get nodes"
echo "   - Check context: kubectl config current-context"
echo "   - Switch context: kubectl config use-context kind-seedcore-dev"
echo "   - Delete cluster: kind delete cluster --name $CLUSTER_NAME"
