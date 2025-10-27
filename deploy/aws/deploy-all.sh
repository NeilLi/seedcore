#!/usr/bin/env bash
# Deploy All SeedCore Services to EKS
# Deploys all Kubernetes manifests to the EKS cluster

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

# Load environment variables
load_env() {
    local env_file="${SCRIPT_DIR}/.env.aws"
    
    if [ ! -f "$env_file" ]; then
        error "Environment file not found: $env_file"
        echo "Please run ./aws-init.sh first to set up the environment"
        exit 1
    fi
    
    log "Loading environment variables from $env_file"
    # Ensure variables are exported so envsubst can see them
    set -a
    source "$env_file"
    set +a
}

# Check if kubectl is configured
check_kubectl() {
    log "Checking kubectl configuration..."
    
    if ! kubectl cluster-info &> /dev/null; then
        error "kubectl is not configured or cluster is not accessible"
        echo "Please run ./aws-init.sh first to set up the cluster"
        exit 1
    fi
    
    local current_context=$(kubectl config current-context)
    log "Current kubectl context: $current_context"
    
    success "kubectl is configured correctly"
}

# Create namespace if it doesn't exist
create_namespace() {
    log "Creating namespace: $NAMESPACE"
    
    if kubectl get namespace "$NAMESPACE" &> /dev/null; then
        log "Namespace $NAMESPACE already exists"
    else
        kubectl create namespace "$NAMESPACE"
    fi
    
    success "Namespace created successfully"
}

# Deploy RBAC
deploy_rbac() {
    log "Deploying RBAC configuration..."
    
    envsubst < "${SCRIPT_DIR}/rbac.yaml" | kubectl apply -f -
    
    success "RBAC configuration deployed successfully"
}

# Deploy storage
deploy_storage() {
    log "Deploying persistent storage..."
    
    # Create a dedicated storage deployment file
    cat > "${SCRIPT_DIR}/storage-deployment.yaml" << EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: seedcore-data-pvc
  namespace: \${NAMESPACE}
  labels:
    app: seedcore
    component: storage
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: \${STORAGE_CLASS}
  resources:
    requests:
      storage: 50Gi
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: xgb-pvc
  namespace: \${NAMESPACE}
  labels:
    app: seedcore
    component: storage
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: \${STORAGE_CLASS}
  resources:
    requests:
      storage: 20Gi
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: nim-model-pvc
  namespace: \${NAMESPACE}
  labels:
    app: nim-retrieval
    component: storage
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: \${STORAGE_CLASS}
  resources:
    requests:
      storage: 50Gi
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: nim-llama-model-pvc
  namespace: \${NAMESPACE}
  labels:
    app: nim-llama
    component: storage
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: \${STORAGE_CLASS}
  resources:
    requests:
      storage: 100Gi
EOF
    
    # Apply storage resources
    envsubst < "${SCRIPT_DIR}/storage-deployment.yaml" | kubectl apply -f -
    
    # Clean up generated file
    rm -f "${SCRIPT_DIR}/storage-deployment.yaml"
    
    success "Persistent storage deployed successfully"
}

# Create environment resources
create_env_resources() {
    log "Creating environment resources from env.example..."
    
    "${SCRIPT_DIR}/create-env-resources.sh" create
    
    success "Environment resources created successfully"
}

# Deploy databases
deploy_databases() {
    log "Deploying database services..."
    
    # Check if deployments exist with old selectors (immutable field issue)
    local need_selector_update=false
    if kubectl get deployment postgresql -n "$NAMESPACE" &>/dev/null; then
        local existing_label=$(kubectl get deployment postgresql -n "$NAMESPACE" -o jsonpath='{.spec.selector.matchLabels.app\.kubernetes\.io/name}' 2>/dev/null || echo "")
        if [ -z "$existing_label" ]; then
            need_selector_update=true
        fi
    fi
    
    if [ "$need_selector_update" = true ]; then
        log "Deployments have old selectors without app.kubernetes.io/name labels."
        log "Deleting existing database deployments to allow selector updates (PVCs preserved)..."
        kubectl delete deployment postgresql mysql neo4j redis -n "$NAMESPACE" 2>/dev/null || log "No existing deployments to delete"
        log "Waiting for deletions to complete..."
        sleep 5
    fi
    
    log "Applying database deployments..."
    envsubst < "${SCRIPT_DIR}/database-deployment.yaml" | kubectl apply -f -
    
    # Wait for databases to be ready
    log "Waiting for databases to be ready..."
    kubectl wait --for=condition=available --timeout=300s deployment/postgresql -n "$NAMESPACE" || true
    kubectl wait --for=condition=available --timeout=300s deployment/mysql -n "$NAMESPACE" || true
    kubectl wait --for=condition=available --timeout=300s deployment/neo4j -n "$NAMESPACE" || true
    kubectl wait --for=condition=available --timeout=300s deployment/redis -n "$NAMESPACE" || true
    
    success "Database services deployed successfully"
}

# Deploy Ray service
deploy_ray_service() {
    log "Deploying Ray service..."
    
    envsubst < "${SCRIPT_DIR}/rayservice-deployment.yaml" | kubectl apply -f -
    
    # Wait for Ray service to be ready
    log "Waiting for Ray service to be ready..."
    kubectl wait --for=condition=available --timeout=600s rayservice/seedcore-svc -n "$NAMESPACE" || true
    
    success "Ray service deployed successfully"
}

# Deploy SeedCore API
deploy_seedcore_api() {
    log "Deploying SeedCore API..."
    
    envsubst < "${SCRIPT_DIR}/seedcore-deployment.yaml" | kubectl apply -f -
    
    # Wait for API to be ready
    log "Waiting for SeedCore API to be ready..."
    kubectl wait --for=condition=available --timeout=300s deployment/seedcore-api -n "$NAMESPACE" || true
    
    success "SeedCore API deployed successfully"
}

# Deploy NIM services
deploy_nim_services() {
    log "Deploying NIM services..."
    
    # Create NIM secrets if they don't exist (optional, placeholder)
    log "Creating NIM secrets..."
    
    # NIM Retrieval Secret (placeholder - update with actual values)
    if ! kubectl get secret nim-retrieval-secret -n "$NAMESPACE" &> /dev/null; then
        kubectl create secret generic nim-retrieval-secret \
            --from-literal=model_api_key="placeholder" \
            --from-literal=encryption_key="placeholder" \
            --dry-run=client -o yaml | kubectl apply -f - &> /dev/null || true
        log "Created nim-retrieval-secret"
    fi
    
    # NIM Llama Secret (placeholder - update with actual values)
    if ! kubectl get secret nim-llama-secret -n "$NAMESPACE" &> /dev/null; then
        kubectl create secret generic nim-llama-secret \
            --from-literal=model_api_key="placeholder" \
            --from-literal=encryption_key="placeholder" \
            --dry-run=client -o yaml | kubectl apply -f - &> /dev/null || true
        log "Created nim-llama-secret"
    fi
    
    # Deploy NIM Retrieval
    log "Deploying NIM Retrieval service..."
    envsubst < "${SCRIPT_DIR}/nim-retrieval-deployment.yaml" | kubectl apply -f -
    
    # Deploy NIM Llama
    log "Deploying NIM Llama service..."
    envsubst < "${SCRIPT_DIR}/nim-llama-deployment.yaml" | kubectl apply -f -
    
    # Wait for NIM services to be ready
    log "Waiting for NIM services to be ready..."
    kubectl wait --for=condition=available --timeout=300s deployment/nim-retrieval -n "$NAMESPACE" || {
        warn "NIM Retrieval deployment did not become available. Check logs:"
        kubectl logs -n "$NAMESPACE" -l app=nim-retrieval --tail=50 || true
    }
    
    # NIM Llama has GPU requirements, skip if not available
    if kubectl get nodes -l node-type=gpu &> /dev/null; then
        kubectl wait --for=condition=available --timeout=300s deployment/nim-llama -n "$NAMESPACE" || {
            warn "NIM Llama deployment did not become available (may need GPU nodes). Check logs:"
            kubectl logs -n "$NAMESPACE" -l app=nim-llama --tail=50 || true
        }
    else
        warn "No GPU nodes found. NIM Llama will not be deployed."
        kubectl delete deployment nim-llama -n "$NAMESPACE" 2>/dev/null || true
    fi
    
    # Show NIM service status
    log "NIM Services Status:"
    kubectl get deployment,pod,svc -n "$NAMESPACE" -l app=nim-retrieval || true
    kubectl get deployment,pod,svc -n "$NAMESPACE" -l app=nim-llama 2>/dev/null || true
    
    success "NIM services deployed successfully"
}

# Deploy ingress
deploy_ingress() {
    log "Deploying ingress configuration..."
    
    envsubst < "${SCRIPT_DIR}/ingress.yaml" | kubectl apply -f -
    
    success "Ingress configuration deployed successfully"
}

# Initialize databases
init_databases() {
    log "Initializing databases..."
    
    # Wait for databases to be fully ready
    log "Waiting for databases to be fully ready..."
    kubectl wait --for=condition=ready pod -l app=postgresql -n "$NAMESPACE" --timeout=300s || true
    kubectl wait --for=condition=ready pod -l app=mysql -n "$NAMESPACE" --timeout=300s || true
    kubectl wait --for=condition=ready pod -l app=neo4j -n "$NAMESPACE" --timeout=300s || true
    kubectl wait --for=condition=ready pod -l app=redis -n "$NAMESPACE" --timeout=300s || true
    
    # Additional wait for database services to be stable
    log "Waiting for database services to stabilize..."
    sleep 30
    
    # Check if initialization scripts exist
    local init_script="${SCRIPT_DIR}/../init-databases.sh"
    local basic_init="${SCRIPT_DIR}/../init_basic_db.sh"
    
    if [ -f "$init_script" ]; then
        log "Running database initialization script: $init_script"
        
        # Export required environment variables for the init scripts
        export NAMESPACE="$NAMESPACE"
        export POSTGRES_USER="${POSTGRES_USER:-postgres}"
        export POSTGRES_DB="${POSTGRES_DB:-postgres}"
        export MYSQL_ROOT_USER="${MYSQL_ROOT_USER:-root}"
        export MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:-password}"
        export NEO4J_USER="${NEO4J_USER:-neo4j}"
        export NEO4J_PASSWORD="${NEO4J_PASSWORD:-password}"
        export NEO4J_DB="${NEO4J_DB:-neo4j}"
        export PG_SELECTOR="app.kubernetes.io/name=postgresql"
        export MYSQL_SELECTOR="app.kubernetes.io/name=mysql"
        export NEO4J_SELECTOR="app=neo4j"
        export TIMEOUT="300s"
        
        # Run the initialization script
        bash "$init_script"
        
        # Alternative: Run basic initialization directly
    elif [ -f "$basic_init" ]; then
        log "Running basic database initialization script: $basic_init"
        
        # Export environment variables
        export NAMESPACE="$NAMESPACE"
        export POSTGRES_USER="${POSTGRES_USER:-postgres}"
        export POSTGRES_DB="${POSTGRES_DB:-postgres}"
        export MYSQL_ROOT_USER="${MYSQL_ROOT_USER:-root}"
        export MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:-password}"
        export NEO4J_USER="${NEO4J_USER:-neo4j}"
        export NEO4J_PASSWORD="${NEO4J_PASSWORD:-password}"
        export NEO4J_DB="${NEO4J_DB:-neo4j}"
        export PG_SELECTOR="app.kubernetes.io/name=postgresql"
        export MYSQL_SELECTOR="app.kubernetes.io/name=mysql"
        export NEO4J_SELECTOR="app=neo4j"
        export TIMEOUT="300s"
        
        # Run basic initialization
        bash "$basic_init" "$NAMESPACE"
        
        # Also run full database initialization if available
        local full_init="${SCRIPT_DIR}/../init_full_db.sh"
        if [ -f "$full_init" ]; then
            log "Running comprehensive database initialization script: $full_init"
            bash "$full_init"
        fi
    else
        warn "Database initialization scripts not found. Skipping..."
        warn "Expected scripts at: $init_script or $basic_init"
    fi
    
    success "Database initialization completed"
}

# Bootstrap components (matches original deploy-seedcore.sh)
bootstrap_components() {
    log "Bootstrapping organism and dispatchers"
    
    # Deploy organism bootstrap
    log "Deploying organism bootstrap..."
    "${SCRIPT_DIR}/bootstrap_organism.sh"
    
    # Deploy dispatchers bootstrap
    log "Deploying dispatchers bootstrap..."
    "${SCRIPT_DIR}/bootstrap_dispatchers.sh"
    
    success "Bootstrap components completed successfully"
}

# Deploy bootstrap jobs
deploy_bootstrap_jobs() {
    log "Deploying bootstrap jobs..."
    
    # Create bootstrap job manifests for AWS deployment
    create_bootstrap_jobs
    
    # Deploy organism bootstrap job
    log "Deploying organism bootstrap job..."
    envsubst < "${SCRIPT_DIR}/bootstrap-organism-job.yaml" | kubectl apply -f -
    
    # Wait for organism bootstrap to complete
    log "Waiting for organism bootstrap to complete..."
    kubectl wait --for=condition=complete job/seedcore-bootstrap-organism -n "$NAMESPACE" --timeout=600s || {
        warn "Organism bootstrap job did not complete successfully."
        kubectl logs job/seedcore-bootstrap-organism -n "$NAMESPACE" || true
    }
    
    # Deploy dispatchers bootstrap job
    log "Deploying dispatchers bootstrap job..."
    envsubst < "${SCRIPT_DIR}/bootstrap-dispatchers-job.yaml" | kubectl apply -f -
    
    # Wait for dispatchers bootstrap to complete
    log "Waiting for dispatchers bootstrap to complete..."
    kubectl wait --for=condition=complete job/seedcore-bootstrap-dispatchers -n "$NAMESPACE" --timeout=600s || {
        warn "Dispatchers bootstrap job did not complete successfully."
        kubectl logs job/seedcore-bootstrap-dispatchers -n "$NAMESPACE" || true
    }
    
    success "Bootstrap jobs completed successfully"
}

# Create bootstrap job manifests for AWS deployment
create_bootstrap_jobs() {
    log "Creating bootstrap job manifests for AWS deployment..."
    
    # Create organism bootstrap job
    cat > "${SCRIPT_DIR}/bootstrap-organism-job.yaml" << EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: seedcore-bootstrap-organism
  namespace: \${NAMESPACE}
  labels:
    app: seedcore
    component: bootstrap-organism
spec:
  completions: 1
  parallelism: 1
  backoffLimit: 3
  template:
    metadata:
      labels:
        app: seedcore
        component: bootstrap-organism
    spec:
      serviceAccountName: seedcore-service-account
      restartPolicy: Never
      containers:
      - name: bootstrap-organism
        image: \${ECR_REPO}:\${SEEDCORE_IMAGE_TAG}
        imagePullPolicy: Always
        command: ["python", "/app/bootstraps/bootstrap_entry.py"]
        env:
        # Tell the entrypoint to only init the organism and exit
        - name: BOOTSTRAP_MODE
          value: "organism"
        - name: EXIT_AFTER_BOOTSTRAP
          value: "true"

        # Ray connectivity
        - name: RAY_ADDRESS
          value: "ray://\${RAY_HEAD_SVC}:\${RAY_HEAD_PORT}"
        - name: RAY_NAMESPACE
          value: "\${SEEDCORE_NS}"
        - name: SEEDCORE_NS
          value: "\${SEEDCORE_NS}"
        - name: RUNNING_IN_CLUSTER
          value: "1"

        # DB DSN
        - name: SEEDCORE_PG_DSN
          value: "postgresql://postgres:\${POSTGRES_PASSWORD}@postgresql.\${NAMESPACE}.svc.cluster.local:5432/seedcore"

        # HTTP fallback for init_organism.py
        - name: SERVE_BASE_URL
          value: "http://seedcore-svc-serve-svc.\${NAMESPACE}.svc.cluster.local:8000"
        - name: ORGANISM_URL
          value: "http://seedcore-svc-serve-svc.\${NAMESPACE}.svc.cluster.local:8000/organism"
        
        resources:
          requests:
            cpu: "100m"
            memory: "512Mi"
          limits:
            cpu: "200m"
            memory: "1Gi"
EOF

    # Create dispatchers bootstrap job
    cat > "${SCRIPT_DIR}/bootstrap-dispatchers-job.yaml" << EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: seedcore-bootstrap-dispatchers
  namespace: \${NAMESPACE}
  labels:
    app: seedcore
    component: bootstrap-dispatchers
spec:
  completions: 1
  parallelism: 1
  backoffLimit: 3
  template:
    metadata:
      labels:
        app: seedcore
        component: bootstrap-dispatchers
    spec:
      serviceAccountName: seedcore-service-account
      restartPolicy: Never
      containers:
      - name: bootstrap-dispatchers
        image: \${ECR_REPO}:\${SEEDCORE_IMAGE_TAG}
        imagePullPolicy: Always
        command: ["python", "/app/bootstraps/bootstrap_entry.py"]
        env:
        # Tell the entrypoint to only init dispatchers and exit
        - name: BOOTSTRAP_MODE
          value: "dispatchers"
        - name: EXIT_AFTER_BOOTSTRAP
          value: "true"

        # Dispatcher bring-up options
        - name: FORCE_REPLACE_DISPATCHERS
          value: "true"
        - name: DISPATCHER_COUNT
          value: "2"
        - name: SEEDCORE_GRAPH_DISPATCHERS
          value: "1"
        - name: DGLBACKEND
          value: "pytorch"

        # Ray connectivity
        - name: RAY_ADDRESS
          value: "ray://\${RAY_HEAD_SVC}:\${RAY_HEAD_PORT}"
        - name: RAY_NAMESPACE
          value: "\${SEEDCORE_NS}"
        - name: SEEDCORE_NS
          value: "\${SEEDCORE_NS}"
        - name: RUNNING_IN_CLUSTER
          value: "1"

        # Database for dispatchers/reaper/graph-dispatchers
        - name: SEEDCORE_PG_DSN
          value: "postgresql://postgres:\${POSTGRES_PASSWORD}@postgresql.\${NAMESPACE}.svc.cluster.local:5432/seedcore"

        # Optional tuning passed into actors
        - name: OCPS_DRIFT_THRESHOLD
          value: "0.5"
        - name: COGNITIVE_TIMEOUT_S
          value: "8.0"
        - name: COGNITIVE_MAX_INFLIGHT
          value: "64"
        - name: FAST_PATH_LATENCY_SLO_MS
          value: "1000"
        - name: MAX_PLAN_STEPS
          value: "16"
        
        resources:
          requests:
            cpu: "100m"
            memory: "512Mi"
          limits:
            cpu: "200m"
            memory: "1Gi"
EOF

    success "Bootstrap job manifests created successfully"
}

# Show deployment status
show_status() {
    log "Deployment Status:"
    echo
    
    echo "=== Namespaces ==="
    kubectl get namespaces | grep -E "(NAME|$NAMESPACE)"
    echo
    
    echo "=== Pods ==="
    kubectl get pods -n "$NAMESPACE" -o wide
    echo
    
    echo "=== Services ==="
    kubectl get services -n "$NAMESPACE"
    echo
    
    echo "=== Ingress ==="
    kubectl get ingress -n "$NAMESPACE"
    echo
    
    echo "=== Ray Services ==="
    kubectl get rayservice -n "$NAMESPACE" || true
    echo
    
    echo "=== Bootstrap Jobs ==="
    kubectl get jobs -n "$NAMESPACE" | grep bootstrap || true
    echo
    
    echo "=== ConfigMaps ==="
    kubectl get configmaps -n "$NAMESPACE" | grep seedcore || true
    echo
    
    echo "=== Secrets ==="
    kubectl get secrets -n "$NAMESPACE" | grep seedcore || true
    echo
    
    echo "=== Persistent Volume Claims ==="
    kubectl get pvc -n "$NAMESPACE"
    echo
}

# Get service URLs
get_service_urls() {
    log "Service URLs:"
    echo
    
    # Get LoadBalancer URLs
    local api_url=$(kubectl get service seedcore-api -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "Pending")
    local ray_url=$(kubectl get service seedcore-svc-serve-svc -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "Pending")
    local nim_retrieval_url=$(kubectl get service nim-retrieval -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "Pending")
    local nim_llama_url=$(kubectl get service nim-llama -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "Pending")
    
    echo "SeedCore API: http://$api_url"
    echo "Ray Serve: http://$ray_url"
    echo "NIM Retrieval: http://$nim_retrieval_url"
    echo "NIM Llama: http://$nim_llama_url"
    echo
    
    # Get Ingress URL
    local ingress_url=$(kubectl get ingress seedcore-ingress -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "Pending")
    if [ "$ingress_url" != "Pending" ]; then
        echo "Ingress URL: https://$ingress_url"
        echo "  - API: https://$ingress_url/api"
        echo "  - ML Service: https://$ingress_url/ml"
        echo "  - Cognitive: https://$ingress_url/cognitive"
        echo "  - Pipeline: https://$ingress_url/pipeline"
        echo "  - Ops: https://$ingress_url/ops"
        echo "  - Organism: https://$ingress_url/organism"
        echo "  - NIM Retrieval: https://$ingress_url/nim/retrieval"
        echo "  - NIM Llama: https://$ingress_url/nim/llama"
    fi
    echo
}

# Cleanup function
cleanup() {
    log "Cleaning up deployment..."
    
    # Delete ingress first
    kubectl delete ingress seedcore-ingress -n "$NAMESPACE" || true
    kubectl delete ingress seedcore-internal-ingress -n "$NAMESPACE" || true
    
    # Delete services
    kubectl delete service seedcore-api -n "$NAMESPACE" || true
    kubectl delete service nim-retrieval -n "$NAMESPACE" || true
    kubectl delete service nim-llama -n "$NAMESPACE" || true
    
    # Delete deployments
    kubectl delete deployment seedcore-api -n "$NAMESPACE" || true
    kubectl delete deployment nim-retrieval -n "$NAMESPACE" || true
    kubectl delete deployment nim-llama -n "$NAMESPACE" || true
    
    # Delete bootstrap jobs
    kubectl delete job seedcore-bootstrap-organism -n "$NAMESPACE" || true
    kubectl delete job seedcore-bootstrap-dispatchers -n "$NAMESPACE" || true
    
    # Delete Ray service
    kubectl delete rayservice seedcore-svc -n "$NAMESPACE" || true
    
    # Delete databases
    kubectl delete deployment postgresql mysql neo4j redis -n "$NAMESPACE" || true
    kubectl delete service postgresql mysql neo4j redis -n "$NAMESPACE" || true
    
    # Delete PVCs
    kubectl delete pvc --all -n "$NAMESPACE" || true
    
    # Delete environment resources
    kubectl delete configmap seedcore-env -n "$NAMESPACE" || true
    kubectl delete secret seedcore-env-secret -n "$NAMESPACE" || true
    kubectl delete configmap seedcore-client-env -n "$NAMESPACE" || true
    
    # Delete RBAC
    kubectl delete -f "${SCRIPT_DIR}/rbac.yaml" || true
    
    # Clean up generated files
    rm -f "${SCRIPT_DIR}/bootstrap-organism-job.yaml" || true
    rm -f "${SCRIPT_DIR}/bootstrap-dispatchers-job.yaml" || true
    
    success "Cleanup completed"
}

# Main function
main() {
    local action="${1:-deploy}"
    
    case "$action" in
        "deploy")
            log "Starting SeedCore deployment to EKS..."
            
            load_env
            check_kubectl
            create_namespace
            deploy_rbac
            deploy_storage
            create_env_resources
            deploy_databases
            init_databases
            deploy_ray_service
            bootstrap_components
            deploy_seedcore_api
            
            # Deploy NIM services (optional, can be skipped with SKIP_NIM=true)
            if [ "${SKIP_NIM:-false}" != "true" ]; then
                deploy_nim_services
            else
                log "Skipping NIM services deployment (SKIP_NIM=true)"
            fi
            
            deploy_ingress
            show_status
            get_service_urls
            
            success "SeedCore deployment completed successfully!"
            ;;
        "status")
            load_env
            show_status
            get_service_urls
            ;;
        "cleanup")
            load_env
            cleanup
            ;;
        "help"|"-h"|"--help")
            echo "Usage: $0 [deploy|status|cleanup|help]"
            echo
            echo "Commands:"
            echo "  deploy   - Deploy all SeedCore services (default)"
            echo "  status   - Show deployment status"
            echo "  cleanup  - Remove all deployed resources"
            echo "  help     - Show this help message"
            echo
            echo "Environment Variables:"
            echo "  SKIP_NIM - Skip NIM services deployment (set to 'true' to skip)"
            echo
            echo "Examples:"
            echo "  ./deploy-all.sh deploy              # Deploy all services"
            echo "  SKIP_NIM=true ./deploy-all.sh deploy  # Skip NIM services"
            echo "  ./deploy-all.sh status             # Check deployment status"
            echo "  ./deploy-all.sh cleanup            # Remove all resources"
            ;;
        *)
            error "Unknown action: $action"
            echo "Use '$0 help' for usage information"
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
