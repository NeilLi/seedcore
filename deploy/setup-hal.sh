#!/bin/bash
set -euo pipefail

# Setup script for SeedCore HAL Bridge
# Builds the HAL Docker image, loads it into Kind, and deploys to Kubernetes

CLUSTER_NAME="${CLUSTER_NAME:-seedcore-dev}"
NAMESPACE="${NAMESPACE:-seedcore-dev}"
IMAGE_NAME="${IMAGE_NAME:-seedcore-hal:latest}"
HAL_DRIVER_MODE="${HAL_DRIVER_MODE:-simulation}"
HAL_SIM_BACKEND="${HAL_SIM_BACKEND:-robot_sim}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "🔧 SeedCore HAL Bridge Setup"
echo "============================"
echo ""

# -----------------------------
# Prerequisites check
# -----------------------------
echo "📋 Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    echo "❌ ERROR: docker is not installed or not in PATH"
    exit 1
fi

if ! command -v kind &> /dev/null; then
    echo "❌ ERROR: kind is not installed or not in PATH"
    exit 1
fi

if ! command -v kubectl &> /dev/null; then
    echo "❌ ERROR: kubectl is not installed or not in PATH"
    exit 1
fi

# Check if Kind cluster exists
if ! kind get clusters 2>/dev/null | grep -Fxq "$CLUSTER_NAME"; then
    echo "❌ ERROR: Kind cluster '$CLUSTER_NAME' does not exist"
    echo "   Create it first with: deploy/setup-kind-only.sh"
    exit 1
fi

echo "✅ Prerequisites OK"
echo ""

# -----------------------------
# Step 1: Build the HAL image
# -----------------------------
echo "🔨 Step 1: Building HAL Docker image..."
echo "   Image: ${IMAGE_NAME}"
echo "   Dockerfile: docker/Dockerfile.hal"
echo "   HAL_DRIVER_MODE: ${HAL_DRIVER_MODE}"
echo "   HAL_SIM_BACKEND: ${HAL_SIM_BACKEND}"
echo ""

cd "${PROJECT_ROOT}"

# Build with explicit build args for clarity (defaults work from project root)
# These ARGs make the Dockerfile flexible for different build contexts
if ! docker build \
    --build-arg REQUIREMENTS_PATH=docker/requirements_hal.txt \
    --build-arg HAL_SRC_PATH=src/seedcore/hal \
    -t "${IMAGE_NAME}" \
    -f docker/Dockerfile.hal \
    .; then
    echo "❌ ERROR: Docker build failed"
    exit 1
fi

echo "✅ Docker image built successfully"
echo ""

# -----------------------------
# Step 2: Load image into Kind
# -----------------------------
echo "📦 Step 2: Loading image into Kind cluster..."
echo "   Cluster: ${CLUSTER_NAME}"
echo ""

if ! kind load docker-image "${IMAGE_NAME}" --name "${CLUSTER_NAME}"; then
    echo "❌ ERROR: Failed to load image into Kind"
    exit 1
fi

echo "✅ Image loaded into Kind successfully"
echo ""

# -----------------------------
# Step 3: Apply Kubernetes deployment
# -----------------------------
echo "🚀 Step 3: Applying Kubernetes deployment..."
echo "   Manifest: deploy/k8s/hal-bridge.yaml"
echo ""

DEPLOYMENT_FILE="${PROJECT_ROOT}/deploy/k8s/hal-bridge.yaml"

if [[ ! -f "${DEPLOYMENT_FILE}" ]]; then
    echo "❌ ERROR: Deployment file not found: ${DEPLOYMENT_FILE}"
    exit 1
fi

if ! kubectl apply -n "${NAMESPACE}" -f "${DEPLOYMENT_FILE}"; then
    echo "❌ ERROR: Failed to apply deployment"
    exit 1
fi

# Ensure rollout always uses caller-provided image and driver configuration.
if ! kubectl -n "${NAMESPACE}" set image deployment/seedcore-hal-bridge "hal-bridge=${IMAGE_NAME}"; then
    echo "❌ ERROR: Failed to set HAL bridge image to ${IMAGE_NAME}"
    exit 1
fi

if ! kubectl -n "${NAMESPACE}" set env deployment/seedcore-hal-bridge \
    "HAL_DRIVER_MODE=${HAL_DRIVER_MODE}" \
    "HAL_SIM_BACKEND=${HAL_SIM_BACKEND}"; then
    echo "❌ ERROR: Failed to set HAL runtime environment"
    exit 1
fi

echo "✅ Deployment applied successfully"
echo ""

# -----------------------------
# Wait for deployment to be ready
# -----------------------------
echo "⏳ Waiting for HAL Bridge to be ready..."
echo ""

if kubectl wait --for=condition=available --timeout=120s deployment/seedcore-hal-bridge -n "${NAMESPACE}" 2>/dev/null; then
    echo "✅ HAL Bridge is ready!"
else
    echo "⚠️  Deployment may still be starting. Check status with:"
    echo "   kubectl get pods -n ${NAMESPACE} -l app=hal-bridge"
    echo "   kubectl logs -n ${NAMESPACE} -l app=hal-bridge"
fi

echo ""
echo "🎉 HAL Bridge setup complete!"
echo ""
echo "📊 Useful commands:"
echo "   Check status:    kubectl get pods -n ${NAMESPACE} -l app=hal-bridge"
echo "   View logs:       kubectl logs -n ${NAMESPACE} -l app=hal-bridge -f"
echo "   Port forward:    kubectl port-forward -n ${NAMESPACE} svc/seedcore-hal-bridge 8003:8003"
echo "   Test endpoint:   curl http://localhost:8003/status"
echo ""
