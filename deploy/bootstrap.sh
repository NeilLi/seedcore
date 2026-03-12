#!/usr/bin/env bash
# SeedCore bootstrap job launcher for organism/dispatcher initialization.

set -euo pipefail
trap 'echo "🛑 Interrupted"; exit 1' INT TERM

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

NAMESPACE="${NAMESPACE:-seedcore-dev}"
RAYSERVICE_NAME="${RAYSERVICE_NAME:-seedcore-svc}"
RAY_HEAD_SVC="${RAY_HEAD_SVC:-}"
JOB_NAME="${JOB_NAME:-seedcore-bootstrap}"
JOB_FILE="${JOB_FILE:-${SCRIPT_DIR}/k8s/bootstrap-job.yaml}"
BOOTSTRAP_IMAGE="${BOOTSTRAP_IMAGE:-${RAY_IMAGE:-seedcore:latest}}"
BOOTSTRAP_TIMEOUT="${BOOTSTRAP_TIMEOUT:-900}"
WAIT_FOR_RAY_TIMEOUT="${WAIT_FOR_RAY_TIMEOUT:-300}"
TAIL_LOGS_ON_SUCCESS="${TAIL_LOGS_ON_SUCCESS:-false}"
RAY_NAMESPACE="${RAY_NAMESPACE:-${NAMESPACE}}"
PG_SERVICE="${PG_SERVICE:-postgresql}"
PG_PORT="${PG_PORT:-5432}"
PG_DB="${PG_DB:-seedcore}"
PG_USER="${PG_USER:-postgres}"
PG_PASSWORD="${PG_PASSWORD:-postgres}"

usage() {
  local ray_head_default="${RAY_HEAD_SVC:-${RAYSERVICE_NAME}-stable-svc}"
  cat <<EOF
Usage: $(basename "$0") [options]

Options:
  -n, --namespace <ns>       Kubernetes namespace (default: ${NAMESPACE})
      --job-name <name>      Bootstrap Job name (default: ${JOB_NAME})
      --job-file <path>      Source manifest template (default: ${JOB_FILE})
      --image <img:tag>      Bootstrap image (default: ${BOOTSTRAP_IMAGE})
      --rayservice-name <n>  RayService name used to derive stable service
      --ray-head-svc <name>  Stable Ray service name (default: ${ray_head_default})
      --timeout <seconds>    Job completion timeout (default: ${BOOTSTRAP_TIMEOUT})
      --ray-timeout <sec>    Wait time for Ray service endpoints (default: ${WAIT_FOR_RAY_TIMEOUT})
      --tail-logs            Tail final job logs after success
  -h, --help                 Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--namespace) NAMESPACE="$2"; shift 2 ;;
    --job-name) JOB_NAME="$2"; shift 2 ;;
    --job-file) JOB_FILE="$2"; shift 2 ;;
    --image) BOOTSTRAP_IMAGE="$2"; shift 2 ;;
    --rayservice-name) RAYSERVICE_NAME="$2"; shift 2 ;;
    --ray-head-svc) RAY_HEAD_SVC="$2"; shift 2 ;;
    --timeout) BOOTSTRAP_TIMEOUT="$2"; shift 2 ;;
    --ray-timeout) WAIT_FOR_RAY_TIMEOUT="$2"; shift 2 ;;
    --tail-logs) TAIL_LOGS_ON_SUCCESS=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "❌ Unknown argument: $1"; usage; exit 1 ;;
  esac
done

if [[ -z "${RAY_HEAD_SVC}" ]]; then
  RAY_HEAD_SVC="${RAYSERVICE_NAME}-stable-svc"
fi

echo "🚀 Deploying SeedCore bootstrap job"
echo "   • Namespace:      ${NAMESPACE}"
echo "   • Job:            ${JOB_NAME}"
echo "   • Image:          ${BOOTSTRAP_IMAGE}"
echo "   • Stable Ray SVC: ${RAY_HEAD_SVC}"

[[ -n "${NAMESPACE}" ]] || { echo "❌ NAMESPACE is empty"; exit 1; }
[[ -f "${JOB_FILE}" ]] || { echo "❌ Job template not found: ${JOB_FILE}"; exit 1; }
command -v kubectl >/dev/null 2>&1 || { echo "❌ kubectl not found"; exit 1; }

wait_for_service_endpoints() {
  local service_name="$1"
  local timeout_s="$2"
  local elapsed=0

  echo "⏳ Waiting for service/${service_name} endpoints..."
  while (( elapsed < timeout_s )); do
    if kubectl get svc "${service_name}" -n "${NAMESPACE}" >/dev/null 2>&1; then
      local endpoint_ip
      endpoint_ip="$(kubectl get endpoints "${service_name}" -n "${NAMESPACE}" -o jsonpath='{.subsets[0].addresses[0].ip}' 2>/dev/null || true)"
      if [[ -n "${endpoint_ip}" ]]; then
        echo "✅ service/${service_name} is routable (${endpoint_ip})"
        return 0
      fi
    fi
    sleep 5
    elapsed=$((elapsed + 5))
  done

  echo "❌ Timed out waiting for service/${service_name} endpoints"
  kubectl get svc "${service_name}" -n "${NAMESPACE}" || true
  kubectl get endpoints "${service_name}" -n "${NAMESPACE}" || true
  return 1
}

render_job_manifest() {
  local dst="$1"
  local ray_address="ray://${RAY_HEAD_SVC}:10001"
  local serve_base_url="http://${RAY_HEAD_SVC}.${NAMESPACE}.svc.cluster.local:8000"
  local organism_url="${serve_base_url}/organism"
  local pg_dsn="postgresql://${PG_USER}:${PG_PASSWORD}@${PG_SERVICE}.${NAMESPACE}.svc.cluster.local:${PG_PORT}/${PG_DB}"

  awk \
    -v namespace="${NAMESPACE}" \
    -v job_name="${JOB_NAME}" \
    -v image="${BOOTSTRAP_IMAGE}" \
    -v ray_address="${ray_address}" \
    -v ray_namespace="${RAY_NAMESPACE}" \
    -v serve_base_url="${serve_base_url}" \
    -v organism_url="${organism_url}" \
    -v pg_dsn="${pg_dsn}" '
    BEGIN {
      in_top_metadata = 0
      top_metadata_done = 0
      current_env = ""
    }
    !top_metadata_done && /^metadata:[[:space:]]*$/ {
      in_top_metadata = 1
      print
      next
    }
    in_top_metadata && /^  name:[[:space:]]*/ {
      print "  name: " job_name
      next
    }
    in_top_metadata && /^  namespace:[[:space:]]*/ {
      print "  namespace: " namespace
      next
    }
    in_top_metadata && /^spec:[[:space:]]*$/ {
      in_top_metadata = 0
      top_metadata_done = 1
      print
      next
    }
    /^[[:space:]]*image:[[:space:]]*/ {
      print "          image: " image
      next
    }
    /^[[:space:]]*- name:[[:space:]]*/ {
      current_env = $3
      print
      next
    }
    current_env == "RAY_ADDRESS" && /^[[:space:]]*value:[[:space:]]*/ {
      print "              value: \"" ray_address "\""
      current_env = ""
      next
    }
    current_env == "RAY_NAMESPACE" && /^[[:space:]]*value:[[:space:]]*/ {
      print "              value: \"" ray_namespace "\""
      current_env = ""
      next
    }
    current_env == "SEEDCORE_NS" && /^[[:space:]]*value:[[:space:]]*/ {
      print "              value: \"" ray_namespace "\""
      current_env = ""
      next
    }
    current_env == "SEEDCORE_PG_DSN" && /^[[:space:]]*value:[[:space:]]*/ {
      print "              value: \"" pg_dsn "\""
      current_env = ""
      next
    }
    current_env == "SERVE_BASE_URL" && /^[[:space:]]*value:[[:space:]]*/ {
      print "              value: \"" serve_base_url "\""
      current_env = ""
      next
    }
    current_env == "ORGANISM_URL" && /^[[:space:]]*value:[[:space:]]*/ {
      print "              value: \"" organism_url "\""
      current_env = ""
      next
    }
    { print }
  ' "${JOB_FILE}" > "${dst}"
}

wait_for_service_endpoints "${RAY_HEAD_SVC}" "${WAIT_FOR_RAY_TIMEOUT}"

RENDERED_JOB="${TMP_DIR}/bootstrap-job.rendered.yaml"
render_job_manifest "${RENDERED_JOB}"

if kubectl get job "${JOB_NAME}" -n "${NAMESPACE}" >/dev/null 2>&1; then
  echo "ℹ️  Removing existing job/${JOB_NAME} before redeploy"
  kubectl delete job "${JOB_NAME}" -n "${NAMESPACE}" --wait=true >/dev/null
fi

echo "📦 Applying rendered bootstrap job manifest"
kubectl apply -f "${RENDERED_JOB}" >/dev/null

echo "⏳ Waiting for job/${JOB_NAME} to complete (timeout: ${BOOTSTRAP_TIMEOUT}s)..."
if ! kubectl wait --for=condition=complete "job/${JOB_NAME}" -n "${NAMESPACE}" --timeout="${BOOTSTRAP_TIMEOUT}s"; then
  echo "❌ Bootstrap job did not complete successfully"
  echo
  echo "🔍 Job describe:"
  kubectl describe "job/${JOB_NAME}" -n "${NAMESPACE}" || true
  echo
  echo "📝 Recent logs:"
  kubectl logs "job/${JOB_NAME}" -n "${NAMESPACE}" --tail=200 || true
  exit 1
fi

echo "✅ Bootstrap job completed successfully"
if [[ "${TAIL_LOGS_ON_SUCCESS}" == "true" ]]; then
  echo
  echo "📝 Final logs:"
  kubectl logs "job/${JOB_NAME}" -n "${NAMESPACE}" --tail=-1 || true
fi
