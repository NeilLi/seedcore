#!/bin/bash
set -euo pipefail

echo "🚀 Setting up Kind Cluster with RayService and Data Stores"

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
CLUSTER_NAME="${CLUSTER_NAME:-seedcore-dev}"
NAMESPACE="${NAMESPACE:-seedcore-dev}"
RAY_VERSION="${RAY_VERSION:-2.33.0}"
RAY_IMAGE="${RAY_IMAGE:-seedcore-serve:latest}"   # your image (already built locally)
WORKER_REPLICAS="${WORKER_REPLICAS:-1}"

# RayService bits
RAYSERVICE_FILE="${RAYSERVICE_FILE:-rayservice.yaml}"  # path to your RayService YAML
RS_NAME="${RS_NAME:-seedcore-svc}"                      # metadata.name inside rayservice.yaml

# Optional CLI: setup-kind-ray.sh [namespace] [cluster_name] [image] [rayservice_file] [rayservice_name]
if [[ $# -ge 1 ]]; then NAMESPACE="$1"; fi
if [[ $# -ge 2 ]]; then CLUSTER_NAME="$2"; fi
if [[ $# -ge 3 ]]; then RAY_IMAGE="$3"; fi
if [[ $# -ge 4 ]]; then RAYSERVICE_FILE="$4"; fi
if [[ $# -ge 5 ]]; then RS_NAME="$5"; fi

# .env → Secret
ENV_FILE_PATH="${ENV_FILE_PATH:-../docker/.env}"
SECRET_NAME="${SECRET_NAME:-seedcore-env-secret}"

# ---------- Tool checks ----------
command -v kind >/dev/null || { print_status "ERROR" "kind is not installed."; exit 1; }
command -v kubectl >/dev/null || { print_status "ERROR" "kubectl is not installed."; exit 1; }
command -v helm >/dev/null || { print_status "ERROR" "helm is not installed."; exit 1; }

# ---------- Kind cluster ----------
if ! kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
  print_status "INFO" "Creating Kind cluster '$CLUSTER_NAME'..."
  kind create cluster --name "$CLUSTER_NAME"
  print_status "OK" "Kind cluster created"
else
  print_status "OK" "Kind cluster '$CLUSTER_NAME' already exists"
fi

# Set context
print_status "INFO" "Setting kubectl context..."
kubectl cluster-info --context "kind-$CLUSTER_NAME" >/dev/null

# ---------- Namespace ----------
print_status "INFO" "Creating namespace $NAMESPACE (if missing)..."
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
print_status "OK" "Namespace ready"

# ---------- Load your image into Kind ----------
print_status "INFO" "Loading image ${RAY_IMAGE} into Kind nodes (${CLUSTER_NAME})..."
kind load docker-image "${RAY_IMAGE}" --name "${CLUSTER_NAME}"
print_status "OK" "Image loaded into Kind nodes"

# ---------- Host data dir (mounted via hostPath for pods) ----------
print_status "INFO" "Setting up /tmp/seedcore-data on host..."
sudo mkdir -p /tmp/seedcore-data
sudo chown -R 1000:1000 /tmp/seedcore-data
sudo chmod -R 755 /tmp/seedcore-data
print_status "OK" "Host data directory /tmp/seedcore-data ready"

# ---------- KubeRay operator ----------
print_status "INFO" "Installing/Upgrading KubeRay operator..."
helm repo add kuberay https://ray-project.github.io/kuberay-helm/ >/dev/null 2>&1 || true
helm repo update >/dev/null
if ! kubectl get namespace kuberay-system >/dev/null 2>&1; then
  helm install kuberay-operator kuberay/kuberay-operator \
    --namespace kuberay-system --create-namespace --wait
  print_status "OK" "KubeRay operator installed"
else
  if ! kubectl get pods -n kuberay-system -l app.kubernetes.io/name=kuberay-operator --no-headers | grep -q Running; then
    helm upgrade kuberay-operator kuberay/kuberay-operator --namespace kuberay-system --wait
  fi
  print_status "OK" "KubeRay operator is running"
fi

print_status "INFO" "Waiting for KubeRay operator to be ready..."
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=kuberay-operator -n kuberay-system --timeout=300s

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

# ---------- Deploy RayService (manages its own RayCluster) ----------
if [ ! -f "${RAYSERVICE_FILE}" ]; then
  print_status "ERROR" "RayService file '${RAYSERVICE_FILE}' not found. Set RAYSERVICE_FILE or pass as 4th arg."
  exit 1
fi

print_status "INFO" "Applying RayService from ${RAYSERVICE_FILE}..."
kubectl apply -n "${NAMESPACE}" -f "${RAYSERVICE_FILE}"

# ---------- Wait for RayService-managed head/worker pods ----------
print_status "INFO" "Confirming RayService exists..."
kubectl -n "${NAMESPACE}" get rayservice "${RS_NAME}"

print_status "INFO" "Waiting for RayService head pod to be created..."
for i in {1..120}; do
  COUNT=$(kubectl -n "${NAMESPACE}" get pods \
    -l "ray.io/node-type=head,ray.io/ray-service-name=${RS_NAME}" \
    --no-headers 2>/dev/null | wc -l)
  if [ "$COUNT" -ge 1 ]; then break; fi
  sleep 5
done
if [ "${COUNT:-0}" -lt 1 ]; then
  print_status "ERROR" "Head pod not created in time."
  kubectl -n "${NAMESPACE}" get rayservice "${RS_NAME}" -o yaml | sed -n '/^status:/,$p' | head -n 120 || true
  exit 1
fi

print_status "INFO" "Waiting for RayService head pod to be Ready..."
kubectl -n "${NAMESPACE}" wait --for=condition=ready pod \
  -l "ray.io/node-type=head,ray.io/ray-service-name=${RS_NAME}" --timeout=900s

# Optional: wait for at least one worker if replicas > 0
print_status "INFO" "Waiting for RayService worker pod(s) to be Ready (if any)..."
kubectl wait --for=condition=ready pod \
  -l "ray.io/node-type=worker,ray.io/cluster=${RS_NAME}" \
  -n "${NAMESPACE}" --timeout=600s || true

# Discover the generated RayCluster name
print_status "INFO" "Discovering generated RayCluster name..."
kubectl -n "${NAMESPACE}" get rayservice "${RS_NAME}" \
  -o jsonpath='{.status.activeServiceStatus.rayClusterName}{"\n"}{.status.pendingServiceStatus.rayClusterName}{"\n"}' || true

# ---------- Status & objects ----------
print_status "INFO" "RayService status (summary):"
kubectl -n "${NAMESPACE}" get rayservice "${RS_NAME}" -o yaml | sed -n '/^status:/,$p' | head -n 120 || true

print_status "INFO" "Pods (selector: ray.io/cluster=${RS_NAME}):"
kubectl get pods -n "${NAMESPACE}" -l ray.io/cluster="${RS_NAME}"

print_status "INFO" "Services (selector: ray.io/cluster=${RS_NAME}):"
kubectl get svc -n "${NAMESPACE}" -l ray.io/cluster="${RS_NAME}"

# ---------- Port-forward helpers ----------
HEAD_SVC="$(kubectl -n "${NAMESPACE}" get svc \
  -l ray.io/cluster="${RS_NAME}",ray.io/node-type=head \
  -o jsonpath='{.items[0].metadata.name}')"

if [ -n "${HEAD_SVC}" ]; then
  echo
  print_status "OK" "Head service detected: ${HEAD_SVC}"
  echo "🔌 Port-forward commands (run in separate terminals):"
  echo "  - Dashboard: kubectl -n ${NAMESPACE} port-forward svc/${HEAD_SVC} 8265:8265"
  echo "  - Serve HTTP: kubectl -n ${NAMESPACE} port-forward svc/${HEAD_SVC} 8001:8000"
  echo
  echo "🩺 Health check (if your Serve app exposes /health):"
  echo "  - curl -fsS http://127.0.0.1:8001/health || true"
else
  print_status "WARN" "No head service found via labels; verify RayService name (${RS_NAME}) and namespace (${NAMESPACE})."
fi

# ---------- Final summary ----------
echo
print_status "OK" "🎉 Kind + KubeRay operator + RayService (${RS_NAME}) deployed!"
echo
echo "📊 Cluster Info:"
echo "   - Kind Cluster: ${CLUSTER_NAME}"
echo "   - Namespace:    ${NAMESPACE}"
echo "   - RayService:   ${RS_NAME}"
echo "   - Image:        ${RAY_IMAGE}"
echo "   - Data Dir:     /tmp/seedcore-data (hostPath)"
echo
echo "🔧 Useful:"
echo "   - List pods:        kubectl get pods -n ${NAMESPACE} -w"
echo "   - RayService YAML:  kubectl -n ${NAMESPACE} get rayservice ${RS_NAME} -o yaml"
echo "   - Delete cluster:   kind delete cluster --name ${CLUSTER_NAME}"
