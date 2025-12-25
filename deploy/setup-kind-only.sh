#!/bin/bash
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-seedcore-dev}"
RECREATE_CLUSTER="${RECREATE_CLUSTER:-false}"
RESET_KIND_CACHE="${RESET_KIND_CACHE:-false}"
MIN_FREE_GB="${MIN_FREE_GB:-10}"

# -----------------------------
# Detect interactive shell
# -----------------------------
if [[ -t 0 ]]; then
    INTERACTIVE=true
else
    INTERACTIVE=false
fi

echo "🚀 Starting Kind cluster bootstrap..."

# -----------------------------
# Disk safety check
# -----------------------------
ROOT_FREE_GB=$(df --output=avail -BG / | tail -1 | tr -dc '0-9')

if (( ROOT_FREE_GB < MIN_FREE_GB )); then
    echo "❌ ERROR: Low disk space!"
    echo "   Available: ${ROOT_FREE_GB}GB, Required: ${MIN_FREE_GB}GB"
    echo "   Aborting to avoid containerd explosion."
    exit 1
fi

echo "💾 Disk OK: ${ROOT_FREE_GB}GB free"

# -----------------------------
# Optional Kind cache cleanup
# -----------------------------
if [[ "$RESET_KIND_CACHE" == "true" ]]; then
    echo "🧹 RESET_KIND_CACHE=true — cleaning Kind containerd cache..."
    sudo rm -rf /var/kind/containerd || true
    sudo mkdir -p /var/kind/containerd
    sudo chmod 755 /var/kind/containerd
fi

# -----------------------------
# Existing cluster handling
# -----------------------------
if kind get clusters 2>/dev/null | grep -Fxq "$CLUSTER_NAME"; then
    echo "⚠️  Cluster '$CLUSTER_NAME' already exists"

    if [[ "$RECREATE_CLUSTER" == "true" ]]; then
        echo "🗑️  Deleting existing cluster (RECREATE_CLUSTER=true)..."
        kind delete cluster --name "$CLUSTER_NAME"
    elif [[ "$INTERACTIVE" == true ]]; then
        read -r -p "Delete and recreate it? (y/N): " reply
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
        echo "ℹ️  Non-interactive shell — using existing cluster"
        echo "   Set RECREATE_CLUSTER=true to force recreation"
        exit 0
    fi
fi

# -----------------------------
# Generate Kind config
# -----------------------------
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

# -----------------------------
# Create cluster
# -----------------------------
echo "📦 Creating Kind cluster '$CLUSTER_NAME'..."
kind create cluster \
  --name "$CLUSTER_NAME" \
  --image kindest/node:v1.30.0 \
  --config "$KIND_CONFIG"

# -----------------------------
# Verify cluster
# -----------------------------
echo "🔍 Verifying cluster..."
kubectl cluster-info --context "kind-$CLUSTER_NAME"

echo ""
echo "✅ Kind cluster '$CLUSTER_NAME' is ready!"
echo ""
echo "🧭 Useful commands:"
echo "   kubectl get nodes"
echo "   kubectl config current-context"
echo "   kubectl config use-context kind-$CLUSTER_NAME"
echo "   kind delete cluster --name $CLUSTER_NAME"
echo ""
echo "🧹 Cleanup tips:"
echo "   RESET_KIND_CACHE=true ./start-kind.sh   # full cache reset"
echo "   kind delete cluster --name $CLUSTER_NAME"
