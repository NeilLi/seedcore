#!/usr/bin/env bash
# Local host-mode gate for runtime RCT audit generation plus verification API reads.

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

cd "${PROJECT_ROOT}"

source "${SCRIPT_DIR}/host-env.sh"

API_BASE="${SEEDCORE_API:-${SEEDCORE_API_URL}}"
RUNTIME_API_BASE="${SEEDCORE_RUNTIME_API_BASE:-${API_BASE}/api/v1}"
VERIFICATION_API_BASE="${SEEDCORE_VERIFICATION_API_BASE:-http://127.0.0.1:7071}"

require_ready() {
  local name="$1"
  local url="$2"
  local hint="$3"

  if curl -fsS "${url}" >/dev/null 2>&1; then
    return 0
  fi

  echo "[FAIL] ${name} is not reachable at ${url}" >&2
  echo "       Start it with: ${hint}" >&2
  return 1
}

require_ready "SeedCore API" "${API_BASE}/health" "bash deploy/local/run-api.sh"
require_ready "verification API" "${VERIFICATION_API_BASE}/health" "bash deploy/local/run-verification-api.sh"

SEEDCORE_API="${API_BASE}" \
SEEDCORE_RUNTIME_API_BASE="${RUNTIME_API_BASE}" \
SEEDCORE_VERIFICATION_API_BASE="${VERIFICATION_API_BASE}" \
bash scripts/host/verify_runtime_rct_audit_surface.sh
