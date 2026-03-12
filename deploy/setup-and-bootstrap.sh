#!/usr/bin/env bash
# Convenience wrapper for local SeedCore cluster bring-up.

set -euo pipefail
trap 'echo "🛑 Interrupted"; exit 1' INT TERM

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

NAMESPACE="${NAMESPACE:-seedcore-dev}"
CLUSTER_NAME="${CLUSTER_NAME:-seedcore-dev}"
RAY_IMAGE="${RAY_IMAGE:-seedcore:latest}"
RAYSERVICE_NAME="${RAYSERVICE_NAME:-seedcore-svc}"
STABLE_SERVE_SVC_NAME="${STABLE_SERVE_SVC_NAME:-}"
WAIT_AFTER_SETUP_S="${WAIT_AFTER_SETUP_S:-15}"
WAIT_AFTER_BOOTSTRAP_S="${WAIT_AFTER_BOOTSTRAP_S:-0}"
SKIP_SETUP="${SKIP_SETUP:-false}"
SKIP_BOOTSTRAP="${SKIP_BOOTSTRAP:-false}"

if [[ -t 1 ]]; then
  START_PORT_FORWARD="${START_PORT_FORWARD:-true}"
else
  START_PORT_FORWARD="${START_PORT_FORWARD:-false}"
fi

usage() {
  local stable_service_default="${STABLE_SERVE_SVC_NAME:-${RAYSERVICE_NAME}-stable-svc}"
  cat <<EOF
Usage: $(basename "$0") [options]

Options:
  -n, --namespace <ns>         Kubernetes namespace (default: ${NAMESPACE})
  -c, --cluster <name>         Kind cluster name (default: ${CLUSTER_NAME})
  -i, --image <img:tag>        Ray/bootstrap image (default: ${RAY_IMAGE})
      --rayservice-name <n>    RayService name (default: ${RAYSERVICE_NAME})
      --stable-service <name>  Stable Ray service name (default: ${stable_service_default})
      --skip-setup             Skip setup-ray-serve.sh
      --skip-bootstrap         Skip bootstrap.sh
      --skip-port-forward      Do not start port-forward.sh
      --wait-after-setup <s>   Extra settle time after setup (default: ${WAIT_AFTER_SETUP_S})
      --wait-after-bootstrap <s>
                               Extra settle time after bootstrap (default: ${WAIT_AFTER_BOOTSTRAP_S})
      --port-forward           Force port forwarding even in non-interactive shells
  -h, --help                   Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--namespace) NAMESPACE="$2"; shift 2 ;;
    -c|--cluster) CLUSTER_NAME="$2"; shift 2 ;;
    -i|--image) RAY_IMAGE="$2"; shift 2 ;;
    --rayservice-name) RAYSERVICE_NAME="$2"; shift 2 ;;
    --stable-service) STABLE_SERVE_SVC_NAME="$2"; shift 2 ;;
    --skip-setup) SKIP_SETUP=true; shift ;;
    --skip-bootstrap) SKIP_BOOTSTRAP=true; shift ;;
    --skip-port-forward) START_PORT_FORWARD=false; shift ;;
    --wait-after-setup) WAIT_AFTER_SETUP_S="$2"; shift 2 ;;
    --wait-after-bootstrap) WAIT_AFTER_BOOTSTRAP_S="$2"; shift 2 ;;
    --port-forward) START_PORT_FORWARD=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "❌ Unknown argument: $1"; usage; exit 1 ;;
  esac
done

if [[ -z "${STABLE_SERVE_SVC_NAME}" ]]; then
  STABLE_SERVE_SVC_NAME="${RAYSERVICE_NAME}-stable-svc"
fi

echo "═══════════════════════════════════════════════════════════════"
echo "🚀 SeedCore setup + bootstrap"
echo "═══════════════════════════════════════════════════════════════"
echo "   • Namespace:      ${NAMESPACE}"
echo "   • Cluster:        ${CLUSTER_NAME}"
echo "   • Ray image:      ${RAY_IMAGE}"
echo "   • RayService:     ${RAYSERVICE_NAME}"
echo "   • Stable service: ${STABLE_SERVE_SVC_NAME}"
echo

run_setup() {
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "📍 Step 1: setup-ray-serve.sh"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  bash "${SCRIPT_DIR}/setup-ray-serve.sh" \
    --namespace "${NAMESPACE}" \
    --cluster "${CLUSTER_NAME}" \
    --image "${RAY_IMAGE}" \
    --rayservice-name "${RAYSERVICE_NAME}" \
    --stable-service "${STABLE_SERVE_SVC_NAME}"
  echo
}

run_bootstrap() {
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "📍 Step 2: bootstrap.sh"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  bash "${SCRIPT_DIR}/bootstrap.sh" \
    --namespace "${NAMESPACE}" \
    --image "${RAY_IMAGE}" \
    --rayservice-name "${RAYSERVICE_NAME}" \
    --ray-head-svc "${STABLE_SERVE_SVC_NAME}"
  echo
}

run_port_forward() {
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "📍 Step 3: port-forward.sh"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  RAYSERVICE_NAME="${RAYSERVICE_NAME}" \
  STABLE_RAY_SVC="${STABLE_SERVE_SVC_NAME}" \
  bash "${SCRIPT_DIR}/port-forward.sh" "${NAMESPACE}"
}

if [[ "${SKIP_SETUP}" != "true" ]]; then
  run_setup
  if (( WAIT_AFTER_SETUP_S > 0 )); then
    echo "⏳ Waiting ${WAIT_AFTER_SETUP_S}s for Ray services to settle..."
    sleep "${WAIT_AFTER_SETUP_S}"
  fi
else
  echo "ℹ️  Skipping setup-ray-serve.sh"
  echo
fi

if [[ "${SKIP_BOOTSTRAP}" != "true" ]]; then
  run_bootstrap
  if (( WAIT_AFTER_BOOTSTRAP_S > 0 )); then
    echo "⏳ Waiting ${WAIT_AFTER_BOOTSTRAP_S}s after bootstrap..."
    sleep "${WAIT_AFTER_BOOTSTRAP_S}"
  fi
else
  echo "ℹ️  Skipping bootstrap.sh"
  echo
fi

if [[ "${START_PORT_FORWARD}" == "true" ]]; then
  run_port_forward
else
  echo "ℹ️  Port forwarding skipped"
  echo "   Start it later with: ${SCRIPT_DIR}/port-forward.sh ${NAMESPACE}"
fi
