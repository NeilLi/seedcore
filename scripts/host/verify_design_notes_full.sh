#!/usr/bin/env bash
# Full local design-notes verification gate.
# Runs the default host regression bundle plus additional design-note invariant checks.

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

VERIFICATION_API_BASE="${SEEDCORE_VERIFICATION_API_BASE:-http://127.0.0.1:7071}"
DESIGN_NOTES_SKIP_Q2_CONTRACTS="${SEEDCORE_SKIP_Q2_CONTRACT_GATE:-0}"
DESIGN_NOTES_SKIP_GATEWAY_REAL_CALLS="${SEEDCORE_SKIP_AGENT_ACTION_GATEWAY_GATE:-0}"
DESIGN_NOTES_SKIP_PRODUCTIZED_SURFACE="${SEEDCORE_SKIP_PRODUCTIZED_SURFACE_GATE:-0}"

VERIFY_API_PID=""
VERIFY_API_STARTED=0

cleanup() {
  if [[ "${VERIFY_API_STARTED}" == "1" && -n "${VERIFY_API_PID}" ]]; then
    if kill -0 "${VERIFY_API_PID}" >/dev/null 2>&1; then
      kill "${VERIFY_API_PID}" >/dev/null 2>&1 || true
      wait "${VERIFY_API_PID}" >/dev/null 2>&1 || true
    fi
  fi
}
trap cleanup EXIT

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[FAIL] missing required binary: $1" >&2
    exit 1
  fi
}

maybe_start_verification_api() {
  if curl -fsS "${VERIFICATION_API_BASE}/health" >/dev/null 2>&1; then
    return 0
  fi

  if [[ ! "${VERIFICATION_API_BASE}" =~ ^http://127\.0\.0\.1:[0-9]+$ ]]; then
    echo "[FAIL] verification API is unavailable at ${VERIFICATION_API_BASE} and auto-start only supports local 127.0.0.1 base." >&2
    return 1
  fi

  local port tsx_bin log_file
  port="$(printf '%s\n' "${VERIFICATION_API_BASE}" | sed -E 's#^http://127\.0\.0\.1:([0-9]+)$#\1#')"
  tsx_bin="${PROJECT_ROOT}/ts/node_modules/.bin/tsx"
  log_file="${PROJECT_ROOT}/.local-runtime/verification-api-design-notes.log"

  if [[ ! -x "${tsx_bin}" ]]; then
    echo "[FAIL] missing tsx binary at ${tsx_bin}. Run: cd ts && npm ci" >&2
    return 1
  fi

  mkdir -p "${PROJECT_ROOT}/.local-runtime"
  (
    cd "${PROJECT_ROOT}/ts/services/verification-api"
    PORT="${port}" "${tsx_bin}" src/server.ts >"${log_file}" 2>&1
  ) &
  VERIFY_API_PID="$!"
  VERIFY_API_STARTED=1

  for _ in $(seq 1 60); do
    if curl -fsS "${VERIFICATION_API_BASE}/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done

  echo "[FAIL] verification API did not become ready at ${VERIFICATION_API_BASE}. See ${log_file}" >&2
  return 1
}

run_step() {
  local title="$1"
  shift
  echo
  echo "==> ${title}"
  "$@"
}

cd "${PROJECT_ROOT}"
source .venv/bin/activate

require_bin curl

run_step "Host regression baseline" bash scripts/host/verify_host_regression.sh
run_step "PDP deterministic boundary policy matrix" bash scripts/host/verify_pdp_boundary.sh
run_step "Governed execution spine" bash scripts/host/verify_execution_spine.sh
run_step "Evidence contracts" bash scripts/host/verify_evidence_contracts.sh
run_step "Admission contract inventory" bash scripts/host/verify_admission_contract_inventory.sh
run_step "Delegated ingress non-bypass boundary" bash scripts/host/verify_kafka_ingress_non_bypass.sh

if [[ "${DESIGN_NOTES_SKIP_GATEWAY_REAL_CALLS}" != "1" ]]; then
  run_step "Agent Action Gateway productized real-calls" bash scripts/host/verify_agent_action_gateway_productization_real_calls.sh --strict-replay-ready
fi

if [[ "${DESIGN_NOTES_SKIP_PRODUCTIZED_SURFACE}" != "1" ]]; then
  maybe_start_verification_api
  run_step "Productized verification surface protocol" bash scripts/host/verify_productized_surface.sh
fi

if [[ "${DESIGN_NOTES_SKIP_Q2_CONTRACTS}" != "1" ]]; then
  run_step "Q2 verification contracts gate" bash scripts/host/verify_q2_verification_contracts.sh
fi

echo
echo "Design-notes full verification gate passed."
