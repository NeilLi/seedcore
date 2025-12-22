#!/usr/bin/env bash
# deploy/deploy-seedcore-api.sh — SeedCore API deployer for Kind/Kubernetes
set -euo pipefail

# Resolve script directory for robust relative paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- Colors / status
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log() { local lvl=$1 msg=$2; case "$lvl" in
  OK) echo -e "${GREEN}✅ $msg${NC}";;
  WARN) echo -e "${YELLOW}⚠️  $msg${NC}";;
  INFO) echo -e "${BLUE}ℹ️  $msg${NC}";;
  ERR) echo -e "${RED}❌ $msg${NC}";;
esac; }

# ---- Defaults (env-overridable)
CLUSTER_NAME="${CLUSTER_NAME:-seedcore-dev}"
NAMESPACE="${NAMESPACE:-seedcore-dev}"
SERVICE_NAME="${SERVICE_NAME:-seedcore-api}"
DEPLOY_NAME="${DEPLOY_NAME:-seedcore-api}"
API_IMAGE="${API_IMAGE:-seedcore:latest}"
REPLICAS="${REPLICAS:-1}"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/../docker/.env}"
ENV_MODE="${ENV_MODE:-auto}"                 # auto|cm|secret|file
SKIP_LOAD="${SKIP_LOAD:-0}"
PORT_FORWARD="${PORT_FORWARD:-0}"
LOCAL_PORT="${LOCAL_PORT:-8002}"

# Normalize boolean-ish env vars to 0/1
case "${SKIP_LOAD}" in
  1|true|TRUE|yes|YES|y|Y) SKIP_LOAD=1 ;;
  0|false|FALSE|no|NO|n|N|"") SKIP_LOAD=0 ;;
  *) echo "Invalid SKIP_LOAD='${SKIP_LOAD}' (use 0/1/true/false)"; exit 1 ;;
esac

case "${PORT_FORWARD}" in
  1|true|TRUE|yes|YES|y|Y) PORT_FORWARD=1 ;;
  0|false|FALSE|no|NO|n|N|"") PORT_FORWARD=0 ;;
  *) echo "Invalid PORT_FORWARD='${PORT_FORWARD}' (use 0/1/true/false)"; exit 1 ;;
esac

# Ray + misc
RAY_HEAD_SVC="${RAY_HEAD_SVC:-seedcore-svc-head-svc}"
RAY_HEAD_PORT="${RAY_HEAD_PORT:-10001}"
SEEDCORE_NS="${SEEDCORE_NS:-seedcore-dev}"
HOSTPATH_PROJECT="${HOSTPATH_PROJECT:-/project}"

YAML_PATH="${YAML_PATH:-${SCRIPT_DIR}/k8s/seedcore-api.yaml}"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [options]
  -n, --namespace <ns>       Namespace (default: $NAMESPACE)
  -c, --cluster <name>       Kind cluster (default: $CLUSTER_NAME)
  -i, --image <img:tag>      API image (default: $API_IMAGE)
  -e, --env <path>           .env file for fallback ConfigMap (default: $ENV_FILE)
  -r, --replicas <n>         Replicas (default: $REPLICAS)
      --skip-load            Skip 'kind load docker-image'
      --port-forward         Port-forward svc/${SERVICE_NAME} to localhost:${LOCAL_PORT}
      --env-mode <m>         Env wiring: auto|cm|secret|file (default: $ENV_MODE)
      --delete               Delete resources and exit
  -y, --yaml <path>          Path to templated YAML (default: $YAML_PATH)
  -h, --help                 Help
USAGE
}

DELETE_ONLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--namespace) NAMESPACE="$2"; shift 2;;
    -c|--cluster) CLUSTER_NAME="$2"; shift 2;;
    -i|--image) API_IMAGE="$2"; shift 2;;
    -e|--env) ENV_FILE="$2"; shift 2;;
    -r|--replicas) REPLICAS="$2"; shift 2;;
    --skip-load) SKIP_LOAD=1; shift;;
    --port-forward) PORT_FORWARD=1; shift;;
    --env-mode) ENV_MODE="$2"; shift 2;;
    --delete) DELETE_ONLY=1; shift;;
    -y|--yaml) YAML_PATH="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) log ERR "Unknown arg: $1"; usage; exit 1;;
  esac
done

log INFO "NS=$NAMESPACE | cluster=kind-$CLUSTER_NAME | image=$API_IMAGE | env-mode=$ENV_MODE"

# ---- Tool checks
command -v kubectl >/dev/null || { log ERR "kubectl not found"; exit 1; }
if [[ "${SKIP_LOAD:-0}" -eq 0 ]]; then command -v kind >/dev/null || { log ERR "kind not found (or set SKIP_LOAD=1)"; exit 1; }; fi
command -v envsubst >/dev/null || { log ERR "envsubst not found (install gettext)"; exit 1; }

# ---- Smart Kind image load (uses kind get nodes + ctr, works on Debian/Ubuntu/macOS)
smart_kind_load() {
  local img="$1" cluster="$2"
  [[ "$SKIP_LOAD" -eq 1 ]] && return 0
  
  # Get actual Kind node names dynamically (works regardless of naming scheme)
  local nodes; nodes=$(kind get nodes --name "$cluster" 2>/dev/null || :)
  if [[ -z "$nodes" ]]; then
    log WARN "Kind cluster '$cluster' not found. Skipping image load."
    return 0
  fi
  
  # Verify local image exists
  if ! docker inspect "$img" >/dev/null 2>&1; then
    log ERR "Local image '$img' not found. Build it first."
    exit 1
  fi
  
  # Prepare alternative image name (kind/containerd often uses docker.io/library/ prefix)
  local alt_img="$img"
  if [[ "$img" != */* ]]; then
    alt_img="docker.io/library/$img"
  fi
  
  # Check if image exists on all nodes using ctr (always available in kindest/node)
  local node_has_image=true
  if [[ -z "$nodes" ]]; then
    node_has_image=false
  else
    for node in $nodes; do
      if docker exec "$node" sh -lc "
        refs=\$(ctr -n k8s.io images ls -q 2>/dev/null || true)
        echo \"\$refs\" | grep -Fxq '${alt_img}' || echo \"\$refs\" | grep -Fxq '${img}'
      " >/dev/null 2>&1; then
        : # present
      else
        node_has_image=false
        break
      fi
    done
  fi
  
  if [[ "$node_has_image" == "true" ]]; then
    log INFO "Image already present on all Kind nodes; skip load."
  else
    log INFO "Loading image $img into Kind cluster $cluster ..."
    kind load docker-image "$img" --name "$cluster"
    log OK "Image loaded into Kind nodes"
  fi
}

# ---- Namespace ensure
kubectl get ns "$NAMESPACE" >/dev/null 2>&1 || {
  log INFO "Creating namespace $NAMESPACE ..."
  kubectl create namespace "$NAMESPACE"
  log OK "Namespace ensured"
}

# ---- Delete path
if [[ "$DELETE_ONLY" -eq 1 ]]; then
  log INFO "Deleting API resources in $NAMESPACE..."
  kubectl -n "$NAMESPACE" delete deploy/"$DEPLOY_NAME" svc/"$SERVICE_NAME" configmap/"$SERVICE_NAME"-config --ignore-not-found
  log OK "Deleted (if existed)."; exit 0
fi

# ---- Decide env wiring (auto/cm/secret/file)
use_shared_cm=false; use_client_cm=false; use_secret=false; use_file_cm=false
if [[ "$ENV_MODE" == "cm" ]]; then
  use_shared_cm=true; use_client_cm=true
elif [[ "$ENV_MODE" == "secret" ]]; then
  use_secret=true
elif [[ "$ENV_MODE" == "file" ]]; then
  use_file_cm=true
else
  # auto
  if kubectl -n "$NAMESPACE" get configmap seedcore-env >/dev/null 2>&1; then
    use_shared_cm=true
  fi
  if kubectl -n "$NAMESPACE" get configmap seedcore-client-env >/dev/null 2>&1; then
    use_client_cm=true
  fi
  if [[ "$use_shared_cm" != "true" ]] && [[ "$use_client_cm" != "true" ]]; then
    if kubectl -n "$NAMESPACE" get secret seedcore-env-secret >/dev/null 2>&1; then
      use_secret=true
    else
      use_file_cm=true
    fi
  fi
fi

# ---- Create/Update env sources when needed
if [[ "$use_shared_cm" == "true" ]] && [[ -f "$ENV_FILE" ]]; then
  log INFO "Updating shared ConfigMap seedcore-env from $ENV_FILE ..."
  kubectl -n "$NAMESPACE" create configmap seedcore-env --from-env-file="$ENV_FILE" -o yaml --dry-run=client | kubectl apply -f -
  log OK "ConfigMap seedcore-env updated"
fi

if [[ "$use_file_cm" == "true" ]]; then
  if [[ -f "$ENV_FILE" ]]; then
    log INFO "Creating/Updating ${SERVICE_NAME}-config from $ENV_FILE ..."
    kubectl -n "$NAMESPACE" create configmap "${SERVICE_NAME}-config" --from-env-file="$ENV_FILE" -o yaml --dry-run=client | kubectl apply -f -
    log OK "ConfigMap ${SERVICE_NAME}-config updated"
  else
    log WARN "Env file '$ENV_FILE' not found; continuing without fallback config."
  fi
fi

# ---- Smart image load
smart_kind_load "$API_IMAGE" "$CLUSTER_NAME"

# ---- Render + apply YAML
export NAMESPACE SERVICE_NAME DEPLOY_NAME API_IMAGE REPLICAS \
       RAY_HEAD_SVC RAY_HEAD_PORT SEEDCORE_NS HOSTPATH_PROJECT
log INFO "Applying ${YAML_PATH} ..."
tmpfile="$(mktemp)"; envsubst < "${YAML_PATH}" > "$tmpfile"
kubectl apply -f "$tmpfile"
rm -f "$tmpfile"

# ---- Rollout + info
log INFO "Waiting for Deployment rollout ..."
kubectl -n "$NAMESPACE" rollout status deploy/"$DEPLOY_NAME" --timeout=180s || :

log INFO "Pods:"
kubectl -n "$NAMESPACE" get pods -l app="${SERVICE_NAME}" -o wide || :

log INFO "Service:"
kubectl -n "$NAMESPACE" get svc "${SERVICE_NAME}" || :

echo
log OK "API deployed as svc/${SERVICE_NAME} in ns/${NAMESPACE}"
echo "  - Tail logs:    kubectl -n ${NAMESPACE} logs deploy/${DEPLOY_NAME} -f --tail=200"
echo "  - Exec shell:   kubectl -n ${NAMESPACE} exec -it deploy/${DEPLOY_NAME} -- /bin/bash || /bin/sh"
echo "  - Port-forward: kubectl -n ${NAMESPACE} port-forward svc/${SERVICE_NAME} ${LOCAL_PORT}:8002"
echo "  - Health:       curl -sf http://127.0.0.1:${LOCAL_PORT}/health || :"
echo "  - Ready:        curl -si http://127.0.0.1:${LOCAL_PORT}/readyz | head -n1"
echo "  - Delete:       $(basename "$0") --delete -n ${NAMESPACE}"
echo

if [[ "$PORT_FORWARD" -eq 1 ]]; then
  log INFO "Starting port-forward on localhost:${LOCAL_PORT} (Ctrl+C to stop)..."
  kubectl -n "$NAMESPACE" port-forward svc/${SERVICE_NAME} ${LOCAL_PORT}:8002
fi

