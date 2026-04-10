#!/usr/bin/env bash
# Deployment-realistic kube verification lane for Q2/Q3 gate validation.
# Validates runtime gates, degraded drills, benchmark/baseline artifacts, and
# conditionally upgrades to full verification-surface protocol checks when the
# verification API is available in the topology.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

NAMESPACE="${NAMESPACE:-seedcore-dev}"

RUNTIME_LOCAL_PORT="${SEEDCORE_RUNTIME_LOCAL_PORT:-8002}"
RUNTIME_API_BASE="${SEEDCORE_RUNTIME_API_BASE:-http://127.0.0.1:${RUNTIME_LOCAL_PORT}/api/v1}"
RUNTIME_HEALTH_URL="${SEEDCORE_RUNTIME_HEALTH_URL:-http://127.0.0.1:${RUNTIME_LOCAL_PORT}/health}"
RUNTIME_READYZ_URL="${SEEDCORE_RUNTIME_READYZ_URL:-http://127.0.0.1:${RUNTIME_LOCAL_PORT}/readyz}"
ENABLE_RUNTIME_PORT_FORWARD="${SEEDCORE_ENABLE_PORT_FORWARD:-1}"
RUNTIME_PORT_FORWARD_LOG="${SEEDCORE_KUBE_PORT_FORWARD_LOG:-${ROOT}/.local-runtime/kube_topology/seedcore_api_port_forward.log}"

VERIFICATION_LOCAL_PORT="${SEEDCORE_VERIFICATION_LOCAL_PORT:-7071}"
VERIFICATION_API_BASE="${SEEDCORE_VERIFICATION_API_BASE:-http://127.0.0.1:${VERIFICATION_LOCAL_PORT}}"
VERIFICATION_SERVICE_NAME="${SEEDCORE_VERIFICATION_SERVICE_NAME:-seedcore-verification-api}"
ENABLE_VERIFICATION_PORT_FORWARD="${SEEDCORE_ENABLE_VERIFICATION_PORT_FORWARD:-1}"
VERIFICATION_PORT_FORWARD_LOG="${SEEDCORE_VERIFICATION_PORT_FORWARD_LOG:-${ROOT}/.local-runtime/kube_topology/verification_api_port_forward.log}"

REPORT_DIR="${SEEDCORE_KUBE_VERIFY_REPORT_DIR:-${ROOT}/.local-runtime/kube_topology}"
RUN_DEGRADED_DRILLS="${SEEDCORE_RUN_DEGRADED_DRILLS:-1}"
RUN_REDIS_DEPENDENCY_DRILL="${SEEDCORE_RUN_REDIS_DEPENDENCY_DRILL:-1}"
RUN_BENCHMARK_BASELINE="${SEEDCORE_RUN_BENCHMARK_BASELINE:-1}"
RUN_FULL_VERIFICATION_SURFACE_CHECK="${SEEDCORE_RUN_FULL_VERIFICATION_SURFACE_CHECK:-1}"
ENFORCE_Q3_GATE="${SEEDCORE_ENFORCE_Q3_GATE:-0}"
ENFORCE_FULL_VERIFICATION_GATE="${SEEDCORE_ENFORCE_FULL_VERIFICATION_GATE:-0}"
CONSTRUCT_RUNTIME_AUDIT_FIXTURE="${SEEDCORE_CONSTRUCT_RUNTIME_AUDIT_FIXTURE:-}"
CONSTRUCT_PKG_MINIMAL_CONTRACT_FIXTURE="${SEEDCORE_CONSTRUCT_PKG_MINIMAL_CONTRACT_FIXTURE:-}"
BENCH_REQUESTS="${SEEDCORE_BENCH_REQUESTS:-40}"
BENCH_WARMUP="${SEEDCORE_BENCH_WARMUP:-4}"
BENCH_CONCURRENCY="${SEEDCORE_BENCH_CONCURRENCY:-4}"

POSTGRES_POD_SELECTORS="${SEEDCORE_POSTGRES_POD_SELECTORS:-app=postgres,app.kubernetes.io/name=postgres,app.kubernetes.io/name=postgresql,app=postgresql}"
POSTGRES_DB_NAME="${SEEDCORE_DB_NAME:-seedcore}"
POSTGRES_USER="${SEEDCORE_POSTGRES_USER:-postgres}"
POSTGRES_PASSWORD="${SEEDCORE_POSTGRES_PASSWORD:-password}"

RUNTIME_PORT_FORWARD_PID=""
VERIFICATION_PORT_FORWARD_PID=""

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[FAIL] missing required binary: $1" >&2
    exit 1
  fi
}

is_loopback_url() {
  local url="$1"
  [[ "${url}" == http://127.0.0.1* || "${url}" == http://localhost* || "${url}" == https://127.0.0.1* || "${url}" == https://localhost* ]]
}

is_ipv4_loopback_url() {
  local url="$1"
  [[ "${url}" == http://127.0.0.1* || "${url}" == https://127.0.0.1* ]]
}

port_forward_running_for() {
  local service_name="$1"
  local local_port="$2"
  local remote_port="$3"
  pgrep -f "kubectl .*port-forward .*svc/${service_name} ${local_port}:${remote_port}" >/dev/null 2>&1
}

ipv4_loopback_port_bound_by_non_kubectl() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP@"127.0.0.1:${port}" -sTCP:LISTEN 2>/dev/null | awk 'NR>1 && $1 != "kubectl" {found=1} END {exit found ? 0 : 1}'
    return $?
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -ltnp 2>/dev/null | grep -F "127.0.0.1:${port}" | grep -v "kubectl" >/dev/null 2>&1
    return $?
  fi
  return 1
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
  for ((i = 0; i < attempts; i += 1)); do
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

verification_health_url() {
  local root="${VERIFICATION_API_BASE%/api/v1}"
  echo "${root}/health"
}

cleanup() {
  if [[ -n "${RUNTIME_PORT_FORWARD_PID}" ]]; then
    kill "${RUNTIME_PORT_FORWARD_PID}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${VERIFICATION_PORT_FORWARD_PID}" ]]; then
    kill "${VERIFICATION_PORT_FORWARD_PID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

start_runtime_port_forward_if_needed() {
  if [[ "$(status_code "${RUNTIME_HEALTH_URL}")" == "200" ]]; then
    if is_ipv4_loopback_url "${RUNTIME_HEALTH_URL}" && ipv4_loopback_port_bound_by_non_kubectl "${RUNTIME_LOCAL_PORT}"; then
      echo "[FAIL] non-kubectl process is bound on 127.0.0.1:${RUNTIME_LOCAL_PORT}; kube verification would be shadowed." >&2
      echo "Choose a different SEEDCORE_RUNTIME_LOCAL_PORT or stop the local runtime service." >&2
      exit 1
    fi
    if is_true "${ENABLE_RUNTIME_PORT_FORWARD}" && is_loopback_url "${RUNTIME_HEALTH_URL}" && \
      ! port_forward_running_for "seedcore-api" "${RUNTIME_LOCAL_PORT}" "8002"; then
      echo "[FAIL] ${RUNTIME_HEALTH_URL} is already served locally without kube port-forward; this can shadow kube verification." >&2
      echo "Set SEEDCORE_RUNTIME_LOCAL_PORT to a free port or stop the local runtime before verifying kube topology." >&2
      exit 1
    fi
    return 0
  fi
  if ! is_true "${ENABLE_RUNTIME_PORT_FORWARD}"; then
    echo "[FAIL] runtime endpoint ${RUNTIME_HEALTH_URL} is unreachable and SEEDCORE_ENABLE_PORT_FORWARD=0" >&2
    exit 1
  fi

  require_bin kubectl
  mkdir -p "$(dirname "${RUNTIME_PORT_FORWARD_LOG}")"
  echo "Starting kube port-forward for seedcore-api on :${RUNTIME_LOCAL_PORT}..."
  kubectl -n "${NAMESPACE}" port-forward svc/seedcore-api "${RUNTIME_LOCAL_PORT}:8002" >"${RUNTIME_PORT_FORWARD_LOG}" 2>&1 &
  RUNTIME_PORT_FORWARD_PID="$!"

  if ! wait_for_status "${RUNTIME_HEALTH_URL}" "200" 45; then
    echo "[FAIL] could not reach runtime /health after starting port-forward" >&2
    echo "--- runtime port-forward log ---" >&2
    tail -n 80 "${RUNTIME_PORT_FORWARD_LOG}" >&2 || true
    exit 1
  fi
}

probe_verification_api() {
  local code
  code="$(status_code "${VERIFICATION_API_BASE}/api/v1/verification/transfers/status?source=fixture&dir=rust/fixtures/transfers/allow_case")"
  [[ "${code}" == "200" ]]
}

verification_service_exists() {
  kubectl -n "${NAMESPACE}" get svc "${VERIFICATION_SERVICE_NAME}" >/dev/null 2>&1
}

start_verification_port_forward_if_needed() {
  if probe_verification_api; then
    if is_ipv4_loopback_url "${VERIFICATION_API_BASE}" && ipv4_loopback_port_bound_by_non_kubectl "${VERIFICATION_LOCAL_PORT}"; then
      echo "[FAIL] non-kubectl process is bound on 127.0.0.1:${VERIFICATION_LOCAL_PORT}; verification-surface checks would be shadowed." >&2
      echo "Choose a different SEEDCORE_VERIFICATION_LOCAL_PORT or stop the local verification service." >&2
      exit 1
    fi
    if is_true "${ENABLE_VERIFICATION_PORT_FORWARD}" && is_loopback_url "${VERIFICATION_API_BASE}" && \
      ! port_forward_running_for "${VERIFICATION_SERVICE_NAME}" "${VERIFICATION_LOCAL_PORT}" "7071"; then
      echo "[FAIL] ${VERIFICATION_API_BASE} is already served locally without kube port-forward; this can shadow verification-surface checks." >&2
      echo "Set SEEDCORE_VERIFICATION_LOCAL_PORT to a free port or stop the local service before verifying kube topology." >&2
      exit 1
    fi
    return 0
  fi
  if ! verification_service_exists; then
    return 1
  fi
  if ! is_true "${ENABLE_VERIFICATION_PORT_FORWARD}"; then
    return 1
  fi

  mkdir -p "$(dirname "${VERIFICATION_PORT_FORWARD_LOG}")"
  echo "Starting kube port-forward for ${VERIFICATION_SERVICE_NAME} on :${VERIFICATION_LOCAL_PORT}..."
  kubectl -n "${NAMESPACE}" port-forward svc/"${VERIFICATION_SERVICE_NAME}" "${VERIFICATION_LOCAL_PORT}:7071" >"${VERIFICATION_PORT_FORWARD_LOG}" 2>&1 &
  VERIFICATION_PORT_FORWARD_PID="$!"

  if ! wait_for_status "$(verification_health_url)" "200" 45; then
    echo "⚠️  verification API port-forward did not become healthy on ${VERIFICATION_API_BASE}" >&2
    echo "--- verification port-forward log ---" >&2
    tail -n 80 "${VERIFICATION_PORT_FORWARD_LOG}" >&2 || true
    return 1
  fi

  probe_verification_api
}

find_runtime_audit_id_from_kube_postgres() {
  if [[ -n "${SEEDCORE_AUDIT_ID:-}" ]]; then
    echo "${SEEDCORE_AUDIT_ID}"
    return 0
  fi

  local pod_name=""
  local selector
  IFS=',' read -r -a selectors <<<"${POSTGRES_POD_SELECTORS}"
  for selector in "${selectors[@]}"; do
    selector="$(echo "${selector}" | xargs)"
    [[ -n "${selector}" ]] || continue
    pod_name="$(
      kubectl -n "${NAMESPACE}" get pods -l "${selector}" \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true
    )"
    if [[ -n "${pod_name}" ]]; then
      break
    fi
  done
  if [[ -z "${pod_name}" ]]; then
    return 1
  fi

  local candidates=(
    "${POSTGRES_USER}:${POSTGRES_PASSWORD}:${POSTGRES_DB_NAME}"
    "postgres:password:seedcore"
    "postgres:password:postgres"
    "seedcore:seedcore:seedcore"
    "seedcore:seedcore:postgres"
  )
  local candidate user password db_name audit_id
  for candidate in "${candidates[@]}"; do
    IFS=':' read -r user password db_name <<<"${candidate}"
    audit_id="$(
      kubectl -n "${NAMESPACE}" exec "${pod_name}" -- \
        env PGPASSWORD="${password}" \
        psql -U "${user}" -d "${db_name}" -Atc \
          "select id::text from public.governed_execution_audit order by recorded_at desc limit 1;" 2>/dev/null | head -n 1 || true
    )"
    if [[ -n "${audit_id}" ]]; then
      echo "${audit_id}"
      return 0
    fi
  done
  return 1
}

ensure_runtime_audit_id_available() {
  local audit_id
  audit_id="$(find_runtime_audit_id_from_kube_postgres || true)"
  if [[ -n "${audit_id}" ]]; then
    echo "${audit_id}"
    return 0
  fi

  if [[ -z "${CONSTRUCT_RUNTIME_AUDIT_FIXTURE}" ]]; then
    return 1
  fi

  echo "No governed execution audit rows found; seeding fixture '${CONSTRUCT_RUNTIME_AUDIT_FIXTURE}' for runtime verification..."
  python3 "${ROOT}/scripts/host/seed_kube_runtime_audit_fixture.py" \
    --namespace "${NAMESPACE}" \
    --fixture-case "${CONSTRUCT_RUNTIME_AUDIT_FIXTURE}" \
    --db-name "${POSTGRES_DB_NAME}" \
    --db-user "${POSTGRES_USER}" \
    --db-password "${POSTGRES_PASSWORD}" \
    --postgres-pod-selectors "${POSTGRES_POD_SELECTORS}" >/dev/null

  audit_id="$(find_runtime_audit_id_from_kube_postgres || true)"
  if [[ -n "${audit_id}" ]]; then
    echo "${audit_id}"
    return 0
  fi
  return 1
}

runtime_status_gate_ok() {
  local status_json="$1"
  jq -e '.runtime_ready == true and .authz_graph_ready == true and .graph_freshness_ok == true' >/dev/null <<<"${status_json}"
}

attempt_pkg_minimal_contract_seed() {
  if [[ -z "${CONSTRUCT_PKG_MINIMAL_CONTRACT_FIXTURE}" ]]; then
    return 1
  fi
  echo "Runtime status gate failed; seeding minimal PKG contract/taxonomy fixture (${CONSTRUCT_PKG_MINIMAL_CONTRACT_FIXTURE})..."
  python3 "${ROOT}/scripts/host/seed_kube_pkg_minimal_contract.py" \
    --namespace "${NAMESPACE}" \
    --source-tag "${CONSTRUCT_PKG_MINIMAL_CONTRACT_FIXTURE}" \
    --db-name "${POSTGRES_DB_NAME}" \
    --db-user "${POSTGRES_USER}" \
    --db-password "${POSTGRES_PASSWORD}" \
    --postgres-pod-selectors "${POSTGRES_POD_SELECTORS}" >/dev/null
}

run_productized_surface_protocol() {
  local audit_id
  audit_id="$(ensure_runtime_audit_id_available || true)"
  if [[ -z "${audit_id}" ]]; then
    echo "⚠️  unable to discover runtime audit id; skipping full productized verification protocol" >&2
    return 1
  fi

  local protocol_log="${REPORT_DIR}/verification_surface_protocol_$(date -u +%Y%m%dT%H%M%SZ).log"
  mkdir -p "${REPORT_DIR}"
  if SEEDCORE_VERIFICATION_API_BASE="${VERIFICATION_API_BASE}" \
    SEEDCORE_RUNTIME_API_BASE="${RUNTIME_API_BASE}" \
    SEEDCORE_AUDIT_ID="${audit_id}" \
    SEEDCORE_SKIP_HOT_PATH_OBSERVABILITY_GATE=1 \
    SEEDCORE_RUN_REDIS_DEPENDENCY_DRILL=0 \
    SEEDCORE_RUN_KAFKA_DEPENDENCY_DRILL=0 \
    bash "${ROOT}/scripts/host/verify_productized_surface.sh" >"${protocol_log}" 2>&1; then
    echo "Productized verification-surface protocol passed (log: ${protocol_log})"
    return 0
  fi

  echo "⚠️  productized verification-surface protocol failed (log: ${protocol_log})" >&2
  tail -n 80 "${protocol_log}" >&2 || true
  return 1
}

build_report() {
  local status_json="$1"
  local observability_ok="$2"
  local redis_drill_ok="$3"
  local benchmark_path="$4"
  local baseline_path="$5"
  local verification_api_available="$6"
  local verification_surface_protocol_passed="$7"

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
  local q3_reasons=()
  if [[ "${runtime_ready}" != "true" ]]; then
    q3_ready=false
    q3_reasons+=("runtime_not_ready")
  fi
  if [[ "${authz_graph_ready}" != "true" ]]; then
    q3_ready=false
    q3_reasons+=("authz_graph_not_ready")
  fi
  if [[ "${graph_freshness_ok}" != "true" ]]; then
    q3_ready=false
    q3_reasons+=("graph_not_fresh")
  fi
  if [[ "${observability_ok}" != "true" ]]; then
    q3_ready=false
    q3_reasons+=("observability_gate_failed")
  fi
  if [[ "${redis_drill_ok}" != "true" ]]; then
    q3_ready=false
    q3_reasons+=("redis_drill_failed")
  fi
  if [[ "${benchmark_error_count}" != "0" ]]; then
    q3_ready=false
    q3_reasons+=("benchmark_errors_present")
  fi
  if [[ "${benchmark_mismatch_count}" != "0" ]]; then
    q3_ready=false
    q3_reasons+=("benchmark_mismatch_present")
  fi
  if [[ "${benchmark_graph_freshness_ok}" != "true" ]]; then
    q3_ready=false
    q3_reasons+=("benchmark_graph_not_fresh")
  fi
  if [[ "${benchmark_authz_graph_ready}" != "true" ]]; then
    q3_ready=false
    q3_reasons+=("benchmark_authz_graph_not_ready")
  fi

  local full_ready=true
  local full_reasons=()
  if [[ "${q3_ready}" != "true" ]]; then
    full_ready=false
  fi
  if [[ "${verification_api_available}" != "true" ]]; then
    full_ready=false
    full_reasons+=("verification_surface_unavailable")
  fi
  if [[ "${verification_surface_protocol_passed}" != "true" ]]; then
    full_ready=false
    full_reasons+=("verification_surface_protocol_failed")
  fi

  local q3_reasons_json full_reasons_json
  if [[ ${#q3_reasons[@]} -eq 0 ]]; then
    q3_reasons_json='[]'
  else
    q3_reasons_json="$(printf '%s\n' "${q3_reasons[@]}" | jq -R . | jq -s .)"
  fi
  if [[ ${#full_reasons[@]} -eq 0 ]]; then
    full_reasons_json='[]'
  else
    full_reasons_json="$(printf '%s\n' "${full_reasons[@]}" | jq -R . | jq -s .)"
  fi

  local safe_tools_json
  if [[ "${verification_surface_protocol_passed}" == "true" ]]; then
    safe_tools_json='["seedcore.verification.queue","seedcore.verification.workflow_verification_detail","seedcore.verification.workflow_replay","seedcore.verification.runbook_lookup","seedcore.hotpath.status","seedcore.hotpath.metrics"]'
  else
    safe_tools_json='["seedcore.hotpath.status","seedcore.hotpath.metrics"]'
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
    --argjson verification_surface_available "${verification_api_available}" \
    --argjson verification_surface_protocol_passed "${verification_surface_protocol_passed}" \
    --argjson q3_green_enough "${q3_ready}" \
    --argjson q3_blockers "${q3_reasons_json}" \
    --argjson full_green_enough "${full_ready}" \
    --argjson full_blockers "${full_reasons_json}" \
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
      verification_surface_available: $verification_surface_available,
      verification_surface_protocol_passed: $verification_surface_protocol_passed,
      green_enough_for_narrow_q3_bridge: $q3_green_enough,
      q3_blockers: $q3_blockers,
      green_enough_for_full_external_agent_debugging: $full_green_enough,
      full_external_agent_blockers: $full_blockers,
      safe_gemini_read_surface: $safe_gemini_read_surface
    }' >"${report_path}"

  echo "${report_path}"
}

main() {
  require_bin curl
  require_bin jq
  require_bin kubectl
  require_bin python3

  echo "== Kube topology verification lane =="
  echo "Namespace: ${NAMESPACE}"
  echo "Runtime API: ${RUNTIME_API_BASE}"
  echo "Verification API: ${VERIFICATION_API_BASE}"
  echo "Run degraded drills: ${RUN_DEGRADED_DRILLS}"
  echo "Run benchmark/baseline: ${RUN_BENCHMARK_BASELINE}"
  echo "Run full verification-surface check: ${RUN_FULL_VERIFICATION_SURFACE_CHECK}"

  start_runtime_port_forward_if_needed

  local health_code ready_code status_json
  health_code="$(status_code "${RUNTIME_HEALTH_URL}")"
  ready_code="$(status_code "${RUNTIME_READYZ_URL}")"
  status_json="$(curl -fsS "${RUNTIME_API_BASE}/pdp/hot-path/status")"

  [[ "${health_code}" == "200" ]] || { echo "[FAIL] /health=${health_code}" >&2; exit 1; }
  [[ "${ready_code}" == "200" ]] || { echo "[FAIL] /readyz=${ready_code}" >&2; exit 1; }
  if ! runtime_status_gate_ok "${status_json}"; then
    if ! attempt_pkg_minimal_contract_seed; then
      echo "[FAIL] runtime status gate failed" >&2
      echo "${status_json}" | jq .
      exit 1
    fi
    status_json="$(curl -fsS "${RUNTIME_API_BASE}/pdp/hot-path/status")"
    if ! runtime_status_gate_ok "${status_json}"; then
      echo "[FAIL] runtime status gate failed after minimal PKG contract/taxonomy seeding" >&2
      echo "${status_json}" | jq .
      exit 1
    fi
  fi

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
  if start_verification_port_forward_if_needed; then
    verification_api_available=true
  fi

  local verification_surface_protocol_passed=false
  if is_true "${RUN_FULL_VERIFICATION_SURFACE_CHECK}" && [[ "${verification_api_available}" == "true" ]]; then
    if run_productized_surface_protocol; then
      verification_surface_protocol_passed=true
    fi
  fi

  local report_path
  report_path="$(
    build_report \
      "${status_json}" \
      "${observability_ok}" \
      "${redis_drill_ok}" \
      "${benchmark_artifact}" \
      "${baseline_artifact}" \
      "${verification_api_available}" \
      "${verification_surface_protocol_passed}"
  )"

  echo "Kube topology verification report: ${report_path}"
  jq '. | {green_enough_for_narrow_q3_bridge, q3_blockers, verification_surface_available, verification_surface_protocol_passed, green_enough_for_full_external_agent_debugging, safe_gemini_read_surface}' "${report_path}"

  if is_true "${ENFORCE_Q3_GATE}"; then
    jq -e '.green_enough_for_narrow_q3_bridge == true' "${report_path}" >/dev/null || {
      echo "[FAIL] Q3 readiness gate is not green enough" >&2
      exit 1
    }
  fi
  if is_true "${ENFORCE_FULL_VERIFICATION_GATE}"; then
    jq -e '.green_enough_for_full_external_agent_debugging == true' "${report_path}" >/dev/null || {
      echo "[FAIL] full verification-surface gate is not green enough" >&2
      exit 1
    }
  fi
}

main "$@"
