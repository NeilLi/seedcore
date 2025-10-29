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
RAY_IMAGE="${RAY_IMAGE:-seedcore:latest}"   # your image (already built locally)
WORKER_REPLICAS="${WORKER_REPLICAS:-1}"

# RayService bits
RAYSERVICE_FILE="${RAYSERVICE_FILE:-rayservice.yaml}"  # path to your RayService YAML
RS_NAME="${RS_NAME:-seedcore-svc}"                      # metadata.name inside rayservice.yaml
# ✅ ADDED: Path to your new stable service definition
STABLE_SERVE_SVC_FILE="${STABLE_SERVE_SVC_FILE:-ray-stable-svc.yaml}"

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

# ---------- PKG WASM Path Fix ----------
print_status "INFO" "Configuring PKG WASM path in secret..."
# Update PKG_WASM_PATH to point to accessible location in Ray pods (using writable /app/data mount)
kubectl get secret "${SECRET_NAME}" -n "${NAMESPACE}" -o json 2>/dev/null | \
  jq --arg val "$(echo -n '/app/data/opt/pkg/policy_rules.wasm' | base64)" \
     '.data.PKG_WASM_PATH = $val' | \
  kubectl apply -f - >/dev/null 2>&1 || print_status "WARN" "Could not update PKG_WASM_PATH (secret may not exist yet)"
print_status "OK" "PKG WASM path configured"

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
    -l "ray.io/node-type=head" \
    --no-headers 2>/dev/null | grep -c "${RS_NAME}" || echo "0")
  if [ "$COUNT" -ge 1 ]; then break; fi
  sleep 5
done
if [ "${COUNT:-0}" -lt 1 ]; then
  print_status "ERROR" "Head pod not created in time."
  kubectl -n "${NAMESPACE}" get rayservice "${RS_NAME}" -o yaml | sed -n '/^status:/,$p' | head -n 120 || true
  exit 1
fi

print_status "INFO" "Waiting for RayService head pod to be Ready..."
# Get the actual cluster name from the pod labels
CLUSTER_NAME_FROM_POD=$(kubectl -n "${NAMESPACE}" get pods \
  -l "ray.io/node-type=head" \
  --no-headers | grep "${RS_NAME}" | head -n1 | awk '{print $1}' | sed 's/-head-.*$//')
if [ -n "${CLUSTER_NAME_FROM_POD}" ]; then
  kubectl -n "${NAMESPACE}" wait --for=condition=ready pod \
    -l "ray.io/node-type=head,ray.io/cluster=${CLUSTER_NAME_FROM_POD}" --timeout=900s
else
  print_status "ERROR" "Could not determine cluster name from pods"
  exit 1
fi

# ---------- Setup PKG WASM File ----------
print_status "INFO" "Setting up PKG WASM file in Ray head pod..."
HEAD_POD=$(kubectl -n "${NAMESPACE}" get pods -l "ray.io/node-type=head" --no-headers | head -n1 | awk '{print $1}')
if [ -n "${HEAD_POD}" ]; then
  # Wait for Ray services to be fully ready before attempting file operations
  print_status "INFO" "Waiting for Ray services to be fully ready (30s)..."
  sleep 30
  
  # Retry logic for WASM file creation
  WASM_CREATED=false
  for attempt in 1 2 3; do
    print_status "INFO" "Creating PKG WASM file (attempt $attempt/3)..."
    
    if kubectl exec -n "${NAMESPACE}" "${HEAD_POD}" -- bash -c '
      mkdir -p /app/data/opt/pkg
      cat > /app/data/opt/pkg/policy_rules.wasm << "WASM_EOF"
# Dummy PKG WASM for testing
# Version: rules@1.3.0+ontology@0.9.1
# This is a placeholder - replace with real WASM binary in production
# To replace: kubectl cp policy_rules.wasm <namespace>/<head-pod>:/app/data/opt/pkg/policy_rules.wasm
WASM_EOF
      chmod 644 /app/data/opt/pkg/policy_rules.wasm
      echo "PKG WASM placeholder created at /app/data/opt/pkg/policy_rules.wasm"
    '; then
      WASM_CREATED=true
      break
    else
      print_status "WARN" "Attempt $attempt failed - pod may not be ready yet"
      if [ $attempt -lt 3 ]; then
        sleep 15
      fi
    fi
  done
  
  # Verify WASM file creation
  if [ "$WASM_CREATED" = true ] && kubectl exec -n "${NAMESPACE}" "${HEAD_POD}" -- test -f /app/data/opt/pkg/policy_rules.wasm; then
    WASM_SIZE=$(kubectl exec -n "${NAMESPACE}" "${HEAD_POD}" -- stat -c%s /app/data/opt/pkg/policy_rules.wasm 2>/dev/null || echo "unknown")
    print_status "OK" "PKG WASM placeholder created (${WASM_SIZE} bytes) - replace with real WASM for production"
  else
    print_status "WARN" "PKG WASM file not created - coordinator will report PKG as not loaded"
    print_status "INFO" "Troubleshooting: Check pod logs with 'kubectl logs -n ${NAMESPACE} ${HEAD_POD}'"
  fi
else
  print_status "WARN" "Could not find Ray head pod to setup PKG WASM"
fi

# Optional: wait for at least one worker if replicas > 0
print_status "INFO" "Waiting for RayService worker pod(s) to be Ready (if any)..."
if [ -n "${CLUSTER_NAME_FROM_POD}" ]; then
  kubectl wait --for=condition=ready pod \
    -l "ray.io/node-type=worker,ray.io/cluster=${CLUSTER_NAME_FROM_POD}" \
    -n "${NAMESPACE}" --timeout=600s || true
fi

# ✅ ADDED: ---------- Deploy user-managed stable Serve Service ----------
if [ -f "${STABLE_SERVE_SVC_FILE}" ]; then
  print_status "INFO" "Applying stable Serve Service from ${STABLE_SERVE_SVC_FILE}..."
  kubectl apply -n "${NAMESPACE}" -f "${STABLE_SERVE_SVC_FILE}"
else
  print_status "WARN" "Stable Serve Service file '${STABLE_SERVE_SVC_FILE}' not found. Skipping."
fi


# Discover the generated RayCluster name
print_status "INFO" "Discovering generated RayCluster name..."
kubectl -n "${NAMESPACE}" get rayservice "${RS_NAME}" \
  -o jsonpath='{.status.activeServiceStatus.rayClusterName}{"\n"}{.status.pendingServiceStatus.rayClusterName}{"\n"}' || true

# ---------- Status & objects ----------
print_status "INFO" "RayService status (summary):"
kubectl -n "${NAMESPACE}" get rayservice "${RS_NAME}" -o yaml | sed -n '/^status:/,$p' | head -n 120 || true

print_status "INFO" "Pods (selector: ray.io/cluster=${CLUSTER_NAME_FROM_POD}):"
kubectl get pods -n "${NAMESPACE}" -l ray.io/cluster="${CLUSTER_NAME_FROM_POD}"

print_status "INFO" "Services (selector: ray.io/cluster=${CLUSTER_NAME_FROM_POD}):"
kubectl get svc -n "${NAMESPACE}" -l ray.io/cluster="${CLUSTER_NAME_FROM_POD}"

# ✅ UPDATED: --- Discover Services ---
# The operator creates these services automatically
OPERATOR_HEAD_SVC="${RS_NAME}-head-svc"
OPERATOR_SERVE_SVC="${RS_NAME}-serve-svc" # This one has the selector issue

# This is our user-managed, truly stable service. The name comes from your serve-svc.yaml
USER_STABLE_SERVE_SVC="seedcore-svc-serve-svc"

# For dashboard and client, the operator-managed head service is fine
if kubectl -n "${NAMESPACE}" get svc "${OPERATOR_HEAD_SVC}" >/dev/null 2>&1; then
  HEAD_SVC="${OPERATOR_HEAD_SVC}"
else
  # Fallback: cluster-specific head svc (during early init)
  HEAD_SVC="$(kubectl -n "${NAMESPACE}" get svc \
    -l "ray.io/cluster=${CLUSTER_NAME_FROM_POD}",ray.io/node-type=head \
    -o jsonpath='{.items[0].metadata.name}')"
fi

echo
print_status "OK" "Head service (for dashboard/client): ${HEAD_SVC}"
print_status "WARN" "Operator-managed Serve service (unstable selector): ${OPERATOR_SERVE_SVC}"
print_status "OK" "User-managed stable Serve service (recommended): ${USER_STABLE_SERVE_SVC}"

# ✅ UPDATED: --- Port-forwards ---
echo "🔌 Port-forward (run in separate terminals):"
echo "  - Dashboard: kubectl -n ${NAMESPACE} port-forward svc/${HEAD_SVC} 8265:8265"
echo "  - Ray Client: kubectl -n ${NAMESPACE} port-forward svc/${HEAD_SVC} 10001:10001"
echo "  - Serve HTTP (use the stable service): kubectl -n ${NAMESPACE} port-forward svc/${USER_STABLE_SERVE_SVC} 8000:8000"

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
echo "   - Stable Serve SVC: kubectl -n ${NAMESPACE} describe svc ${USER_STABLE_SERVE_SVC}"
echo "   - Delete cluster:   kind delete cluster --name ${CLUSTER_NAME}"
echo
echo "📦 PKG Configuration:"
echo "   - Check PKG status: kubectl -n ${NAMESPACE} port-forward svc/${USER_STABLE_SERVE_SVC} 8000:8000"
echo "                       curl http://localhost:8000/pipeline/health | jq .pkg"
echo "   - Replace dummy WASM with real binary:"
echo "                       kubectl cp policy_rules.wasm ${NAMESPACE}/${HEAD_POD}:/app/data/opt/pkg/policy_rules.wasm"
echo "                       kubectl delete pod -n ${NAMESPACE} -l ray.io/node-type=head  # Restart to reload"