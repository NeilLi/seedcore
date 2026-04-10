#!/usr/bin/env bash
# Deployment-realistic kube verification lane for Q2/Q3 gate validation.
# This script validates aligned runtime gates, runs optional degraded drills,
# captures benchmark + baseline artifacts, and emits a topology signoff report.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

NAMESPACE="${NAMESPACE:-seedcore-dev}"
RUNTIME_LOCAL_PORT="${SEEDCORE_RUNTIME_LOCAL_PORT:-8002}"
RUNTIME_API_BASE="${SEEDCORE_RUNTIME_API_BASE:-http://127.0.0.1:${RUNTIME_LOCAL_PORT}/api/v1}"
RUNTIME_HEALTH_URL="${SEEDCORE_RUNTIME_HEALTH_URL:-http://127.0.0.1:${RUNTIME_LOCAL_PORT}/health}"
RUNTIME_READYZ_URL="${SEEDCORE_RUNTIME_READYZ_URL:-http://127.0.0.1:${RUNTIME_LOCAL_PORT}/readyz}"
VERIFICATION_API_BASE="${SEEDCORE_VERIFICATION_API_BASE:-http://127.0.0.1:7071}"
PLUGIN_INFO_URL="${SEEDCORE_PLUGIN_INFO_URL:-}"
REPORT_DIR="${SEEDCORE_KUBE_VERIFY_REPORT_DIR:-${ROOT}/.local-runtime/kube_topology}"
RUN_DEGRADED_DRILLS="${SEEDCORE_RUN_DEGRADED_DRILLS:-1}"
RUN_REDIS_DEPENDENCY_DRILL="${SEEDCORE_RUN_REDIS_DEPENDENCY_DRILL:-1}"
RUN_BENCHMARK_BASELINE="${SEEDCORE_RUN_BENCHMARK_BASELINE:-1}"
ENFORCE_Q3_GATE="${SEEDCORE_ENFORCE_Q3_GATE:-0}"
ENABLE_PORT_FORWARD="${SEEDCORE_ENABLE_PORT_FORWARD:-1}"
BENCH_REQUESTS="${SEEDCORE_BENCH_REQUESTS:-40}"
BENCH_WARMUP="${SEEDCORE_BENCH_WARMUP:-4}"
BENCH_CONCURRENCY="${SEEDCORE_BENCH_CONCURRENCY:-4}"
PORT_FORWARD_LOG="${SEEDCORE_KUBE_PORT_FORWARD_LOG:-${ROOT}/.local-runtime/kube_topology/seedcore_api_port_forward.log}"

PORT_FORWARD_PID=""

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[FAIL] missing required binary: $1" >&2
    exit 1
  fi
}

is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|y|Y|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

status_code() {
  local url="$1"
  curl -sS -o /dev/null -w "%{http_code}" "$url" || true
}

wait_for_status() {
  local url="$1"
  local expected="$2"
  local attempts="${3:-45}"
  local i
  for ((i=0; i<attempts; i+=1)); do
    if [[ "$(status_code "${url}")" == "${expected}" ]]; then
      return 0
    fi
    sleep 1
  done
  return 1
}

latest_json_path() {
  local dir="$1"
  if [[ ! -d "${dir}" ]]; then
    return 0
  fi
  ls -1t "${dir}"/*.json 2>/dev/null | head -n 1 || true
}

cleanup() {
  if [[ -n "${PORT_FORWARD_PID}" ]]; then
    kill "${PORT_FORWARD_PID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

start_port_forward_if_needed() {
  if [[ "$(status_code "${RUNTIME_HEALTH_URL}")" == "200" ]]; then
    return 0
  fi
  if ! is_true "${ENABLE_PORT_FORWARD}"; then
    echo "[FAIL] runtime endpoint ${RUNTIME_HEALTH_URL} is unreachable and SEEDCORE_ENABLE_PORT_FORWARD=0" >&2
    exit 1
  fi

  require_bin kubectl
  mkdir -p "$(dirname "${PORT_FORWARD_LOG}")"
  echo "Starting kube port-forward for seedcore-api on :${RUNTIME_LOCAL_PORT}..."
  kubectl -n "${NAMESPACE}" port-forward svc/seedcore-api "${RUNTIME_LOCAL_PORT}:8002" >"${PORT_FORWARD_LOG}" 2>&1 &
  PORT_FORWARD_PID="$!"

  if ! wait_for_status "${RUNTIME_HEALTH_URL}" "200" 45; then
    echo "[FAIL] could not reach runtime /health after starting port-forward" >&2
    echo "--- port-forward log ---" >&2
    tail -n 80 "${PORT_FORWARD_LOG}" >&2 || true
    exit 1
  fi
}

probe_verification_api() {
  local code
  code="$(status_code "${VERIFICATION_API_BASE}/api/v1/verification/transfers/status?source=fixture&dir=rust/fixtures/transfers/allow_case")"
  [[ "${code}" == "200" ]]
}

build_report() {
  local status_json="$1"
  local observability_ok="$2"
  local redis_drill_ok="$3"
  local benchmark_path="$4"
  local baseline_path="$5"
  local verification_api_available="$6"
  local plugin_bundle_json="$7"

  local benchmark_payload="{}"
  local benchmark_error_count=0
  local benchmark_mismatch_count=0
  local benchmark_graph_freshness_ok=true
  local benchmark_authz_graph_ready=true

  if [[ -n "${benchmark_path}" && -f "${benchmark_path}" ]]; then
    benchmark_payload="$(cat "${benchmark_path}")"
    benchmark_error_count="$(jq -r '.error_count // 0' <<<"${benchmark_payload}")"
    benchmark_mismatch_count="$(jq -r '.mismatch_count // 0' <<<"${benchmark_payload}")"
    benchmark_graph_freshness_ok="$(jq -r '.graph_freshness_ok // false' <<<"${benchmark_payload}")"
    benchmark_authz_graph_ready="$(jq -r '.authz_graph_ready // false' <<<"${benchmark_payload}")"
  fi

  local runtime_ready authz_graph_ready graph_freshness_ok
  runtime_ready="$(jq -r '.runtime_ready // false' <<<"${status_json}")"
  authz_graph_ready="$(jq -r '.authz_graph_ready // false' <<<"${status_json}")"
  graph_freshness_ok="$(jq -r '.graph_freshness_ok // false' <<<"${status_json}")"

  local q3_ready=true
  local reasons=()
  if [[ "${runtime_ready}" != "true" ]]; then
    q3_ready=false
    reasons+=("runtime_not_ready")
  fi
  if [[ "${authz_graph_ready}" != "true" ]]; then
    q3_ready=false
    reasons+=("authz_graph_not_ready")
  fi
  if [[ "${graph_freshness_ok}" != "true" ]]; then
    q3_ready=false
    reasons+=("graph_not_fresh")
  fi
  if [[ "${observability_ok}" != "true" ]]; then
    q3_ready=false
    reasons+=("observability_gate_failed")
  fi
  if [[ "${redis_drill_ok}" != "true" ]]; then
    q3_ready=false
    reasons+=("redis_drill_failed")
  fi
  if [[ "${benchmark_error_count}" != "0" ]]; then
    q3_ready=false
    reasons+=("benchmark_errors_present")
  fi
  if [[ "${benchmark_mismatch_count}" != "0" ]]; then
    q3_ready=false
    reasons+=("benchmark_mismatch_present")
  fi
  if [[ "${benchmark_graph_freshness_ok}" != "true" ]]; then
    q3_ready=false
    reasons+=("benchmark_graph_not_fresh")
  fi
  if [[ "${benchmark_authz_graph_ready}" != "true" ]]; then
    q3_ready=false
    reasons+=("benchmark_authz_graph_not_ready")
  fi

  local safe_tools_json
  safe_tools_json="$(
    VERIFICATION_API_AVAILABLE="${verification_api_available}" \
    PLUGIN_BUNDLE_JSON="${plugin_bundle_json}" \
    python3 - <<'PY'
import json
import os

verification_available = os.environ.get("VERIFICATION_API_AVAILABLE", "false").lower() == "true"
plugin_bundle_raw = os.environ.get("PLUGIN_BUNDLE_JSON", "").strip()

if plugin_bundle_raw:
    try:
        payload = json.loads(plugin_bundle_raw)
    except Exception:
        payload = {}
else:
    payload = {}

live_bundle = payload.get("live_gemini_read_only_bundle")
if isinstance(live_bundle, list):
    print(json.dumps(live_bundle))
    raise SystemExit(0)

tools = []
if verification_available:
    tools.extend(
        [
            "seedcore.verification.queue",
            "seedcore.verification.workflow_verification_detail",
            "seedcore.verification.workflow_replay",
            "seedcore.verification.runbook_lookup",
        ]
    )
tools.extend(["seedcore.hotpath.status", "seedcore.hotpath.metrics"])
print(json.dumps(tools))
PY
  )"

  local reasons_json
  if [[ ${#reasons[@]} -eq 0 ]]; then
    reasons_json='[]'
  else
    reasons_json="$(printf '%s\n' "${reasons[@]}" | jq -R . | jq -s .)"
  fi

  mkdir -p "${REPORT_DIR}"
  local report_path="${REPORT_DIR}/kube_topology_signoff_$(date -u +%Y%m%dT%H%M%SZ).json"
  jq -n \
    --arg captured_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg namespace "${NAMESPACE}" \
    --arg runtime_api_base "${RUNTIME_API_BASE}" \
    --arg verification_api_base "${VERIFICATION_API_BASE}" \
    --argjson status "${status_json}" \
    --argjson observability_gate_passed "${observability_ok}" \
    --argjson redis_drill_passed "${redis_drill_ok}" \
    --arg benchmark_artifact "${benchmark_path}" \
    --arg baseline_artifact "${baseline_path}" \
    --argjson benchmark_payload "${benchmark_payload}" \
    --argjson verification_api_available "${verification_api_available}" \
    --argjson q3_green_enough "${q3_ready}" \
    --argjson q3_blockers "${reasons_json}" \
    --argjson safe_gemini_read_surface "${safe_tools_json}" \
    '{
      captured_at: $captured_at,
      namespace: $namespace,
      runtime_api_base: $runtime_api_base,
      verification_api_base: $verification_api_base,
      status: $status,
      observability_gate_passed: $observability_gate_passed,
      redis_drill_passed: $redis_drill_passed,
      benchmark_artifact: $benchmark_artifact,
      baseline_artifact: $baseline_artifact,
      benchmark_payload: $benchmark_payload,
      verification_api_available: $verification_api_available,
      green_enough_for_narrow_q3_bridge: $q3_green_enough,
      q3_blockers: $q3_blockers,
      safe_gemini_read_surface: $safe_gemini_read_surface
    }' > "${report_path}"

  echo "${report_path}"
}

main() {
  require_bin curl
  require_bin jq
  require_bin python3
  require_bin kubectl

  echo "== Kube topology verification lane =="
  echo "Namespace: ${NAMESPACE}"
  echo "Runtime API: ${RUNTIME_API_BASE}"
  echo "Verification API: ${VERIFICATION_API_BASE}"
  echo "Run degraded drills: ${RUN_DEGRADED_DRILLS}"
  echo "Run benchmark/baseline: ${RUN_BENCHMARK_BASELINE}"

  start_port_forward_if_needed

  local health_code ready_code status_json
  health_code="$(status_code "${RUNTIME_HEALTH_URL}")"
  ready_code="$(status_code "${RUNTIME_READYZ_URL}")"
  status_json="$(curl -fsS "${RUNTIME_API_BASE}/pdp/hot-path/status")"

  [[ "${health_code}" == "200" ]] || { echo "[FAIL] /health=${health_code}" >&2; exit 1; }
  [[ "${ready_code}" == "200" ]] || { echo "[FAIL] /readyz=${ready_code}" >&2; exit 1; }
  jq -e '.runtime_ready == true and .authz_graph_ready == true and .graph_freshness_ok == true' >/dev/null <<<"${status_json}" || {
    echo "[FAIL] runtime status gate failed" >&2
    echo "${status_json}" | jq .
    exit 1
  }

  SEEDCORE_RUNTIME_API_BASE="${RUNTIME_API_BASE}" bash "${ROOT}/scripts/host/verify_hot_path_observability.sh"
  local observability_ok=true

  local redis_drill_ok=true
  if is_true "${RUN_DEGRADED_DRILLS}" && is_true "${RUN_REDIS_DEPENDENCY_DRILL}"; then
    SEEDCORE_RUNTIME_API_BASE="${RUNTIME_API_BASE}" \
    SEEDCORE_RUNTIME_HEALTH_URL="${RUNTIME_HEALTH_URL}" \
    SEEDCORE_RUNTIME_READYZ_URL="${RUNTIME_READYZ_URL}" \
    SEEDCORE_REDIS_DRILL_MODE="${SEEDCORE_REDIS_DRILL_MODE:-auto}" \
    SEEDCORE_REDIS_KUBE_NAMESPACE="${SEEDCORE_REDIS_KUBE_NAMESPACE:-${NAMESPACE}}" \
    bash "${ROOT}/scripts/host/verify_pkg_redis_resilience.sh"
  fi

  local benchmark_artifact=""
  local baseline_artifact=""
  if is_true "${RUN_BENCHMARK_BASELINE}"; then
    python3 "${ROOT}/scripts/host/benchmark_rct_hot_path.py" \
      --base-url "${RUNTIME_API_BASE}" \
      --requests "${BENCH_REQUESTS}" \
      --warmup "${BENCH_WARMUP}" \
      --concurrency "${BENCH_CONCURRENCY}"
    baseline_artifact="$(
      python3 "${ROOT}/scripts/host/capture_hot_path_deployment_baseline.py" \
        --runtime-api-base "${RUNTIME_API_BASE}"
    )"
    benchmark_artifact="$(latest_json_path "${ROOT}/.local-runtime/hot_path_benchmarks")"
  fi

  local verification_api_available=false
  if probe_verification_api; then
    verification_api_available=true
  fi

  local plugin_bundle_json=""
  if [[ -n "${PLUGIN_INFO_URL}" ]] && [[ "$(status_code "${PLUGIN_INFO_URL}")" == "200" ]]; then
    plugin_bundle_json="$(curl -fsS "${PLUGIN_INFO_URL}")"
  fi

  local report_path
  report_path="$(build_report \
    "${status_json}" \
    "${observability_ok}" \
    "${redis_drill_ok}" \
    "${benchmark_artifact}" \
    "${baseline_artifact}" \
    "${verification_api_available}" \
    "${plugin_bundle_json}")"

  echo "Kube topology verification report: ${report_path}"
  jq '. | {green_enough_for_narrow_q3_bridge, q3_blockers, verification_api_available, safe_gemini_read_surface}' "${report_path}"

  if is_true "${ENFORCE_Q3_GATE}"; then
    jq -e '.green_enough_for_narrow_q3_bridge == true' "${report_path}" >/dev/null || {
      echo "[FAIL] Q3 readiness gate is not green enough" >&2
      exit 1
    }
  fi
}

main "$@"
