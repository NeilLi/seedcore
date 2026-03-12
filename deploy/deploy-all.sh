#!/usr/bin/env bash
# SeedCore Deployment Orchestrator
# Runs full pipeline: build -> kind -> databases -> storage -> Ray -> bootstrap -> API

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEPLOY_DIR="${SCRIPT_DIR}"

# --------- OS Detection (macOS vs Linux) ----------
SEEDCORE_OS="$(uname -s | tr '[:upper:]' '[:lower:]')"  # darwin / linux
export SEEDCORE_OS

# ---------- PKG Policy Deployment ----------
APPLY_PKG_WASM="${APPLY_PKG_WASM:-false}"
PKG_WASM_FILE="${PKG_WASM_FILE:-}"
NAMESPACE="${NAMESPACE:-seedcore-dev}"
CLUSTER_NAME="${CLUSTER_NAME:-seedcore-dev}"
RAYSERVICE_NAME="${RAYSERVICE_NAME:-seedcore-svc}"
STABLE_SERVICE_NAME="${STABLE_SERVICE_NAME:-${RAYSERVICE_NAME}-stable-svc}"
SEEDCORE_IMAGE="${SEEDCORE_IMAGE:-seedcore:latest}"
RAY_IMAGE="${RAY_IMAGE:-${SEEDCORE_IMAGE}}"
API_IMAGE="${API_IMAGE:-${SEEDCORE_IMAGE}}"
BOOTSTRAP_IMAGE="${BOOTSTRAP_IMAGE:-${RAY_IMAGE}}"
ENV_FILE="${ENV_FILE:-${PROJECT_ROOT}/docker/.env}"
WORKER_REPLICAS="${WORKER_REPLICAS:-1}"
HOST_DATA_DIR="${HOST_DATA_DIR:-/tmp/seedcore-data}"
WAIT_FOR_RAY_S="${WAIT_FOR_RAY_S:-30}"
BUILD_IMAGE="${BUILD_IMAGE:-true}"
BUILD_ENABLE_ML="${BUILD_ENABLE_ML:-0}"
DEPLOY_ENABLE_ML_SERVICE="${DEPLOY_ENABLE_ML_SERVICE:-${BUILD_ENABLE_ML}}"
BUILD_NO_CACHE="${BUILD_NO_CACHE:-0}"
BUILD_DOCKERFILE="${BUILD_DOCKERFILE:-docker/Dockerfile.optimize}"
BUILD_PLATFORM="${BUILD_PLATFORM:-linux/amd64}"
SKIP_KIND_LOAD="${SKIP_KIND_LOAD:-false}"
TAIL_BOOTSTRAP_LOGS="${TAIL_BOOTSTRAP_LOGS:-false}"
DEPLOY_INGRESS_ENABLED="${DEPLOY_INGRESS_ENABLED:-true}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Options:
  -n, --namespace <ns>        Namespace (default: ${NAMESPACE})
  -c, --cluster <name>        Kind cluster name (default: ${CLUSTER_NAME})
  -i, --image <img:tag>       Shared image for Ray/API/bootstrap (default: ${SEEDCORE_IMAGE})
      --ray-image <img:tag>   Override Ray image only (default: ${RAY_IMAGE})
      --api-image <img:tag>   Override API image only (default: ${API_IMAGE})
      --bootstrap-image <img> Override bootstrap image only (default: ${BOOTSTRAP_IMAGE})
      --env-file <path>       Env file used by deploy scripts (default: ${ENV_FILE})
      --worker-replicas <n>   Ray worker replicas (default: ${WORKER_REPLICAS})
      --host-data-dir <path>  HostPath data dir (default: ${HOST_DATA_DIR})
      --skip-build            Skip ./build.sh
      --enable-ml             Build optional ML/local-AI layer and enable ML services
      --no-cache             Build without Docker cache
      --skip-load            Skip kind image loads in downstream scripts
      --skip-ingress         Skip ingress deployment
  -h, --help                  Show this help
EOF
}

require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: '$1' not found in PATH."
    exit 1
  }
}

log() {
  echo
  echo "============================================================"
  echo ">>> $1"
  echo "============================================================"
  echo
}

is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|y|Y|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--namespace) NAMESPACE="$2"; shift 2 ;;
    -c|--cluster) CLUSTER_NAME="$2"; shift 2 ;;
    -i|--image)
      SEEDCORE_IMAGE="$2"
      RAY_IMAGE="$2"
      API_IMAGE="$2"
      BOOTSTRAP_IMAGE="$2"
      shift 2
      ;;
    --ray-image) RAY_IMAGE="$2"; shift 2 ;;
    --api-image) API_IMAGE="$2"; shift 2 ;;
    --bootstrap-image) BOOTSTRAP_IMAGE="$2"; shift 2 ;;
    --env-file) ENV_FILE="$2"; shift 2 ;;
    --worker-replicas) WORKER_REPLICAS="$2"; shift 2 ;;
    --host-data-dir) HOST_DATA_DIR="$2"; shift 2 ;;
    --skip-build) BUILD_IMAGE=false; shift ;;
    --enable-ml)
      BUILD_ENABLE_ML=1
      DEPLOY_ENABLE_ML_SERVICE=1
      shift
      ;;
    --no-cache) BUILD_NO_CACHE=1; shift ;;
    --skip-load) SKIP_KIND_LOAD=true; shift ;;
    --skip-ingress) DEPLOY_INGRESS_ENABLED=false; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: Unknown argument '$1'"; usage; exit 1 ;;
  esac
done

# --------- Cross-platform disk availability ----------
# Returns available KB for a given path (default: current dir).
df_avail_kb() {
  local path="${1:-.}"
  if [[ "${SEEDCORE_OS}" == "darwin" ]]; then
    # BSD df (macOS): no --output=avail
    df -Pk "${path}" | tail -1 | awk '{print $4}'
  else
    # GNU df (Linux)
    df -Pk "${path}" | tail -1 | awk '{print $4}'
  fi
}

# Optional: enforce minimum free space (example: 8 GB)
check_disk_space() {
  local path="${1:-.}"
  local min_kb="${2:-8388608}" # 8GB in KB
  local avail_kb
  avail_kb="$(df_avail_kb "${path}")"

  if [[ -z "${avail_kb}" ]]; then
    echo "⚠️  Could not determine free disk space for '${path}'. Continuing..."
    return 0
  fi

  if (( avail_kb < min_kb )); then
    echo "ERROR: Not enough disk space on '${path}'. Need >= $((min_kb/1024/1024)) GB, have ~ $((avail_kb/1024/1024)) GB."
    exit 1
  fi
}

# --------- envsubst helper (macOS often missing) ----------
ensure_envsubst() {
  if command -v envsubst >/dev/null 2>&1; then
    return 0
  fi

  echo "⚠️  'envsubst' not found."
  echo "    On macOS, install via: brew install gettext && brew link --force gettext"
  echo "    Falling back to Python-based substitution for limited vars..."
  return 1
}

# Simple ${VAR} substitution fallback (only for variables you set in the environment)
envsubst_fallback() {
  python3 - <<'PY'
import os, re, sys
data = sys.stdin.read()
def repl(m):
  key = m.group(1)
  return os.environ.get(key, m.group(0))
sys.stdout.write(re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", repl, data))
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

build_docker_image() {
  log "Building Docker image"
  if ! is_true "${BUILD_IMAGE}"; then
    echo "ℹ️  Skipping Docker build (BUILD_IMAGE=${BUILD_IMAGE})"
    return 0
  fi

  (
    cd "${PROJECT_ROOT}"
    PLATFORM="${BUILD_PLATFORM}" \
    IMAGE_NAME="$(image_name_from_ref "${SEEDCORE_IMAGE}")" \
    IMAGE_TAG="$(image_tag_from_ref "${SEEDCORE_IMAGE}")" \
    DOCKERFILE="${BUILD_DOCKERFILE}" \
    ENABLE_ML="${BUILD_ENABLE_ML}" \
    NO_CACHE="${BUILD_NO_CACHE}" \
    LOAD_IMAGE=1 \
    ./build.sh
  )
}

start_kind_cluster() {
  log "Starting Kubernetes cluster (kind)"
  CLUSTER_NAME="${CLUSTER_NAME}" "${DEPLOY_DIR}/setup-kind-only.sh"
}

deploy_core_services() {
  log "Deploying core services (PostgreSQL, MySQL, Redis, Neo4j)"
  NAMESPACE="${NAMESPACE}" "${DEPLOY_DIR}/setup-cores.sh"
}

init_databases() {
  log "Initializing databases (schema + runtime registry)"
  "${DEPLOY_DIR}/init-databases.sh"
}

deploy_storage() {
  log "Deploying persistent storage"
  kubectl apply -f "${DEPLOY_DIR}/k8s/seedcore-data-pvc.yaml"
}

deploy_rbac() {
  log "Deploying RBAC and service account configuration"

  echo "📦 Deploying service account..."
  kubectl apply -f "${DEPLOY_DIR}/k8s/seedcore-serviceaccount.yaml"

  echo "📦 Deploying role binding..."
  kubectl apply -f "${DEPLOY_DIR}/k8s/seedcore-rolebinding.yaml"

  echo "📦 Deploying network policies..."
  kubectl apply -f "${DEPLOY_DIR}/k8s/allow-api-egress.yaml"
  kubectl apply -f "${DEPLOY_DIR}/k8s/allow-api-to-ray-serve.yaml"

  echo "📦 Deploying XGB storage PVC..."
  kubectl apply -f "${DEPLOY_DIR}/k8s/xgb-pvc.yaml"
}

deploy_ray_services() {
  log "Deploying Ray cluster and Ray Serve"
  CLUSTER_NAME="${CLUSTER_NAME}" \
  NAMESPACE="${NAMESPACE}" \
  RAY_IMAGE="${RAY_IMAGE}" \
  ENABLE_ML_SERVICE="${DEPLOY_ENABLE_ML_SERVICE}" \
  WORKER_REPLICAS="${WORKER_REPLICAS}" \
  RS_NAME="${RAYSERVICE_NAME}" \
  STABLE_SERVE_SVC_NAME="${STABLE_SERVICE_NAME}" \
  ENV_FILE_PATH="${ENV_FILE}" \
  HOST_DATA_DIR="${HOST_DATA_DIR}" \
  SKIP_LOAD="${SKIP_KIND_LOAD}" \
  "${DEPLOY_DIR}/setup-ray-serve.sh"

  echo "📦 Deploying stable Ray service..."
  kubectl apply -f "${DEPLOY_DIR}/ray-stable-svc.yaml"
}

deploy_pkg_policy() {
  log "Deploying PKG policy (WASM)"

  if [[ "${APPLY_PKG_WASM}" != "true" ]]; then
    echo "ℹ️  Skipping PKG WASM deployment (APPLY_PKG_WASM != true)"
    return 0
  fi

  # Export PKG version/env/activate for ingestion script
  export PKG_VERSION="${PKG_VERSION:-}"
  export PKG_ENV="${PKG_ENV:-prod}"
  export PKG_ACTIVATE="${PKG_ACTIVATE:-false}"

  if [[ -n "${PKG_WASM_FILE}" ]]; then
    echo "📦 Applying PKG WASM from ${PKG_WASM_FILE}"
    
    # Optional: Hard-fail in production if version is missing
    # (Uncomment the following block to enforce strict production requirements)
    # if [[ "${PKG_ENV}" == "prod" && -z "${PKG_VERSION}" ]]; then
    #   echo "❌ ERROR: PKG_VERSION is required when APPLY_PKG_WASM=true and PKG_ENV=prod"
    #   echo "   Set PKG_VERSION to enable DB ingestion (e.g., PKG_VERSION=rules@1.4.0)"
    #   exit 1
    # fi
    
    if [[ -n "${PKG_VERSION}" ]]; then
      echo "   Version: ${PKG_VERSION}"
      echo "   Env: ${PKG_ENV}"
      echo "   Activate: ${PKG_ACTIVATE}"
    else
      echo "   ⚠️  PKG_VERSION not set - file will be uploaded but not ingested into DB"
      echo "   Set PKG_VERSION to enable DB ingestion (e.g., PKG_VERSION=rules@1.4.0)"
    fi
    NAMESPACE="${NAMESPACE}" "${DEPLOY_DIR}/update-pkg-wasm.sh" "${PKG_WASM_FILE}"
  else
    echo "⚠️  APPLY_PKG_WASM=true but PKG_WASM_FILE not set"
    echo "    Falling back to dummy WASM (no DB ingestion)"
    NAMESPACE="${NAMESPACE}" "${DEPLOY_DIR}/update-pkg-wasm.sh"
  fi
}

bootstrap_components() {
  log "Bootstrapping organism and dispatchers"
  NAMESPACE="${NAMESPACE}" \
  RAY_IMAGE="${RAY_IMAGE}" \
  BOOTSTRAP_IMAGE="${BOOTSTRAP_IMAGE}" \
  RAYSERVICE_NAME="${RAYSERVICE_NAME}" \
  RAY_HEAD_SVC="${STABLE_SERVICE_NAME}" \
  TAIL_LOGS_ON_SUCCESS="${TAIL_BOOTSTRAP_LOGS}" \
  "${DEPLOY_DIR}/bootstrap.sh"
}

deploy_seedcore_api() {
  log "Deploying SeedCore API"
  CLUSTER_NAME="${CLUSTER_NAME}" \
  NAMESPACE="${NAMESPACE}" \
  API_IMAGE="${API_IMAGE}" \
  ENV_FILE="${ENV_FILE}" \
  RAY_HEAD_SVC="${STABLE_SERVICE_NAME}" \
  SKIP_LOAD="${SKIP_KIND_LOAD}" \
  "${DEPLOY_DIR}/deploy-seedcore-api.sh"
}

deploy_ingress() {
  log "Deploying ingress configuration"

  echo "⏳ Waiting for services to be ready..."
  kubectl wait --for=condition=available --timeout=300s deployment/seedcore-api -n "${NAMESPACE}" || true

  echo "📦 Deploying ingress configuration..."
  export NAMESPACE="${NAMESPACE}"
  export INGRESS_HOST="localhost"
  export SERVICE_NAME="seedcore-api"

  if ensure_envsubst; then
    envsubst < "${DEPLOY_DIR}/k8s/ingress-routing.yaml" | kubectl apply -f - || {
      echo "⚠️  Ingress deployment failed, continuing without ingress (OK for dev)"
    }
  else
    envsubst_fallback < "${DEPLOY_DIR}/k8s/ingress-routing.yaml" | kubectl apply -f - || {
      echo "⚠️  Ingress deployment failed, continuing without ingress (OK for dev)"
    }
  fi

  if [[ -f "${DEPLOY_DIR}/deploy-k8s-ingress.sh" ]]; then
    "${DEPLOY_DIR}/deploy-k8s-ingress.sh"
  else
    echo "⚠️  Ingress controller script not found, skipping"
  fi
}

main() {
  require docker
  require kind
  require kubectl
  require python3

  log "Starting full SeedCore deployment (OS=${SEEDCORE_OS})"
  echo "Namespace:        ${NAMESPACE}"
  echo "Cluster:          ${CLUSTER_NAME}"
  echo "Ray image:        ${RAY_IMAGE}"
  echo "API image:        ${API_IMAGE}"
  echo "Bootstrap image:  ${BOOTSTRAP_IMAGE}"
  echo "Build image:      ${BUILD_IMAGE}"
  echo "Enable ML build:  ${BUILD_ENABLE_ML}"
  echo "Enable ML serve:  ${DEPLOY_ENABLE_ML_SERVICE}"
  check_disk_space "${PROJECT_ROOT}" 8388608

  build_docker_image
  start_kind_cluster
  deploy_core_services
  init_databases
  deploy_storage
  deploy_rbac
  deploy_ray_services
  deploy_pkg_policy

  echo "⏳ Waiting for ${WAIT_FOR_RAY_S} seconds for Ray services to stabilize..."
  sleep "${WAIT_FOR_RAY_S}"

  bootstrap_components
  deploy_seedcore_api
  if is_true "${DEPLOY_INGRESS_ENABLED}"; then
    deploy_ingress
  else
    log "Skipping ingress deployment"
  fi

  log "SeedCore deployment completed successfully!"
}

main "$@"
