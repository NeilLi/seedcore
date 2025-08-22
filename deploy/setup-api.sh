#!/usr/bin/env bash
# setup-api.sh — Standalone API Deployment to Kind/Kubernetes
# Minimal, manual-ops friendly. Matches style of your Ray setup script.
set -euo pipefail

# ------------------------------
# Colors & status
# ------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
print_status() {
  local status=$1; local message=$2
  if [ "$status" = "OK" ]; then echo -e "${GREEN}✅ $message${NC}"
  elif [ "$status" = "WARN" ]; then echo -e "${YELLOW}⚠️  $message${NC}"
  elif [ "$status" = "INFO" ]; then echo -e "${BLUE}ℹ️  $message${NC}"
  else echo -e "${RED}❌ $message${NC}"; fi
}

# ------------------------------
# Config (env-overridable, + flags)
# ------------------------------
CLUSTER_NAME="${CLUSTER_NAME:-seedcore-dev}"
NAMESPACE="${NAMESPACE:-seedcore-dev}"
SERVICE_NAME="${SERVICE_NAME:-seedcore-api}"
DEPLOY_NAME="${DEPLOY_NAME:-seedcore-api}"
API_IMAGE="${API_IMAGE:-seedcore-api:kind}"     # build/tag locally, then load to kind
REPLICAS="${REPLICAS:-1}"
ENV_FILE="${ENV_FILE:-../docker/.env}"          # optional; used only if no shared ConfigMap/Secret
SKIP_LOAD="${SKIP_LOAD:-0}"                     # 1 = skip 'kind load docker-image'
PORT_FORWARD="${PORT_FORWARD:-0}"               # 1 = auto port-forward after deploy
LOCAL_PORT="${LOCAL_PORT:-8002}"                # local port for port-forward

# Env wiring mode (auto detects by default):
#   auto  -> prefer shared Kustomize resources if present (seedcore-env + seedcore-client-env),
#            else fall back to service-specific ConfigMap from ENV_FILE,
#            else if Secret 'seedcore-env-secret' exists, use it.
#   cm    -> force use of seedcore-env (+ optional seedcore-client-env if present)
#   secret-> force use of seedcore-env-secret
#   file  -> force create/use ${SERVICE_NAME}-config from ENV_FILE
ENV_MODE="${ENV_MODE:-auto}"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [options]
  -n, --namespace <ns>     Namespace (default: $NAMESPACE)
  -c, --cluster <name>     Kind cluster name (default: $CLUSTER_NAME)
  -i, --image <img:tag>    API image to deploy (default: $API_IMAGE)
  -e, --env <path>         .env file to load (fallback ConfigMap) (default: $ENV_FILE)
  -r, --replicas <n>       Replica count (default: $REPLICAS)
      --skip-load          Skip 'kind load docker-image'
      --port-forward       Port-forward service to localhost:\$LOCAL_PORT
      --env-mode <m>       Env wiring: auto|cm|secret|file (default: $ENV_MODE)
      --delete             Delete the API Deployment/Service/ConfigMap and exit
  -h, --help               Show this help
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
    -h|--help) usage; exit 0;;
    --) shift; break;;
    *) echo "Unknown arg: $1"; usage; exit 1;;
  esac
done

print_status INFO "Namespace: $NAMESPACE | Cluster: kind-$CLUSTER_NAME | Image: $API_IMAGE | EnvMode: $ENV_MODE"

# ------------------------------
# Tool checks
# ------------------------------
command -v kubectl >/dev/null || { print_status ERROR "kubectl is not installed"; exit 1; }
if [[ "$SKIP_LOAD" -eq 0 ]]; then
  command -v kind >/dev/null || { print_status ERROR "kind is not installed (or set SKIP_LOAD=1)"; exit 1; }
fi

# ------------------------------
# Smart image load (avoid disk bloat)
# ------------------------------
smart_kind_load() {
  local img="$1" cluster="$2"
  if [[ "$SKIP_LOAD" -eq 1 ]]; then return 0; fi
  if ! kind get clusters | grep -q "^${cluster}\$"; then
    print_status WARN "Kind cluster '$cluster' not found. Skipping image load."
    return 0
  fi
  local digest
  if ! digest=$(docker inspect --format='{{.Id}}' "$img" 2>/dev/null); then
    print_status ERROR "Local image '$img' not found. Build it first."; exit 1
  fi
  for n in $(kind get nodes --name "$cluster"); do
    if docker exec "$n" ctr -n k8s.io images ls | grep -q "$digest"; then
      print_status INFO "Image already present on $n (digest match); skipping load."
      return 0
    fi
  done
  print_status INFO "Loading image ${img} into Kind cluster ${cluster}..."
  kind load docker-image "${img}" --name "${cluster}"
  print_status OK "Image loaded into Kind nodes"
}

smart_kind_load "$API_IMAGE" "$CLUSTER_NAME"

# ------------------------------
# Ensure namespace
# ------------------------------
print_status INFO "Creating namespace $NAMESPACE (if not exists)..."
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

# ------------------------------
# Delete path
# ------------------------------
if [[ "$DELETE_ONLY" -eq 1 ]]; then
  print_status INFO "Deleting API resources in $NAMESPACE..."
  kubectl -n "$NAMESPACE" delete deploy/"$DEPLOY_NAME" svc/"$SERVICE_NAME" configmap/"$SERVICE_NAME"-config --ignore-not-found
  print_status OK "Deleted (if existed)."
  exit 0
fi

# ------------------------------
# Decide env wiring
# ------------------------------
use_shared_cm=false
use_client_cm=false
use_secret=false
use_file_cm=false

if [[ "$ENV_MODE" == "cm" ]]; then
  use_shared_cm=true
  use_client_cm=true
elif [[ "$ENV_MODE" == "secret" ]]; then
  use_secret=true
elif [[ "$ENV_MODE" == "file" ]]; then
  use_file_cm=true
else
  # auto-detect
  if kubectl -n "$NAMESPACE" get configmap seedcore-env >/dev/null 2>&1; then
    use_shared_cm=true
  fi
  if kubectl -n "$NAMESPACE" get configmap seedcore-client-env >/dev/null 2>&1; then
    use_client_cm=true
  fi
  if ! $use_shared_cm && ! $use_client_cm; then
    if kubectl -n "$NAMESPACE" get secret seedcore-env-secret >/dev/null 2>&1; then
      use_secret=true
    else
      use_file_cm=true
    fi
  fi
fi

# Update shared ConfigMap if in use
if $use_shared_cm && [[ -f "$ENV_FILE" ]]; then
  print_status INFO "Updating seedcore-env from $ENV_FILE ..."
  kubectl -n "$NAMESPACE" create configmap seedcore-env \
    --from-env-file="$ENV_FILE" \
    -o yaml --dry-run=client | kubectl apply -f -
  print_status OK "ConfigMap 'seedcore-env' updated"

  # Optional: trigger pods to reload envs
  # kubectl -n "$NAMESPACE" rollout restart deployment "$SERVICE_NAME"
fi

# Create fallback ConfigMap from ENV_FILE if needed
if $use_file_cm; then
  if [[ -f "$ENV_FILE" ]]; then
    print_status INFO "Creating/Updating ConfigMap from $ENV_FILE ..."
    kubectl -n "$NAMESPACE" create configmap "$SERVICE_NAME"-config \
      --from-env-file="$ENV_FILE" \
      --dry-run=client -o yaml | kubectl apply -f -
    print_status OK "ConfigMap '$SERVICE_NAME-config' updated"
  else
    print_status WARN "Env file '$ENV_FILE' not found; continuing with no env injection."
  fi
fi

# ------------------------------
# Build envFrom YAML fragments (safe)
# ------------------------------
env_from_yaml=""
if $use_shared_cm; then
  env_from_yaml="${env_from_yaml}
            - configMapRef:
                name: seedcore-env"
fi
if $use_client_cm; then
  env_from_yaml="${env_from_yaml}
            - configMapRef:
                name: seedcore-client-env"
fi
if $use_secret; then
  env_from_yaml="${env_from_yaml}
            - secretRef:
                name: seedcore-env-secret"
fi
if $use_file_cm; then
  env_from_yaml="${env_from_yaml}
            - configMapRef:
                name: ${SERVICE_NAME}-config"
fi

ENV_FROM_BLOCK=""
if [[ -n "${env_from_yaml// /}" ]]; then
  ENV_FROM_BLOCK="          envFrom:${env_from_yaml}"
fi

# ------------------------------
# Apply Deployment + Service
# ------------------------------
print_status INFO "Applying Deployment and Service..."
cat <<EOF | kubectl apply -n "$NAMESPACE" -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${DEPLOY_NAME}
  labels: { app: ${SERVICE_NAME} }
spec:
  replicas: ${REPLICAS}
  selector:
    matchLabels: { app: ${SERVICE_NAME} }
  template:
    metadata:
      labels: { app: ${SERVICE_NAME} }
    spec:
      containers:
        - name: ${SERVICE_NAME}
          image: ${API_IMAGE}
          imagePullPolicy: IfNotPresent
          ports:
            - name: http
              containerPort: 8002
          env:
            - { name: DSP_LOG_TO_FILE,  value: "false" }
            - { name: DSP_LOG_TO_STDOUT, value: "true" }
            - { name: TMPDIR, value: "/tmp" }
            - { name: TEMP,  value: "/tmp" }
            - { name: RAY_ADDRESS, value: "ray://seedcore-svc-head-svc:10001" }
            - { name: SEEDCORE_NS, value: "seedcore-dev" }
${ENV_FROM_BLOCK}
          volumeMounts:
            - name: logs-volume
              mountPath: /tmp/seedcore-logs
            # <<< ADD THIS MOUNT FOR YOUR PROJECT CODE
            - name: project-source-volume
              mountPath: /app
      volumes:
        - name: logs-volume
          emptyDir: {}
        # <<< ADD THIS VOLUME DEFINITION FOR YOUR PROJECT CODE
        - name: project-source-volume
          hostPath:
            path: /project # This MUST match the containerPath from your kind-config.yaml
            type: Directory
---
apiVersion: v1
kind: Service
metadata:
  name: ${SERVICE_NAME}
  labels: { app: ${SERVICE_NAME} }
spec:
  type: ClusterIP
  selector: { app: ${SERVICE_NAME} }
  ports:
    - name: http
      port: 8002
      targetPort: 8002
EOF

# ------------------------------
# Rollout & info
# ------------------------------
print_status INFO "Waiting for Deployment rollout (give it a moment)..."
kubectl -n "$NAMESPACE" rollout status deploy/"$DEPLOY_NAME" --timeout=180s || true

print_status INFO "Pods:"
kubectl -n "$NAMESPACE" get pods -l app="${SERVICE_NAME}" -o wide || true

print_status INFO "Service:"
kubectl -n "$NAMESPACE" get svc "${SERVICE_NAME}" || true

echo
print_status OK "Standalone API deployed as service '${SERVICE_NAME}' in namespace '${NAMESPACE}'"
echo
echo "🔧 Manual operations:"
echo "  - Tail logs:    kubectl -n ${NAMESPACE} logs deploy/${DEPLOY_NAME} -f --tail=200"
echo "  - Exec shell:   kubectl -n ${NAMESPACE} exec -it deploy/${DEPLOY_NAME} -- /bin/bash || /bin/sh"
echo "  - Port-forward: kubectl -n ${NAMESPACE} port-forward svc/${SERVICE_NAME} ${LOCAL_PORT}:8002"
echo "  - Health check: curl -sf http://127.0.0.1:${LOCAL_PORT}/health || true"
echo "  - Delete:       $(basename "$0") --delete -n ${NAMESPACE}"
echo

# Optional: auto port-forward
if [[ "$PORT_FORWARD" -eq 1 ]]; then
  print_status INFO "Starting port-forward on localhost:${LOCAL_PORT} (Ctrl+C to stop)..."
  kubectl -n "$NAMESPACE" port-forward svc/${SERVICE_NAME} ${LOCAL_PORT}:8002
fi
