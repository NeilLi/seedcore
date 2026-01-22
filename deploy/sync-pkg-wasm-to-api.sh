#!/bin/bash
# Sync PKG WASM from database to seedcore-api pod
# This script extracts the compiled WASM from the database
# and copies it to the seedcore-api pod's expected location
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

usage() {
  echo "Usage: $0 [snapshot_id]"
  echo
  echo "Syncs compiled PKG WASM from database to seedcore-api pod."
  echo "Extracts WASM from pkg_snapshot_artifacts table using pkg_active_artifact view."
  echo
  echo "Arguments:"
  echo "  snapshot_id    Optional snapshot ID (default: active snapshot from pkg_active_artifact)"
  echo
  echo "Environment Variables:"
  echo "  NAMESPACE      Kubernetes namespace (default: seedcore-dev)"
  echo "  SECRET_NAME    Secret name (default: seedcore-env-secret)"
  echo "  PKG_ENV        PKG environment to query (default: prod)"
  echo "  SNAPSHOT_ID    Snapshot ID to use (overrides argument and PKG_ENV)"
  exit 1
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
fi

# Allow snapshot_id as first argument
if [ -n "${1:-}" ] && [[ "${1:-}" =~ ^[0-9]+$ ]]; then
  SNAPSHOT_ID="${1}"
fi

# ---------- Tool checks ----------
command -v kubectl >/dev/null || { print_status "ERROR" "kubectl is not installed."; exit 1; }

# ---------- Find Postgres pod ----------
print_status "INFO" "Finding Postgres pod in namespace ${NAMESPACE}..."
POSTGRES_POD=$(kubectl -n "${NAMESPACE}" get pods -l "app.kubernetes.io/name=postgresql" --no-headers 2>/dev/null | head -n1 | awk '{print $1}')

if [ -z "${POSTGRES_POD}" ]; then
  # Try alternative selectors
  POSTGRES_POD=$(kubectl -n "${NAMESPACE}" get pods --no-headers 2>/dev/null | awk '/^postgresql-|^postgres-/{print $1; exit}')
fi

if [ -z "${POSTGRES_POD}" ]; then
  print_status "ERROR" "No Postgres pod found in namespace ${NAMESPACE}"
  exit 1
fi

print_status "OK" "Found Postgres pod: ${POSTGRES_POD}"

# ---------- Extract WASM from database ----------
print_status "INFO" "Extracting WASM from database..."
# Query for active snapshot's WASM artifact using pkg_active_artifact view
PKG_ENV="${PKG_ENV:-prod}"
DB_NAME="${DB_NAME:-seedcore}"
DB_USER="${DB_USER:-postgres}"
SNAPSHOT_ID="${SNAPSHOT_ID:-}"

if [ -z "${SNAPSHOT_ID}" ]; then
  # Get active snapshot ID from pkg_active_artifact view, with fallbacks
  print_status "INFO" "Finding active snapshot for env=${PKG_ENV}..."
  
  # Try 1: Query pkg_active_artifact view for active snapshot
  SNAPSHOT_ID=$(kubectl exec -n "${NAMESPACE}" "${POSTGRES_POD}" -- \
    psql -U "${DB_USER}" -d "${DB_NAME}" -tAc "
      SELECT snapshot_id
      FROM pkg_active_artifact
      WHERE env = '${PKG_ENV}'
        AND artifact_type = 'wasm_pack'
      LIMIT 1;
    " 2>/dev/null | tr -d '[:space:]' || echo "")
  
  # Try 2: Check pkg_deployments for active deployment
  if [ -z "${SNAPSHOT_ID}" ]; then
    print_status "INFO" "Trying pkg_deployments fallback..."
    SNAPSHOT_ID=$(kubectl exec -n "${NAMESPACE}" "${POSTGRES_POD}" -- \
      psql -U "${DB_USER}" -d "${DB_NAME}" -tAc "
        SELECT DISTINCT d.snapshot_id
        FROM pkg_deployments d
        INNER JOIN pkg_snapshot_artifacts a ON a.snapshot_id = d.snapshot_id
        WHERE d.is_active = TRUE
          AND a.artifact_type = 'wasm_pack'
        ORDER BY d.snapshot_id DESC
        LIMIT 1;
      " 2>/dev/null | tr -d '[:space:]' || echo "")
  fi
  
  # Try 3: Fall back to latest snapshot with WASM artifact
  if [ -z "${SNAPSHOT_ID}" ]; then
    print_status "INFO" "Trying latest snapshot fallback..."
    SNAPSHOT_ID=$(kubectl exec -n "${NAMESPACE}" "${POSTGRES_POD}" -- \
      psql -U "${DB_USER}" -d "${DB_NAME}" -tAc "
        SELECT snapshot_id
        FROM pkg_snapshot_artifacts
        WHERE artifact_type = 'wasm_pack'
        ORDER BY snapshot_id DESC
        LIMIT 1;
      " 2>/dev/null | tr -d '[:space:]' || echo "")
  fi
fi

if [ -z "${SNAPSHOT_ID}" ]; then
  print_status "ERROR" "No snapshot with WASM artifact found"
  print_status "INFO" "Compile a snapshot first: POST /api/v1/pkg/snapshots/{id}/compile-rules"
  print_status "INFO" "Or check manually: SELECT * FROM pkg_snapshot_artifacts WHERE artifact_type = 'wasm_pack';"
  exit 1
fi

print_status "OK" "Found snapshot ID: ${SNAPSHOT_ID}"

# Extract WASM bytes from database and write to temp file in postgres pod
print_status "INFO" "Extracting WASM bytes from pkg_snapshot_artifacts table..."
TEMP_WASM="/tmp/policy_rules_sync_$(date +%s).wasm"

# Use psql to extract binary WASM - write via base64 to avoid binary issues
# -tAc: tuples only, aligned, no column names, single column
kubectl exec -n "${NAMESPACE}" "${POSTGRES_POD}" -- bash -c "
  psql -U '${DB_USER}' -d '${DB_NAME}' -tAc \"
    SELECT encode(artifact_bytes, 'base64')
    FROM pkg_snapshot_artifacts
    WHERE snapshot_id = ${SNAPSHOT_ID}
      AND artifact_type = 'wasm_pack'
    LIMIT 1;
  \" | tr -d '[:space:]' | base64 -d > '${TEMP_WASM}' 2>&1
" >/dev/null 2>&1

if [ $? -ne 0 ]; then
  print_status "ERROR" "Failed to extract WASM bytes from database"
  # Show error details
  kubectl exec -n "${NAMESPACE}" "${POSTGRES_POD}" -- bash -c "
    psql -U '${DB_USER}' -d '${DB_NAME}' -tAc \"
      SELECT encode(artifact_bytes, 'base64')
      FROM pkg_snapshot_artifacts
      WHERE snapshot_id = ${SNAPSHOT_ID}
        AND artifact_type = 'wasm_pack'
      LIMIT 1;
    \" | tr -d '[:space:]' | base64 -d > '${TEMP_WASM}' 2>&1
  " 2>&1 | head -n5 | while read line; do
    print_status "WARN" "  ${line}"
  done
  exit 1
fi

# Verify WASM file (check magic bytes: \0asm)
WASM_MAGIC=$(kubectl exec -n "${NAMESPACE}" "${POSTGRES_POD}" -- bash -c "
  if command -v od >/dev/null 2>&1; then
    od -An -tx1 -N4 '${TEMP_WASM}' 2>/dev/null | tr -d ' \n'
  elif command -v hexdump >/dev/null 2>&1; then
    hexdump -n 4 -e '1/1 \"%02x\"' '${TEMP_WASM}' 2>/dev/null
  else
    # Fallback: use head + printf
    head -c 4 '${TEMP_WASM}' 2>/dev/null | od -An -tx1 | tr -d ' \n'
  fi
" || echo "")

if [ "${WASM_MAGIC}" != "0061736d" ]; then
  print_status "WARN" "Extracted file does not appear to be valid WASM (magic bytes: ${WASM_MAGIC})"
  print_status "WARN" "Expected: 0061736d (\\0asm)"
  exit 1
fi

WASM_SIZE=$(kubectl exec -n "${NAMESPACE}" "${POSTGRES_POD}" -- stat -c%s "${TEMP_WASM}" 2>/dev/null || echo "unknown")
print_status "OK" "WASM extracted from database (${WASM_SIZE} bytes, magic: ${WASM_MAGIC})"

# ---------- Find seedcore-api pod ----------
print_status "INFO" "Finding seedcore-api pod in namespace ${NAMESPACE}..."
API_POD=$(kubectl -n "${NAMESPACE}" get pods -l "app=seedcore-api" --no-headers 2>/dev/null | head -n1 | awk '{print $1}')

if [ -z "${API_POD}" ]; then
  print_status "ERROR" "No seedcore-api pod found in namespace ${NAMESPACE}"
  exit 1
fi

print_status "OK" "Found seedcore-api pod: ${API_POD}"

# ---------- Copy WASM to seedcore-api pod ----------
print_status "INFO" "Copying WASM from ${POSTGRES_POD} to ${API_POD}..."

# Copy from postgres pod to local temp
LOCAL_TEMP=$(mktemp)
kubectl cp "${NAMESPACE}/${POSTGRES_POD}:${TEMP_WASM}" "${LOCAL_TEMP}"

# Copy from local to seedcore-api pod
kubectl exec -n "${NAMESPACE}" "${API_POD}" -- mkdir -p /app/data/opt/pkg
kubectl cp "${LOCAL_TEMP}" "${NAMESPACE}/${API_POD}:/app/data/opt/pkg/policy_rules.wasm"

# Cleanup
kubectl exec -n "${NAMESPACE}" "${POSTGRES_POD}" -- rm -f "${TEMP_WASM}"
rm -f "${LOCAL_TEMP}"

print_status "OK" "WASM file copied to seedcore-api pod"

# ---------- Verify WASM file in seedcore-api pod ----------
print_status "INFO" "Verifying WASM file in seedcore-api pod..."
if kubectl exec -n "${NAMESPACE}" "${API_POD}" -- test -f /app/data/opt/pkg/policy_rules.wasm 2>/dev/null; then
  API_WASM_SIZE=$(kubectl exec -n "${NAMESPACE}" "${API_POD}" -- stat -c%s /app/data/opt/pkg/policy_rules.wasm 2>/dev/null)
  API_WASM_MAGIC=$(kubectl exec -n "${NAMESPACE}" "${API_POD}" -- bash -c "
    if command -v od >/dev/null 2>&1; then
      od -An -tx1 -N4 /app/data/opt/pkg/policy_rules.wasm 2>/dev/null | tr -d ' \n'
    elif command -v hexdump >/dev/null 2>&1; then
      hexdump -n 4 -e '1/1 \"%02x\"' /app/data/opt/pkg/policy_rules.wasm 2>/dev/null
    else
      head -c 4 /app/data/opt/pkg/policy_rules.wasm 2>/dev/null | od -An -tx1 | tr -d ' \n'
    fi
  " || echo "")
  
  if [ "${API_WASM_MAGIC}" = "0061736d" ]; then
    print_status "OK" "WASM file verified in seedcore-api pod (${API_WASM_SIZE} bytes, magic: ${API_WASM_MAGIC})"
  else
    print_status "WARN" "WASM file exists but magic bytes don't match (${API_WASM_MAGIC})"
  fi
else
  print_status "ERROR" "WASM file not found in seedcore-api pod"
  exit 1
fi

# ---------- Update PKG_WASM_PATH in secret (if needed) ----------
print_status "INFO" "Ensuring PKG_WASM_PATH is set in secret..."
kubectl get secret "${SECRET_NAME}" -n "${NAMESPACE}" -o json 2>/dev/null | \
  jq --arg val "$(echo -n '/app/data/opt/pkg/policy_rules.wasm' | base64)" \
     '.data.PKG_WASM_PATH = $val' | \
  kubectl apply -f - >/dev/null 2>&1 || print_status "WARN" "Could not update PKG_WASM_PATH (secret may not exist)"

print_status "OK" "PKG_WASM_PATH configured"

# ---------- Final summary ----------
echo
print_status "OK" "🎉 PKG WASM sync complete!"
echo
echo "📦 Next Steps:"
echo "   - Restart seedcore-api pod to reload: kubectl delete pod -n ${NAMESPACE} ${API_POD}"
echo "   - Or wait for next evaluation cycle"
echo "   - Verify: kubectl exec -n ${NAMESPACE} ${API_POD} -- file /app/data/opt/pkg/policy_rules.wasm"
echo "   - Check PKG status: kubectl exec -n ${NAMESPACE} ${API_POD} -- curl -s http://localhost:8002/health | jq .pkg"
