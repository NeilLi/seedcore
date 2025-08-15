#!/bin/bash
set -euo pipefail

echo "🚀 Setting up Kind Cluster with Ray and Data Stores"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
print_status() {
  local status=$1; local message=$2
  if [ "$status" = "OK" ]; then echo -e "${GREEN}✅ $message${NC}"
  elif [ "$status" = "WARN" ]; then echo -e "${YELLOW}⚠️  $message${NC}"
  elif [ "$status" = "INFO" ]; then echo -e "${BLUE}ℹ️  $message${NC}"
  else echo -e "${RED}❌ $message${NC}"; fi
}

# --- Config (overridable via env/args) ---
CLUSTER_NAME="${CLUSTER_NAME:-seedcore-dev}"
NAMESPACE="${NAMESPACE:-seedcore-dev}"
RAY_VERSION="${RAY_VERSION:-2.33.0}"
RAY_IMAGE="${RAY_IMAGE:-seedcore-serve:latest}"   # << your image
WORKER_REPLICAS="${WORKER_REPLICAS:-1}"

# Optional CLI: setup-kind-ray.sh [namespace] [cluster_name] [image]
if [[ $# -ge 1 ]]; then NAMESPACE="$1"; fi
if [[ $# -ge 2 ]]; then CLUSTER_NAME="$2"; fi
if [[ $# -ge 3 ]]; then RAY_IMAGE="$3"; fi

# --- Tool checks ---
command -v kind >/dev/null || { print_status "ERROR" "kind is not installed."; exit 1; }
command -v kubectl >/dev/null || { print_status "ERROR" "kubectl is not installed."; exit 1; }
command -v helm >/dev/null || { print_status "ERROR" "helm is not installed."; exit 1; }

# --- Cluster lifecycle ---
echo "🔍 Checking existing cluster..."
if kind get clusters | grep -q "^${CLUSTER_NAME}\$"; then
  print_status "WARN" "Cluster ${CLUSTER_NAME} already exists"
  read -p "Do you want to delete and recreate it? (y/N): " -r REPLY; echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    print_status "INFO" "Deleting existing cluster..."
    kind delete cluster --name "$CLUSTER_NAME"
  else
    print_status "INFO" "Using existing cluster"
  fi
fi

# Create Kind cluster if needed
if ! kind get clusters | grep -q "^${CLUSTER_NAME}\$"; then
  print_status "INFO" "Creating Kind cluster with kindest/node:v1.30.0..."
  kind create cluster --name "$CLUSTER_NAME" --image kindest/node:v1.30.0 --config kind-config.yaml
  print_status "OK" "Kind cluster created successfully"
fi

# Set context
print_status "INFO" "Setting kubectl context..."
kubectl cluster-info --context "kind-$CLUSTER_NAME"

# Namespace
print_status "INFO" "Creating namespace $NAMESPACE..."
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

# --- Check for docker/.env and apply Ray-only Kustomize if available ---
# This only deploys RayCluster (not API/Serve deployments)
# The seedcore-env ConfigMap is created directly from docker/.env in the script
KUSTOMIZE_DIR="${KUSTOMIZE_DIR:-deploy/kustomize/ray-only}"

if [ ! -f "docker/.env" ]; then
  print_status "ERROR" "docker/.env not found. Create it (copy from env.example) before running setup."
  exit 1
fi

# Always create/update the seedcore-env ConfigMap from docker/.env first
print_status "INFO" "Creating/updating seedcore-env ConfigMap from docker/.env..."
kubectl -n "$NAMESPACE" create configmap seedcore-env \
  --from-env-file=docker/.env \
  --dry-run=client -o yaml | kubectl apply -f -
print_status "OK" "ConfigMap seedcore-env created/updated successfully"

# Now apply Ray-only Kustomize if available
if [ -d "$KUSTOMIZE_DIR" ]; then
  print_status "INFO" "Applying Ray-only Kustomize at $KUSTOMIZE_DIR (RayCluster only)..."
  kubectl apply -k "$KUSTOMIZE_DIR" -n "$NAMESPACE"
  print_status "OK" "Ray-only Kustomize applied successfully"
else
  print_status "WARN" "Ray-only Kustomize not found; will use inline RayCluster manifest."
fi

# --- Load your Ray image into Kind nodes ---
print_status "INFO" "Loading image ${RAY_IMAGE} into Kind cluster ${CLUSTER_NAME}..."
kind load docker-image "${RAY_IMAGE}" --name "${CLUSTER_NAME}"
print_status "OK" "Image loaded into Kind nodes"

# Create and set permissions for the data directory on the host
print_status "INFO" "Setting up /data directory on host for Ray cluster..."
sudo mkdir -p /tmp/seedcore-data
sudo chown -R 1000:1000 /tmp/seedcore-data
sudo chmod -R 755 /tmp/seedcore-data
print_status "OK" "Host data directory /tmp/seedcore-data created with proper permissions"

# --- KubeRay operator ---
print_status "INFO" "Installing/Upgrading KubeRay operator..."
helm repo add kuberay https://ray-project.github.io/kuberay-helm/ >/dev/null 2>&1 || true
helm repo update >/dev/null
if ! kubectl get namespace kuberay-system >/dev/null 2>&1; then
  helm install kuberay-operator kuberay/kuberay-operator \
    --namespace kuberay-system --create-namespace --wait
  print_status "OK" "KubeRay operator installed"
else
  if ! kubectl get pods -n kuberay-system -l app.kubernetes.io/name=kuberay-operator --no-headers | grep -q Running; then
    helm upgrade kuberay-operator kuberay/kuberay-operator --namespace kuberay-system --wait
  fi
  print_status "OK" "KubeRay operator is running"
fi

print_status "INFO" "Waiting for KubeRay operator to be ready..."
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=kuberay-operator -n kuberay-system --timeout=300s

# --- Deploy RayCluster using YOUR image for head & workers (name=seedcore => seedcore-head-svc) ---
print_status "INFO" "Deploying Ray cluster (image: ${RAY_IMAGE})..."

# Check if we already applied via Kustomize
if [ -d "$KUSTOMIZE_DIR" ] && kubectl get raycluster seedcore -n "$NAMESPACE" >/dev/null 2>&1; then
  print_status "INFO" "RayCluster already deployed via Kustomize, checking if image update is needed..."
  
  # Get current head image
  CURRENT_IMAGE=$(kubectl get raycluster seedcore -n "$NAMESPACE" -o jsonpath='{.spec.headGroupSpec.template.spec.containers[0].image}')
  
  if [ "$CURRENT_IMAGE" != "${RAY_IMAGE}" ]; then
    print_status "INFO" "Updating RayCluster head image from $CURRENT_IMAGE to ${RAY_IMAGE}..."
    # Only update the head image, keep workers as rayproject/ray for compatibility
    cat <<EOF | kubectl patch raycluster seedcore -n "$NAMESPACE" --type='merge' -p -
{
  "spec": {
    "headGroupSpec": {
      "template": {
        "spec": {
          "containers": [
            {
              "name": "ray-head",
              "image": "${RAY_IMAGE}"
            }
          ]
        }
      }
    }
  }
}
EOF
    print_status "OK" "RayCluster head image updated to ${RAY_IMAGE}"
  else
    print_status "INFO" "RayCluster head image is already ${RAY_IMAGE}, no update needed"
  fi
else
  print_status "INFO" "Deploying RayCluster using inline manifest..."
  cat <<EOF | kubectl apply -n "${NAMESPACE}" -f -
apiVersion: ray.io/v1
kind: RayCluster
metadata:
  name: seedcore
spec:
  rayVersion: "${RAY_VERSION}"
  headGroupSpec:
    serviceType: ClusterIP
    rayStartParams:
      dashboard-host: "0.0.0.0"
      dashboard-port: "8265"
      ray-client-server-port: "10001"
      num-cpus: "1"
    template:
      spec:
        # Add initContainer to fix /data permissions
        initContainers:
        - name: volume-permission-fix
          image: busybox
          command: ['sh', '-c', 'chown -R 1000:1000 /data && chmod -R 755 /data']
          volumeMounts:
          - name: data-volume
            mountPath: /data
        containers:
          - name: ray-head
            image: "${RAY_IMAGE}"
            imagePullPolicy: IfNotPresent
            volumeMounts:
            - name: data-volume
              mountPath: /data
            resources:
              requests:
                cpu: "1000m"
                memory: "2Gi"
              limits:
                cpu: "2000m"
                memory: "4Gi"
        # Define the data volume
        volumes:
        - name: data-volume
          hostPath:
            path: /tmp/seedcore-data
            type: DirectoryOrCreate
  workerGroupSpecs:
    - groupName: small
      replicas: ${WORKER_REPLICAS}
      minReplicas: ${WORKER_REPLICAS}
      maxReplicas: ${WORKER_REPLICAS}
      rayStartParams:
        num-cpus: "1"
      template:
        spec:
          # Add initContainer to fix /data permissions
          initContainers:
          - name: volume-permission-fix
            image: busybox
            command: ['sh', '-c', 'chown -R 1000:1000 /data && chmod -R 755 /data']
            volumeMounts:
            - name: data-volume
              mountPath: /data
          containers:
            - name: ray-worker
              image: "${RAY_IMAGE}"
              imagePullPolicy: IfNotPresent
              volumeMounts:
              - name: data-volume
                mountPath: /data
              resources:
                requests:
                  cpu: "750m"
                  memory: "3Gi"
                limits:
                  cpu: "1500m"
                  memory: "3Gi"
          # Define the data volume
          volumes:
          - name: data-volume
            hostPath:
              path: /tmp/seedcore-data
              type: DirectoryOrCreate
EOF
  print_status "OK" "RayCluster deployed using inline manifest"
fi

# --- Wait for head pod Ready ---
print_status "INFO" "Waiting for Ray head pod to be ready..."
kubectl wait --for=condition=ready pod -l ray.io/node-type=head -n "$NAMESPACE" --timeout=300s

# --- Show Ray cluster status ---
print_status "INFO" "Ray cluster objects:"
kubectl get raycluster -n "$NAMESPACE"
print_status "INFO" "Ray pods:"
kubectl get pods -n "$NAMESPACE" -l ray.io/cluster=seedcore

# --- Services (note: head service name remains seedcore-head-svc) ---
print_status "INFO" "Ray services:"
kubectl get svc -n "$NAMESPACE" | grep seedcore || true

# --- Connectivity test using YOUR image (robust Job-based) ---
print_status "INFO" "Testing Ray cluster connection (using ${RAY_IMAGE})..."

# Clean up any prior job
kubectl -n "$NAMESPACE" delete job/ray-smoke --ignore-not-found >/dev/null 2>&1 || true

# Create a one-shot Job that retries connect for ~30s
cat <<EOF | kubectl apply -n "$NAMESPACE" -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: ray-smoke
spec:
  backoffLimit: 0
  activeDeadlineSeconds: 120
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: test
        image: "${RAY_IMAGE}"
        imagePullPolicy: IfNotPresent
        command: ["/bin/bash","-lc"]
        args:
        - |
          python - <<'PY'
          import os, sys, time
          import ray
          ns = os.environ.get("NS", "seedcore-dev")
          addr = "ray://seedcore-head-svc:10001"
          for i in range(10):
              try:
                  ray.init(address=addr, namespace=ns)
                  print("✅ Ray cluster connected successfully!")
                  print("📊 Cluster resources:", ray.cluster_resources())
                  ray.shutdown()
                  sys.exit(0)
              except Exception as e:
                  print(f"[ray-smoke] attempt {i+1}/10 failed: {e}")
                  time.sleep(3)
          sys.exit(1)
          PY
        env:
        - name: NS
          value: "${NAMESPACE}"
EOF

# Wait for the Job to complete, show logs, and clean up
if kubectl -n "$NAMESPACE" wait --for=condition=complete job/ray-smoke --timeout=120s; then
  kubectl -n "$NAMESPACE" logs job/ray-smoke --tail=200
  kubectl -n "$NAMESPACE" delete job/ray-smoke --ignore-not-found >/dev/null 2>&1 || true
  print_status "OK" "Ray cluster connection test passed"
else
  kubectl -n "$NAMESPACE" logs job/ray-smoke --tail=200 || true
  print_status "ERROR" "Ray cluster connection test failed"
  exit 1
fi

# --- Helm repos for data stores (add/update before install) ---
print_status "INFO" "Adding/Updating Helm repos for data stores..."
helm repo add bitnami https://charts.bitnami.com/bitnami >/dev/null 2>&1 || true
helm repo add neo4j https://helm.neo4j.com/neo4j >/dev/null 2>&1 || true
helm repo add grafana https://grafana.github.io/helm-charts >/dev/null 2>&1 || true
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo update >/dev/null

# --- Data Stores ---
print_status "INFO" "Deploying data stores (PostgreSQL, MySQL, Redis, Neo4j)..."
print_status "INFO" "This may take several minutes..."

print_status "INFO" "Deploying PostgreSQL with pgvector..."
helm upgrade --install postgresql ./helm/postgresql \
  --namespace "$NAMESPACE" --wait --timeout 10m

print_status "INFO" "Deploying MySQL..."
helm upgrade --install mysql ./helm/mysql \
  --namespace "$NAMESPACE" --wait --timeout 10m

print_status "INFO" "Deploying Redis (Bitnami)..."
helm upgrade --install redis bitnami/redis \
  --namespace "$NAMESPACE" \
  --set auth.enabled=false \
  --set master.persistence.size=512Mi \
  --set master.resources.requests.cpu=50m \
  --set master.resources.requests.memory=64Mi \
  --wait --timeout 10m

print_status "INFO" "Deploying Neo4j..."
helm upgrade --install neo4j neo4j/neo4j \
  --namespace "$NAMESPACE" --wait --timeout 10m \
  --set neo4j.name=neo4j \
  --set neo4j.password=password \
  --set neo4j.resources.requests.cpu=500m \
  --set neo4j.resources.requests.memory=2Gi \
  --set neo4j.resources.limits.cpu=1000m \
  --set neo4j.resources.limits.memory=4Gi \
  --set neo4j.volumeSize=2Gi \
  --set volumes.data.mode=defaultStorageClass \
  --set services.neo4j.enabled=false \
  --set loadbalancer=exclude

# --- Verify ---
print_status "INFO" "Verifying all services are running..."
kubectl get pods -n "$NAMESPACE"

print_status "INFO" "Checking data store services..."
kubectl get svc -n "$NAMESPACE"

echo
print_status "OK" "🎉 Kind cluster with Ray (using ${RAY_IMAGE}) and Data Stores setup completed!"
echo
echo "📊 Cluster Status:"
echo "   - Kind Cluster: $CLUSTER_NAME"
echo "   - Namespace: $NAMESPACE"
echo "   - Ray Head Svc: seedcore-head-svc (ports: 10001 Ray Client, 8265 Dashboard, 8000 HTTP if you run Serve here)"
echo "   - Data Directory: /tmp/seedcore-data (mounted as /data in containers)"
echo
echo "🔧 Useful Commands:"
echo "   - Check cluster: kubectl cluster-info --context kind-$CLUSTER_NAME"
echo "   - List pods:     kubectl get pods -n $NAMESPACE"
echo "   - Dashboard:     kubectl -n $NAMESPACE port-forward svc/seedcore-head-svc 8265:8265"
echo "   - Ray client:    kubectl -n $NAMESPACE port-forward svc/seedcore-head-svc 10001:10001"
echo "   - Serve HTTP:    kubectl -n $NAMESPACE port-forward svc/seedcore-head-svc 8001:8000"
echo "   - Check data dir: ls -la /tmp/seedcore-data"
echo "   - Delete cluster: kind delete cluster --name $CLUSTER_NAME"
echo
echo "🌐 Data Store Endpoints:"
echo "   - PostgreSQL: postgresql.$NAMESPACE.svc.cluster.local:5432"
echo "   - MySQL:      mysql.$NAMESPACE.svc.cluster.local:3306"
echo "   - Redis:      redis-master.$NAMESPACE.svc.cluster.local:6379"
echo "   - Neo4j:      neo4j.$NAMESPACE.svc.cluster.local:7687"
echo
echo "🔑 Default Credentials:"
echo "   - PostgreSQL: postgres/password"
echo "   - MySQL:      seedcore/password"
echo "   - Neo4j:      neo4j/password"
echo "   - Redis:      no authentication"
echo
echo "🚀 Next steps:"
echo "   1) Run Serve on the Ray head (RayService or Ray Job) using the same image."
echo "   2) Port-forward head svc and hit your API: curl http://127.0.0.1:8001/health"
echo "   3) Monitor: kubectl -n $NAMESPACE get pods -w"
