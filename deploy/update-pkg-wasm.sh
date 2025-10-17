#!/bin/bash
# Helper script to update PKG WASM file in running Ray deployment
set -euo pipefail

# ---------- Pretty printing ----------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
print_status() {
  local status=$1; local message=$2
  if [ "$status" = "OK" ]; then echo -e "${GREEN}✅ $message${NC}"
  elif [ "$status" = "WARN" ]; then echo -e "${YELLOW}⚠️  $message${NC}"
  elif [ "$status" = "INFO" ]; then echo -e "${BLUE}ℹ️  $message${NC}"
  else echo -e "${RED}❌ $message${NC}"; fi
}

# ---------- Config ----------
NAMESPACE="${NAMESPACE:-seedcore-dev}"
SECRET_NAME="${SECRET_NAME:-seedcore-env-secret}"
WASM_FILE="${1:-}"

usage() {
  echo "Usage: $0 [wasm_file]"
  echo
  echo "Updates PKG WASM file in the Ray deployment."
  echo
  echo "Options:"
  echo "  wasm_file    Path to PKG WASM binary file (optional, creates dummy if not provided)"
  echo
  echo "Environment Variables:"
  echo "  NAMESPACE    Kubernetes namespace (default: seedcore-dev)"
  echo "  SECRET_NAME  Secret name (default: seedcore-env-secret)"
  echo
  echo "Examples:"
  echo "  # Create/update with dummy WASM (for testing)"
  echo "  $0"
  echo
  echo "  # Update with real WASM binary"
  echo "  $0 /path/to/policy_rules.wasm"
  exit 1
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
fi

# ---------- Tool checks ----------
command -v kubectl >/dev/null || { print_status "ERROR" "kubectl is not installed."; exit 1; }
command -v jq >/dev/null || { print_status "ERROR" "jq is not installed."; exit 1; }

# ---------- Find Ray head pod ----------
print_status "INFO" "Finding Ray head pod in namespace ${NAMESPACE}..."
HEAD_POD=$(kubectl -n "${NAMESPACE}" get pods -l "ray.io/node-type=head" --no-headers 2>/dev/null | head -n1 | awk '{print $1}')

if [ -z "${HEAD_POD}" ]; then
  print_status "ERROR" "No Ray head pod found in namespace ${NAMESPACE}"
  exit 1
fi

print_status "OK" "Found Ray head pod: ${HEAD_POD}"

# ---------- Update PKG_WASM_PATH in secret ----------
print_status "INFO" "Updating PKG_WASM_PATH in secret ${SECRET_NAME}..."
kubectl get secret "${SECRET_NAME}" -n "${NAMESPACE}" -o json 2>/dev/null | \
  jq --arg val "$(echo -n '/app/opt/pkg/policy_rules.wasm' | base64)" \
     '.data.PKG_WASM_PATH = $val' | \
  kubectl apply -f - >/dev/null

print_status "OK" "Secret updated with PKG_WASM_PATH=/app/opt/pkg/policy_rules.wasm"

# ---------- Upload or create WASM file ----------
if [ -n "${WASM_FILE}" ]; then
  # Real WASM file provided
  if [ ! -f "${WASM_FILE}" ]; then
    print_status "ERROR" "WASM file not found: ${WASM_FILE}"
    exit 1
  fi
  
  print_status "INFO" "Uploading WASM file ${WASM_FILE} to ${HEAD_POD}..."
  kubectl exec -n "${NAMESPACE}" "${HEAD_POD}" -- mkdir -p /app/opt/pkg
  kubectl cp "${WASM_FILE}" "${NAMESPACE}/${HEAD_POD}:/app/opt/pkg/policy_rules.wasm"
  
  WASM_SIZE=$(kubectl exec -n "${NAMESPACE}" "${HEAD_POD}" -- stat -c%s /app/opt/pkg/policy_rules.wasm 2>/dev/null || echo "unknown")
  print_status "OK" "WASM file uploaded (${WASM_SIZE} bytes)"
else
  # Create dummy WASM
  print_status "INFO" "Creating dummy WASM placeholder in ${HEAD_POD}..."
  kubectl exec -n "${NAMESPACE}" "${HEAD_POD}" -- bash -c '
    mkdir -p /app/opt/pkg
    cat > /app/opt/pkg/policy_rules.wasm << "WASM_EOF"
# Dummy PKG WASM for testing
# Version: rules@1.3.0+ontology@0.9.1
# This is a placeholder - replace with real WASM binary in production
# To replace: kubectl cp policy_rules.wasm seedcore-dev/<head-pod>:/app/opt/pkg/policy_rules.wasm
WASM_EOF
    chmod 644 /app/opt/pkg/policy_rules.wasm
  '
  print_status "OK" "Dummy WASM placeholder created"
  print_status "WARN" "Using dummy WASM - replace with real binary for production"
fi

# ---------- Verify WASM file ----------
print_status "INFO" "Verifying WASM file..."
if kubectl exec -n "${NAMESPACE}" "${HEAD_POD}" -- test -f /app/opt/pkg/policy_rules.wasm 2>/dev/null; then
  WASM_SIZE=$(kubectl exec -n "${NAMESPACE}" "${HEAD_POD}" -- stat -c%s /app/opt/pkg/policy_rules.wasm 2>/dev/null)
  print_status "OK" "WASM file exists: /app/opt/pkg/policy_rules.wasm (${WASM_SIZE} bytes)"
else
  print_status "ERROR" "WASM file not found in pod"
  exit 1
fi

# ---------- Restart Ray head pod to reload ----------
print_status "INFO" "Restarting Ray head pod to reload PKG..."
kubectl delete pod -n "${NAMESPACE}" "${HEAD_POD}"

print_status "INFO" "Waiting for new head pod to be ready..."
sleep 5
kubectl wait --for=condition=ready pod -l ray.io/node-type=head -n "${NAMESPACE}" --timeout=300s

NEW_HEAD_POD=$(kubectl -n "${NAMESPACE}" get pods -l "ray.io/node-type=head" --no-headers | head -n1 | awk '{print $1}')
print_status "OK" "New head pod ready: ${NEW_HEAD_POD}"

# ---------- Wait for coordinator to be ready ----------
print_status "INFO" "Waiting for coordinator to be ready (this may take 30-60s)..."
sleep 45

# ---------- Verify PKG status ----------
print_status "INFO" "Checking PKG status via health endpoint..."

# Try to get PKG status
PKG_STATUS=$(kubectl exec -n "${NAMESPACE}" "${NEW_HEAD_POD}" -- curl -s http://localhost:8000/pipeline/health 2>/dev/null | jq -r '.pkg.loaded' 2>/dev/null || echo "unknown")

if [ "${PKG_STATUS}" = "true" ]; then
  print_status "OK" "PKG successfully loaded!"
  kubectl exec -n "${NAMESPACE}" "${NEW_HEAD_POD}" -- curl -s http://localhost:8000/pipeline/health 2>/dev/null | jq '.pkg'
elif [ "${PKG_STATUS}" = "false" ]; then
  print_status "ERROR" "PKG not loaded - check coordinator logs"
  kubectl exec -n "${NAMESPACE}" "${NEW_HEAD_POD}" -- curl -s http://localhost:8000/pipeline/health 2>/dev/null | jq '.pkg'
  echo
  echo "Troubleshooting:"
  echo "  1. Check coordinator logs: kubectl logs -n ${NAMESPACE} ${NEW_HEAD_POD} | grep -i pkg"
  echo "  2. Verify WASM path: kubectl exec -n ${NAMESPACE} ${NEW_HEAD_POD} -- ls -lh /app/opt/pkg/policy_rules.wasm"
  echo "  3. Check env var: kubectl exec -n ${NAMESPACE} ${NEW_HEAD_POD} -- env | grep PKG_WASM_PATH"
  exit 1
else
  print_status "WARN" "Could not determine PKG status (coordinator may still be starting)"
  echo "Check manually with:"
  echo "  kubectl -n ${NAMESPACE} port-forward svc/seedcore-svc-serve-svc 8000:8000"
  echo "  curl http://localhost:8000/pipeline/health | jq .pkg"
fi

# ---------- Final summary ----------
echo
print_status "OK" "🎉 PKG WASM update complete!"
echo
echo "📦 Next Steps:"
echo "   - Port-forward: kubectl -n ${NAMESPACE} port-forward svc/seedcore-svc-serve-svc 8000:8000"
echo "   - Check status:  curl http://localhost:8000/pipeline/health | jq .pkg"
echo "   - Test HGNN:     curl -X POST http://localhost:8002/api/v1/tasks \\"
echo "                      -H 'Content-Type: application/json' \\"
echo "                      -d '{\"type\":\"general_query\",\"description\":\"test\",\"params\":{\"ocps\":{\"S_t\":1.0,\"h\":1.0,\"h_clr\":0.5,\"flag_on\":true},\"kappa\":0.7,\"criticality\":0.7},\"run_immediately\":true}'"

