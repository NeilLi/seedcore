#!/usr/bin/env bash
# SeedCore Deployment Orchestrator
# Runs full pipeline: build -> kind -> databases -> storage -> Ray -> bootstrap -> API

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Since script is now in deploy/ directory, project root is parent
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEPLOY_DIR="${SCRIPT_DIR}"

require() {
  command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' not found in PATH."; exit 1; }
}

log() {
  echo
  echo "============================================================"
  echo ">>> $1"
  echo "============================================================"
  echo
}

build_docker_image() {
  log "Building Docker image"
  (cd "${PROJECT_ROOT}" && ./build.sh)
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
  
  # Apply service account
  echo "📦 Deploying service account..."
  kubectl apply -f "${DEPLOY_DIR}/k8s/seedcore-serviceaccount.yaml"
  
  # Apply role binding
  echo "📦 Deploying role binding..."
  kubectl apply -f "${DEPLOY_DIR}/k8s/seedcore-rolebinding.yaml"
  
  # Apply network policies
  echo "📦 Deploying network policies..."
  kubectl apply -f "${DEPLOY_DIR}/k8s/allow-api-egress.yaml"
  kubectl apply -f "${DEPLOY_DIR}/k8s/allow-api-to-ray-serve.yaml"
  
  # Apply XGB PVC for Ray storage
  echo "📦 Deploying XGB storage PVC..."
  kubectl apply -f "${DEPLOY_DIR}/k8s/xgb-pvc.yaml"
}

deploy_ray_services() {
  log "Deploying Ray cluster and Ray Serve"
  "${DEPLOY_DIR}/setup-ray-serve.sh"
  
  # Apply stable Ray service for ingress routing
  echo "📦 Deploying stable Ray service..."
  kubectl apply -f "${DEPLOY_DIR}/ray-stable-svc.yaml"
}

bootstrap_components() {
  log "Bootstrapping organism and dispatchers"
  "${DEPLOY_DIR}/bootstrap_organism.sh"
  "${DEPLOY_DIR}/bootstrap_dispatchers.sh"
}

deploy_seedcore_api() {
  log "Deploying SeedCore API"
  "${DEPLOY_DIR}/deploy-seedcore-api.sh"
}

deploy_ingress() {
  log "Deploying ingress configuration"
  
  # Wait for services to be ready
  echo "⏳ Waiting for services to be ready..."
  kubectl wait --for=condition=available --timeout=300s deployment/seedcore-api -n seedcore-dev || true
  
  # Deploy ingress with substituted variables (optional for dev)
  echo "📦 Deploying ingress configuration..."
  NAMESPACE="seedcore-dev"
  INGRESS_HOST="localhost"
  SERVICE_NAME="seedcore-api"
  
  if envsubst < "${DEPLOY_DIR}/k8s/ingress-routing.yaml" | kubectl apply -f -; then
    echo "✅ Ingress configuration deployed successfully"
  else
    echo "⚠️  Ingress deployment failed, continuing without ingress (OK for dev)"
  fi
  
  # Deploy ingress controller (optional)
  if [[ -f "${DEPLOY_DIR}/deploy-k8s-ingress.sh" ]]; then
    "${DEPLOY_DIR}/deploy-k8s-ingress.sh"
  else
    echo "⚠️  Ingress controller script not found, skipping"
  fi
}

main() {
  # quick prereq check
  require docker
  require kind
  require kubectl

  log "Starting full SeedCore deployment"
  build_docker_image
  start_kind_cluster
  deploy_core_services
  init_databases
  deploy_storage
  deploy_rbac
  deploy_ray_services
  bootstrap_components
  deploy_seedcore_api
  deploy_ingress
  log "SeedCore deployment completed successfully!"
}

main "$@"
