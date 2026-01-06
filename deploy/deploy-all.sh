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

build_docker_image() {
  log "Building Docker image"
  #(cd "${PROJECT_ROOT}" && ./build.sh)
}

start_kind_cluster() {
  log "Starting Kubernetes cluster (kind)"
  "${DEPLOY_DIR}/setup-kind-only.sh"
}

deploy_core_services() {
  log "Deploying core services (PostgreSQL, MySQL, Redis, Neo4j)"
  "${DEPLOY_DIR}/setup-cores.sh"
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
  "${DEPLOY_DIR}/setup-ray-serve.sh"

  echo "📦 Deploying stable Ray service..."
  kubectl apply -f "${DEPLOY_DIR}/ray-stable-svc.yaml"
}

bootstrap_components() {
  log "Bootstrapping organism and dispatchers"
  "${DEPLOY_DIR}/bootstrap.sh"
}

deploy_seedcore_api() {
  log "Deploying SeedCore API"
  "${DEPLOY_DIR}/deploy-seedcore-api.sh"
}

deploy_ingress() {
  log "Deploying ingress configuration"

  echo "⏳ Waiting for services to be ready..."
  kubectl wait --for=condition=available --timeout=300s deployment/seedcore-api -n seedcore-dev || true

  echo "📦 Deploying ingress configuration..."
  export NAMESPACE="seedcore-dev"
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
  check_disk_space "${PROJECT_ROOT}" 8388608

  build_docker_image
  start_kind_cluster
  deploy_core_services
  init_databases
  deploy_storage
  deploy_rbac
  deploy_ray_services

  echo "⏳ Waiting for 30 seconds for Ray services to stabilize..."
  sleep 30

  bootstrap_components
  deploy_seedcore_api
  deploy_ingress

  log "SeedCore deployment completed successfully!"
}

main "$@"
