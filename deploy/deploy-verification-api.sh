#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

CLUSTER_NAME="${CLUSTER_NAME:-seedcore-dev}"
NAMESPACE="${NAMESPACE:-seedcore-dev}"
VERIFICATION_API_IMAGE="${VERIFICATION_API_IMAGE:-seedcore-verification-api:latest}"
BUILD_IMAGE="${BUILD_IMAGE:-true}"
BUILD_PLATFORM="${BUILD_PLATFORM:-linux/amd64}"
BUILD_NO_CACHE="${BUILD_NO_CACHE:-0}"
SKIP_LOAD="${SKIP_LOAD:-0}"
VERIFICATION_SERVICE_NAME="${VERIFICATION_SERVICE_NAME:-seedcore-verification-api}"
VERIFICATION_DEPLOYMENT_NAME="${VERIFICATION_DEPLOYMENT_NAME:-seedcore-verification-api}"
VERIFICATION_APP_LABEL="${VERIFICATION_APP_LABEL:-seedcore-verification-api}"
VERIFICATION_RUNTIME_API_BASE="${VERIFICATION_RUNTIME_API_BASE:-http://seedcore-api.${NAMESPACE}.svc.cluster.local:8002/api/v1}"
YAML_PATH="${YAML_PATH:-${SCRIPT_DIR}/k8s/verification-api.yaml}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Options:
  -n, --namespace <ns>                 Namespace (default: ${NAMESPACE})
  -c, --cluster <name>                 Kind cluster name (default: ${CLUSTER_NAME})
  -i, --image <img:tag>                Verification API image (default: ${VERIFICATION_API_IMAGE})
      --build-image <true|false>       Build image before deploy (default: ${BUILD_IMAGE})
      --skip-load                       Skip kind image load
      --runtime-api-base <url>         Runtime API base for verification service
      --yaml <path>                    Verification API manifest template
  -h, --help                           Show help
EOF
}

is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|y|Y|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

ensure_envsubst() {
  if command -v envsubst >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

envsubst_fallback() {
  python3 - <<'PY'
import os
import re
import sys

raw = sys.stdin.read()
pattern = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
sys.stdout.write(pattern.sub(lambda m: os.environ.get(m.group(1), m.group(0)), raw))
PY
}

image_name_from_ref() {
  local image_ref="$1"
  local last_segment="${image_ref##*/}"
  if [[ "${last_segment}" == *:* ]]; then
    printf '%s\n' "${image_ref%:*}"
  else
    printf '%s\n' "${image_ref}"
  fi
}

image_tag_from_ref() {
  local image_ref="$1"
  local last_segment="${image_ref##*/}"
  if [[ "${last_segment}" == *:* ]]; then
    printf '%s\n' "${image_ref##*:}"
  else
    printf '%s\n' "latest"
  fi
}

smart_kind_load() {
  local image_ref="$1"
  if is_true "${SKIP_LOAD}"; then
    return 0
  fi

  local nodes
  nodes="$(kind get nodes --name "${CLUSTER_NAME}" 2>/dev/null || true)"
  if [[ -z "${nodes}" ]]; then
    echo "⚠️  Kind cluster '${CLUSTER_NAME}' not found; skipping image load."
    return 0
  fi

  local node
  for node in ${nodes}; do
    if ! docker exec "${node}" sh -lc "ctr -n k8s.io images ls -q | grep -Fxq '${image_ref}'"; then
      echo "Loading image ${image_ref} into Kind cluster ${CLUSTER_NAME}..."
      kind load docker-image "${image_ref}" --name "${CLUSTER_NAME}"
      return 0
    fi
  done
  echo "Image ${image_ref} already present on all Kind nodes."
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--namespace) NAMESPACE="$2"; shift 2 ;;
    -c|--cluster) CLUSTER_NAME="$2"; shift 2 ;;
    -i|--image) VERIFICATION_API_IMAGE="$2"; shift 2 ;;
    --build-image) BUILD_IMAGE="$2"; shift 2 ;;
    --skip-load) SKIP_LOAD=1; shift ;;
    --runtime-api-base) VERIFICATION_RUNTIME_API_BASE="$2"; shift 2 ;;
    --yaml) YAML_PATH="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

command -v kubectl >/dev/null 2>&1 || { echo "kubectl not found" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "docker not found" >&2; exit 1; }
command -v kind >/dev/null 2>&1 || { echo "kind not found" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "python3 not found" >&2; exit 1; }

kubectl get ns "${NAMESPACE}" >/dev/null 2>&1 || kubectl create namespace "${NAMESPACE}" >/dev/null

if is_true "${BUILD_IMAGE}"; then
  echo "Building verification API image ${VERIFICATION_API_IMAGE}..."
  (
    cd "${PROJECT_ROOT}"
    PLATFORM="${BUILD_PLATFORM}" \
    IMAGE_NAME="$(image_name_from_ref "${VERIFICATION_API_IMAGE}")" \
    IMAGE_TAG="$(image_tag_from_ref "${VERIFICATION_API_IMAGE}")" \
    DOCKERFILE="docker/Dockerfile.verification-api" \
    ENABLE_ML="0" \
    NO_CACHE="${BUILD_NO_CACHE}" \
    LOAD_IMAGE="1" \
    ./build.sh
  )
else
  echo "Skipping verification API image build (BUILD_IMAGE=${BUILD_IMAGE})."
fi

smart_kind_load "${VERIFICATION_API_IMAGE}"

export NAMESPACE
export VERIFICATION_API_IMAGE
export VERIFICATION_SERVICE_NAME
export VERIFICATION_DEPLOYMENT_NAME
export VERIFICATION_APP_LABEL
export VERIFICATION_RUNTIME_API_BASE

tmpfile="$(mktemp)"
if ensure_envsubst; then
  envsubst < "${YAML_PATH}" > "${tmpfile}"
else
  echo "⚠️  envsubst not found; using python fallback templating"
  envsubst_fallback < "${YAML_PATH}" > "${tmpfile}"
fi
kubectl apply -f "${tmpfile}"
rm -f "${tmpfile}"

echo "Waiting for verification API rollout..."
kubectl -n "${NAMESPACE}" rollout status deployment/"${VERIFICATION_DEPLOYMENT_NAME}" --timeout=180s

echo "Verification API deployment:"
kubectl -n "${NAMESPACE}" get deployment "${VERIFICATION_DEPLOYMENT_NAME}"
echo "Verification API service:"
kubectl -n "${NAMESPACE}" get svc "${VERIFICATION_SERVICE_NAME}"

echo "✅ Verification API deployed"
echo "   Port-forward: kubectl -n ${NAMESPACE} port-forward svc/${VERIFICATION_SERVICE_NAME} 7071:7071"
echo "   Health check: curl -fsS http://127.0.0.1:7071/health"
