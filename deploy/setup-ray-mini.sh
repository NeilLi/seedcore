#!/bin/bash

set -euo pipefail

# Resolve script directory for robust relative paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🚀 Setting up Ray Head Deployment"

# ---------- Pretty printing ----------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
print_status() {
  local status=$1; local message=$2
  if [ "$status" = "OK" ]; then echo -e "${GREEN}✅ $message${NC}"
  elif [ "$status" = "WARN" ]; then echo -e "${YELLOW}⚠️  $message${NC}"
  elif [ "$status" = "INFO" ]; then echo -e "${BLUE}ℹ️  $message${NC}"
  else echo -e "${RED}❌ $message${NC}"; fi
}

# ---------- Config (overridable via env or CLI) ----------
NAMESPACE="${NAMESPACE:-seedcore-dev}"
RAY_HEAD_FILE="${RAY_HEAD_FILE:-${SCRIPT_DIR}/k8s/seedcore-ray-head.yaml}"

# .env → Secret
ENV_FILE_PATH="${ENV_FILE_PATH:-${SCRIPT_DIR}/../docker/.env}"
SECRET_NAME="${SECRET_NAME:-seedcore-env-secret}"

# Optional CLI: setup-ray-mini.sh [namespace] [ray_head_file]
if [[ $# -ge 1 ]]; then NAMESPACE="$1"; fi
if [[ $# -ge 2 ]]; then RAY_HEAD_FILE="$2"; fi

# ---------- Tool checks ----------
command -v kubectl >/dev/null || { print_status "ERROR" "kubectl is not installed."; exit 1; }

# ---------- Verify kubectl context ----------
print_status "INFO" "Verifying kubectl context..."
if ! kubectl cluster-info >/dev/null 2>&1; then
  print_status "ERROR" "kubectl context is not configured or cluster is not accessible"
  exit 1
fi
print_status "OK" "kubectl context verified"

# ---------- Namespace ----------
print_status "INFO" "Creating namespace $NAMESPACE (if missing)..."
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
print_status "OK" "Namespace ready"

# ---------- .env → Secret ----------
if [ -f "$ENV_FILE_PATH" ]; then
  print_status "INFO" "Creating/Updating Secret '${SECRET_NAME}' from ${ENV_FILE_PATH}..."
  kubectl -n "${NAMESPACE}" create secret generic "${SECRET_NAME}" \
    --from-env-file="${ENV_FILE_PATH}" \
    --dry-run=client -o yaml | kubectl apply -f -
  print_status "OK" "Secret ${SECRET_NAME} created/updated"
else
  print_status "WARN" "${ENV_FILE_PATH} not found. Skipping secret creation."
fi

# ---------- Deploy Ray Head ----------
if [ ! -f "${RAY_HEAD_FILE}" ]; then
  print_status "ERROR" "Ray Head file '${RAY_HEAD_FILE}' not found. Set RAY_HEAD_FILE or pass as 2nd arg."
  exit 1
fi

print_status "INFO" "Applying Ray Head deployment from ${RAY_HEAD_FILE}..."
kubectl apply -n "${NAMESPACE}" -f "${RAY_HEAD_FILE}"

# ---------- Wait for deployment ----------
print_status "INFO" "Waiting for Ray Head deployment to be ready..."
kubectl wait --for=condition=available deployment/seedcore-ray-head -n "${NAMESPACE}" --timeout=300s || {
  print_status "WARN" "Deployment did not become ready within timeout. Checking status..."
  kubectl -n "${NAMESPACE}" get deployment seedcore-ray-head
  kubectl -n "${NAMESPACE}" get pods -l component=ray-head
}

# ---------- Status & objects ----------
print_status "INFO" "Ray Head deployment status:"
kubectl -n "${NAMESPACE}" get deployment seedcore-ray-head

print_status "INFO" "Ray Head pods:"
kubectl -n "${NAMESPACE}" get pods -l component=ray-head

print_status "INFO" "Ray Head service:"
kubectl -n "${NAMESPACE}" get svc seedcore-head-svc

# ---------- Port-forward info ----------
echo
print_status "OK" "🔌 Port-forward (run in separate terminals):"
echo "  - Dashboard: kubectl -n ${NAMESPACE} port-forward svc/seedcore-head-svc 8265:8265"
echo "  - Serve HTTP: kubectl -n ${NAMESPACE} port-forward svc/seedcore-head-svc 8000:8000"

# ---------- Final summary ----------
echo
print_status "OK" "🎉 Ray Head deployment applied!"
echo
echo "📊 Deployment Info:"
echo "   - Namespace:    ${NAMESPACE}"
echo "   - Deployment:   seedcore-ray-head"
echo "   - Service:      seedcore-head-svc"
echo
echo "🔧 Useful commands:"
echo "   - List pods:        kubectl get pods -n ${NAMESPACE} -l component=ray-head"
echo "   - View logs:        kubectl logs -n ${NAMESPACE} -l component=ray-head -f"
echo "   - Describe deploy:  kubectl -n ${NAMESPACE} describe deployment seedcore-ray-head"
echo "   - Delete deploy:    kubectl -n ${NAMESPACE} delete -f ${RAY_HEAD_FILE}"
