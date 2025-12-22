#!/usr/bin/env bash
set -euo pipefail

# ============================
# Datadog Kubernetes Bootstrap
# ============================

# -------- Config (override via env) --------
DATADOG_NAMESPACE="${DATADOG_NAMESPACE:-datadog}"
DATADOG_RELEASE="${DATADOG_RELEASE:-datadog}"

# IMPORTANT: match your Datadog UI region
DATADOG_SITE="${DATADOG_SITE:-ap1.datadoghq.com}"

# Required: export before running
# export DATADOG_API_KEY=xxxx
DATADOG_API_KEY="${DATADOG_API_KEY:-}"

CLUSTER_NAME="${CLUSTER_NAME:-seedcore-dev}"

# -------- Pretty printing --------
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}ℹ️  $*${NC}"; }
warn()  { echo -e "${YELLOW}⚠️  $*${NC}"; }
error() { echo -e "${RED}❌ $*${NC}"; }

# -------- Preflight --------
command -v helm >/dev/null || { error "helm not installed"; exit 1; }
command -v kubectl >/dev/null || { error "kubectl not installed"; exit 1; }

if [[ -z "$DATADOG_API_KEY" ]]; then
  error "DATADOG_API_KEY not set. Export it before running."
  exit 1
fi

info "Deploying Datadog to cluster '${CLUSTER_NAME}' (site: ${DATADOG_SITE})"

# -------- Namespace --------
if ! kubectl get ns "${DATADOG_NAMESPACE}" >/dev/null 2>&1; then
  info "Creating namespace ${DATADOG_NAMESPACE}"
  kubectl create namespace "${DATADOG_NAMESPACE}"
else
  info "Namespace ${DATADOG_NAMESPACE} already exists"
fi

# -------- Secret --------
if ! kubectl get secret datadog-secret -n "${DATADOG_NAMESPACE}" >/dev/null 2>&1; then
  info "Creating datadog-secret"
  kubectl create secret generic datadog-secret \
    -n "${DATADOG_NAMESPACE}" \
    --from-literal=api-key="${DATADOG_API_KEY}"
else
  info "datadog-secret already exists"
fi

# -------- Helm repo --------
info "Adding Datadog Helm repo"
helm repo add datadog https://helm.datadoghq.com >/dev/null 2>&1 || true
helm repo update >/dev/null

# -------- Install / Upgrade --------
info "Installing / upgrading Datadog Agent via Helm"

helm upgrade --install "${DATADOG_RELEASE}" datadog/datadog \
  -n "${DATADOG_NAMESPACE}" \
  --set datadog.site="${DATADOG_SITE}" \
  --set datadog.clusterName="${CLUSTER_NAME}" \
  --set datadog.apiKeyExistingSecret=datadog-secret \
  --set datadog.logs.enabled=true \
  --set datadog.logs.containerCollectAll=true \
  --set datadog.processAgent.enabled=true \
  --set datadog.kubelet.tlsVerify=false \
  --set clusterAgent.enabled=true

info "Datadog Helm release applied"

# -------- Optional restarts (safe) --------
info "Restarting Datadog pods to ensure config pickup"
kubectl rollout restart ds/datadog -n "${DATADOG_NAMESPACE}" || true
kubectl rollout restart deploy/datadog-cluster-agent -n "${DATADOG_NAMESPACE}" || true

# -------- Status --------
info "Waiting for Datadog pods to be Ready"
kubectl rollout status ds/datadog -n "${DATADOG_NAMESPACE}" --timeout=180s || true

echo
info "Datadog deployment complete 🎉"
echo "  - Cluster Name : ${CLUSTER_NAME}"
echo "  - Site         : ${DATADOG_SITE}"
echo "  - Namespace    : ${DATADOG_NAMESPACE}"
echo
echo "Next checks:"
echo "  kubectl get pods -n ${DATADOG_NAMESPACE}"
echo "  kubectl exec -n ${DATADOG_NAMESPACE} <datadog-pod> -c agent -- agent status"

