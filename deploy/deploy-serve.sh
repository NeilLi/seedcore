#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# SeedCore Serve - Deploy to Kubernetes (Kind-friendly)
#
# - Verifies tools (kubectl, kind, docker)
# - Ensures namespace exists
# - Loads local image into the correct Kind cluster
# - Waits for Ray head service and data stores (Postgres, MySQL, Redis, Neo4j)
# - Deploys/updates seedcore-serve with sensible probes & resources
# - Prints status and handy commands
#
# Usage:
#   ./deploy-seedcore-serve.sh [NAMESPACE] [KIND_CLUSTER_NAME] [IMAGE_NAME]
#
# Defaults:
#   NAMESPACE="seedcore-dev"
#   KIND_CLUSTER_NAME="seedcore-dev"   # matches your setup-kind-ray.sh
#   IMAGE_NAME="seedcore-serve:latest"
###############################################################################

# --------------------------
# Config / Defaults
# --------------------------
NAMESPACE="${1:-seedcore-dev}"
KIND_CLUSTER_NAME="${2:-seedcore-dev}"
IMAGE_NAME="${3:-seedcore-serve:latest}"

APP_NAME="seedcore-serve"             # base name for labels
DEPLOY_NAME="seedcore-serve-dev"
SVC_NAME="seedcore-serve-dev"

RAY_SVC="seedcore-head-svc"
RAY_PORT="10001"

# Data store service names (ClusterIP DNS within the namespace)
PG_HOST="postgresql";   PG_PORT="5432"
MYSQL_HOST="mysql";     MYSQL_PORT="3306"
REDIS_HOST="redis-master"; REDIS_PORT="6379"
NEO4J_HOST="neo4j";     NEO4J_PORT="7687"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() {
  local level="$1"; shift
  local msg="$*"
  case "$level" in
    OK)   echo -e "${GREEN}✅ ${msg}${NC}" ;;
    WARN) echo -e "${YELLOW}⚠️  ${msg}${NC}" ;;
    INFO) echo -e "${BLUE}ℹ️  ${msg}${NC}" ;;
    *)    echo -e "${RED}❌ ${msg}${NC}" ;;
  esac
}

require_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || { print_status ERROR "Missing required command: $cmd"; exit 1; }
}

# --------------------------
# Preflight
# --------------------------
print_status INFO "Starting SeedCore Serve deployment"

require_cmd kubectl
require_cmd kind
require_cmd docker

# Show context info
CURRENT_CTX="$(kubectl config current-context || true)"
print_status INFO "kubectl current context: ${CURRENT_CTX:-<none>}"

# Ensure Kind cluster exists
if ! kind get clusters | grep -qx "$KIND_CLUSTER_NAME"; then
  print_status ERROR "Kind cluster \"$KIND_CLUSTER_NAME\" not found. Create it or pass the correct name."
  exit 1
fi
print_status OK "Kind cluster \"$KIND_CLUSTER_NAME\" is available"

# Ensure namespace exists (idempotent)
if kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
  print_status OK "Namespace \"$NAMESPACE\" exists"
else
  print_status WARN "Namespace \"$NAMESPACE\" not found; creating..."
  kubectl create namespace "$NAMESPACE"
  print_status OK "Namespace \"$NAMESPACE\" created"
fi

# Verify local image exists
print_status INFO "Checking for local image \"$IMAGE_NAME\"..."
if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
  print_status ERROR "Image \"$IMAGE_NAME\" not found locally."
  echo "Build it first:"
  echo "  docker build -f docker/Dockerfile.serve -t seedcore-serve:latest ."
  exit 1
fi
print_status OK "Local image \"$IMAGE_NAME\" found"

# Load image into Kind (only if not present on nodes)
print_status INFO "Loading \"$IMAGE_NAME\" into Kind cluster \"$KIND_CLUSTER_NAME\"..."
kind load docker-image "$IMAGE_NAME" --name "$KIND_CLUSTER_NAME"
print_status OK "Image loaded into Kind"

# --------------------------
# Cluster dependency checks
# --------------------------
# Quick function to wait for a Service to exist
wait_service() {
  local ns="$1" name="$2" timeout="${3:-120s}"
  kubectl -n "$ns" wait --for=condition=available "deployment/$name" --timeout=1s >/dev/null 2>&1 && return 0 || true
  # If it's not a deployment we still want the Service object to exist
  local start=$(date +%s)
  while true; do
    if kubectl -n "$ns" get svc "$name" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
    if (( $(date +%s) - start > ${timeout%s} )); then
      return 1
    fi
  done
}

# Wait for TCP readiness from inside the cluster (busybox with nc)
# This avoids relying on host network reachability.
wait_tcp_in_cluster() {
  local ns="$1" host="$2" port="$3" label="$4" timeout="${5:-120}" # seconds
  print_status INFO "Waiting for ${label} at ${host}:${port} (up to ${timeout}s)..."
  # One-off pod that exits after the check
  # Using --rm requires interactive; here we create and delete explicitly to be CI-friendly.
  local pod="netcheck-$(tr -dc 'a-z0-9' </dev/urandom | head -c6)"
  kubectl -n "$ns" run "$pod" --restart='Never' --image=busybox:1.36 --overrides='{"spec":{"terminationGracePeriodSeconds":0}}' -- sh -c \
    "i=0; until nc -z ${host} ${port}; do i=\$((i+1)); if [ \$i -ge ${timeout} ]; then echo TIMEOUT; exit 1; fi; sleep 1; done; echo OK" >/tmp/"$pod".log 2>&1 || true

  if kubectl -n "$ns" wait --for=condition=Ready pod/"$pod" --timeout=10s >/dev/null 2>&1; then
    :
  fi

  # Read the result and clean up
  kubectl -n "$ns" logs "$pod" >/tmp/"$pod".log 2>/dev/null || true
  local result=""; result="$(cat /tmp/"$pod".log 2>/dev/null || echo)"
  kubectl -n "$ns" delete pod "$pod" --ignore-not-found >/dev/null 2>&1 || true
  if echo "$result" | grep -q "OK"; then
    print_status OK "${label} is reachable"
    return 0
  else
    print_status WARN "Could not reach ${label} (${host}:${port}). Last output:"
    echo "$result"
    return 1
  fi
}

# Check Ray head service and port
if kubectl -n "$NAMESPACE" get svc "$RAY_SVC" >/dev/null 2>&1; then
  print_status OK "Ray Service \"$RAY_SVC\" exists"
  wait_tcp_in_cluster "$NAMESPACE" "$RAY_SVC" "$RAY_PORT" "Ray Head (GCS/Serve) port"
else
  print_status WARN "Ray Service \"$RAY_SVC\" not found in \"$NAMESPACE\" (continuing)"
fi

# Data store checks (by service + TCP reachability)
declare -A STORES=(
  ["PostgreSQL"]="$PG_HOST:$PG_PORT"
  ["MySQL"]="$MYSQL_HOST:$MYSQL_PORT"
  ["Redis"]="$REDIS_HOST:$REDIS_PORT"
  ["Neo4j"]="$NEO4J_HOST:$NEO4J_PORT"
)

for name in "${!STORES[@]}"; do
  host="${STORES[$name]%:*}"
  port="${STORES[$name]#*:}"
  if kubectl -n "$NAMESPACE" get svc "$host" >/dev/null 2>&1; then
    print_status OK "$name service \"$host\" present"
    wait_tcp_in_cluster "$NAMESPACE" "$host" "$port" "$name"
  else
    print_status WARN "$name service \"$host\" missing (continuing)"
  fi
done

# --------------------------
# Apply Deployment + Service
# --------------------------
print_status INFO "Applying ${DEPLOY_NAME} resources to namespace \"$NAMESPACE\"..."

cat <<EOF | kubectl -n "$NAMESPACE" apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${DEPLOY_NAME}
  labels:
    app.kubernetes.io/name: ${APP_NAME}
    app.kubernetes.io/instance: ${DEPLOY_NAME}
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: ${APP_NAME}
      app.kubernetes.io/instance: ${DEPLOY_NAME}
  template:
    metadata:
      labels:
        app.kubernetes.io/name: ${APP_NAME}
        app.kubernetes.io/instance: ${DEPLOY_NAME}
    spec:
      terminationGracePeriodSeconds: 30
      # Wait for core dependencies before starting the app
      initContainers:
      - name: wait-deps
        image: busybox:1.36
        imagePullPolicy: IfNotPresent
        env:
        - { name: PG_HOST,      value: "${PG_HOST}" }
        - { name: PG_PORT,      value: "${PG_PORT}" }
        - { name: MYSQL_HOST,   value: "${MYSQL_HOST}" }
        - { name: MYSQL_PORT,   value: "${MYSQL_PORT}" }
        - { name: REDIS_HOST,   value: "${REDIS_HOST}" }
        - { name: REDIS_PORT,   value: "${REDIS_PORT}" }
        - { name: NEO4J_HOST,   value: "${NEO4J_HOST}" }
        - { name: NEO4J_PORT,   value: "${NEO4J_PORT}" }
        - { name: RAY_SVC,      value: "${RAY_SVC}" }
        - { name: RAY_PORT,     value: "${RAY_PORT}" }
        command: ["sh","-lc"]
        args:
          - |
            set -e
            echo "Waiting for dependencies..."
            for target in "\$PG_HOST:\$PG_PORT" "\$MYSQL_HOST:\$MYSQL_PORT" "\$REDIS_HOST:\$REDIS_PORT" "\$NEO4J_HOST:\$NEO4J_PORT" "\$RAY_SVC:\$RAY_PORT"; do
              host=\${target%:*}; port=\${target#*:}
              i=0; until nc -z "\$host" "\$port"; do
                i=\$((i+1))
                if [ \$i -ge 180 ]; then
                  echo "Timeout waiting for \$host:\$port"; exit 1
                fi
                sleep 1
              done
              echo "OK: \$host:\$port"
            done
      containers:
      - name: serve
        image: ${IMAGE_NAME}
        imagePullPolicy: IfNotPresent
        env:
        - { name: RAY_ADDRESS,      value: "ray://${RAY_SVC}:${RAY_PORT}" }
        - { name: RAY_NAMESPACE,    value: "${NAMESPACE}" }
        - { name: SEEDCORE_NS,      value: "${NAMESPACE}" }
        - { name: SERVE_HTTP_HOST,  value: "0.0.0.0" }
        - { name: SERVE_HTTP_PORT,  value: "8000" }
        - { name: PYTHONPATH,       value: "/app:/app/src" }
        # Database connections
        - { name: PG_DSN,               value: "postgresql://postgres:password@${PG_HOST}:${PG_PORT}/postgres" }
        - { name: MYSQL_DATABASE_URL,   value: "mysql+mysqlconnector://seedcore:password@${MYSQL_HOST}:${MYSQL_PORT}/seedcore" }
        - { name: REDIS_HOST,           value: "${REDIS_HOST}" }
        - { name: REDIS_PORT,           value: "${REDIS_PORT}" }
        - { name: NEO4J_URI,            value: "bolt://${NEO4J_HOST}:${NEO4J_PORT}" }
        - { name: NEO4J_USER,           value: "neo4j" }
        - { name: NEO4J_PASSWORD,       value: "password" }
        ports:
        - { name: http, containerPort: 8000 }
        resources:
          requests:
            cpu: "200m"
            memory: "256Mi"
          limits:
            cpu: "1"
            memory: "512Mi"
        # Give the app time to start before liveness kicks in
        startupProbe:
          httpGet:
            path: /health
            port: http
          failureThreshold: 30
          periodSeconds: 2
        readinessProbe:
          httpGet:
            path: /health
            port: http
          initialDelaySeconds: 10
          periodSeconds: 5
          timeoutSeconds: 2
          failureThreshold: 12
        livenessProbe:
          httpGet:
            path: /health
            port: http
          initialDelaySeconds: 60
          periodSeconds: 20
          timeoutSeconds: 2
          failureThreshold: 6
---
apiVersion: v1
kind: Service
metadata:
  name: ${SVC_NAME}
  labels:
    app.kubernetes.io/name: ${APP_NAME}
    app.kubernetes.io/instance: ${DEPLOY_NAME}
spec:
  selector:
    app.kubernetes.io/name: ${APP_NAME}
    app.kubernetes.io/instance: ${DEPLOY_NAME}
  ports:
  - name: http
    port: 80
    targetPort: http
  type: ClusterIP
EOF

print_status OK "Manifests applied"

# --------------------------
# Wait and show status
# --------------------------
print_status INFO "Waiting for deployment/${DEPLOY_NAME} to be Available..."
kubectl -n "$NAMESPACE" rollout status deployment/"$DEPLOY_NAME" --timeout=300s

print_status OK "Deployment is Available"

print_status INFO "Deployment summary:"
kubectl -n "$NAMESPACE" get deploy "$DEPLOY_NAME" -o wide

print_status INFO "Pods:"
kubectl -n "$NAMESPACE" get pods -l app.kubernetes.io/instance="$DEPLOY_NAME" -o wide

print_status INFO "Service:"
kubectl -n "$NAMESPACE" get svc "$SVC_NAME" -o wide

print_status INFO "Recent logs (serve container):"
kubectl -n "$NAMESPACE" logs deploy/"$DEPLOY_NAME" --tail=80 || true

echo ""
print_status OK "🎉 ${DEPLOY_NAME} deployment completed!"
echo ""
echo "📊 Deployment Status:"
echo "   - Namespace: $NAMESPACE"
echo "   - Deployment: ${DEPLOY_NAME}"
echo "   - Service: ${SVC_NAME}"
echo "   - Port: 80 (ClusterIP)"
echo ""
echo "🔧 Useful Commands:"
echo "   - Watch pods: kubectl -n $NAMESPACE get pods -w"
echo "   - Follow logs: kubectl -n $NAMESPACE logs deploy/${DEPLOY_NAME} -f"
echo "   - Port forward: kubectl -n $NAMESPACE port-forward svc/${SVC_NAME} 8001:80"
echo "   - Test health (port-forwarded): curl http://127.0.0.1:8001/health"
echo "   - In-cluster health check:"
echo "       kubectl -n $NAMESPACE exec -it \$(kubectl -n $NAMESPACE get pod -l app.kubernetes.io/instance=${DEPLOY_NAME} -o jsonpath='{.items[0].metadata.name}') -- \\"
echo "         sh -lc 'wget -qO- http://127.0.0.1:8000/health || curl -fsS http://127.0.0.1:8000/health'"
echo ""
echo "🚀 Next steps:"
echo "   1. Validate Ray connectivity from the pod: "
echo "        kubectl -n $NAMESPACE exec -it \$(kubectl -n $NAMESPACE get pod -l app.kubernetes.io/instance=${DEPLOY_NAME} -o jsonpath='{.items[0].metadata.name}') -- \\"
echo "          python -c 'import ray; ray.init(\"ray://${RAY_SVC}:${RAY_PORT}\"); print(ray.cluster_resources())'"
echo "   2. Run a small inference/test request against your service once Ready."
echo "   3. Consider moving secrets (DB passwords, etc.) into Kubernetes Secrets for production."
