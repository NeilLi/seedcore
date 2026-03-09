#!/usr/bin/env bash
# AWS EKS Initialization Script
# Sets up AWS CLI, EKS CLI, and kubectl configuration

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

# Check if required tools are installed
check_prerequisites() {
    log "Checking prerequisites..."
    
    local missing_tools=()
    
    if ! command -v aws &> /dev/null; then
        missing_tools+=("aws-cli")
    fi
    
    if ! command -v eksctl &> /dev/null; then
        missing_tools+=("eksctl")
    fi
    
    if ! command -v kubectl &> /dev/null; then
        missing_tools+=("kubectl")
    fi
    
    if ! command -v docker &> /dev/null; then
        missing_tools+=("docker")
    fi
    
    if [ ${#missing_tools[@]} -ne 0 ]; then
        error "Missing required tools: ${missing_tools[*]}"
        echo
        echo "Please install the missing tools:"
        echo "  - AWS CLI: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
        echo "  - eksctl: https://eksctl.io/introduction/installation/"
        echo "  - kubectl: https://kubernetes.io/docs/tasks/tools/"
        echo "  - Docker: https://docs.docker.com/get-docker/"
        exit 1
    fi
    
    success "All prerequisites are installed"
}

# Load environment variables
load_env() {
    local env_file="${SCRIPT_DIR}/.env.aws"
    
    if [ ! -f "$env_file" ]; then
        if [ -f "${SCRIPT_DIR}/env.aws.example" ]; then
            warn "Environment file not found. Copying from example..."
            cp "${SCRIPT_DIR}/env.aws.example" "$env_file"
            warn "Please edit ${env_file} with your AWS configuration"
            exit 1
        else
            error "Environment file not found: $env_file"
            exit 1
        fi
    fi
    
    log "Loading environment variables from $env_file"
    source "$env_file"
    
    # Validate required variables
    local required_vars=(
        "AWS_REGION"
        "AWS_ACCOUNT_ID"
        "CLUSTER_NAME"
        "NAMESPACE"
        "ECR_REPO"
    )
    
    for var in "${required_vars[@]}"; do
        if [ -z "${!var:-}" ]; then
            error "Required environment variable $var is not set"
            exit 1
        fi
    done
    
    success "Environment variables loaded successfully"
}

# Configure AWS CLI
configure_aws() {
    log "Configuring AWS CLI..."
    
    # Check if AWS is already configured
    if aws sts get-caller-identity &> /dev/null; then
        local current_region=$(aws configure get region)
        if [ "$current_region" != "$AWS_REGION" ]; then
            warn "AWS region mismatch. Current: $current_region, Expected: $AWS_REGION"
            aws configure set region "$AWS_REGION"
        fi
        success "AWS CLI is already configured"
    else
        warn "AWS CLI is not configured. Please run 'aws configure' first"
        echo "You can also set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables"
        exit 1
    fi
}

# Create ECR repositories
create_ecr_repos() {
    log "Creating ECR repositories..."
    
    local repos=("seedcore" "nim-retrieval" "nim-llama")
    
    for repo in "${repos[@]}"; do
        local repo_name="${ECR_REGISTRY}/${repo}"
        
        if aws ecr describe-repositories --repository-names "$repo" --region "$AWS_REGION" &> /dev/null; then
            log "ECR repository $repo already exists"
        else
            log "Creating ECR repository: $repo"
            aws ecr create-repository \
                --repository-name "$repo" \
                --region "$AWS_REGION" \
                --image-scanning-configuration scanOnPush=true \
                --encryption-configuration encryptionType=AES256
        fi
    done
    
    success "ECR repositories created successfully"
}

# Login to ECR
login_ecr() {
    log "Logging in to ECR..."
    
    aws ecr get-login-password --region "$AWS_REGION" | \
        docker login --username AWS --password-stdin "$ECR_REGISTRY"
    
    success "Successfully logged in to ECR"
}

# Create EKS cluster
create_eks_cluster() {
    log "Creating EKS cluster: $CLUSTER_NAME"
    
    if eksctl get cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" &> /dev/null; then
        warn "EKS cluster $CLUSTER_NAME already exists"
    else
        log "Creating EKS cluster with eksctl..."
        eksctl create cluster -f "${SCRIPT_DIR}/eks-cluster.yaml"
    fi
    
    success "EKS cluster created successfully"
}

# Update kubeconfig
update_kubeconfig() {
    log "Updating kubeconfig..."
    
    aws eks update-kubeconfig \
        --region "$AWS_REGION" \
        --name "$CLUSTER_NAME"
    
    success "Kubeconfig updated successfully"
}

# Create namespace
create_namespace() {
    log "Creating namespace: $NAMESPACE"
    
    if kubectl get namespace "$NAMESPACE" &> /dev/null; then
        log "Namespace $NAMESPACE already exists"
    else
        kubectl create namespace "$NAMESPACE"
    fi
    
    success "Namespace created successfully"
}

# Install KubeRay operator
install_kuberay() {
    log "Installing KubeRay operator..."
    
    # Check if KubeRay CRDs exist
    if kubectl get crd rayclusters.ray.io &> /dev/null; then
        log "KubeRay operator already installed"
        success "KubeRay operator is ready"
        return 0
    fi
    
    # Check if helm is available
    if ! command -v helm &> /dev/null; then
        warn "Helm is not installed. Installing with kubectl..."
        
        # Create namespace first
        kubectl create namespace kuberay-system --dry-run=client -o yaml | kubectl apply -f -
        
        # Install using kubectl with the official all-in-one YAML
        kubectl apply -f https://github.com/ray-project/kuberay/releases/download/v1.4.2/kuberay-operator-v1.4.2-allinone.yaml
        
        # Wait for operator to be ready
        log "Waiting for KubeRay operator to be ready..."
        kubectl wait --for=condition=available --timeout=300s deployment/kuberay-operator -n kuberay-system || true
        
    else
        log "Installing KubeRay operator using Helm..."
        
        # Add KubeRay Helm repo
        helm repo add kuberay https://ray-project.github.io/kuberay-helm/ &> /dev/null || true
        helm repo update &> /dev/null
        
        # Create namespace if needed
        kubectl create namespace kuberay-system --dry-run=client -o yaml | kubectl apply -f - &> /dev/null
        
        # Check if Helm release exists
        if ! helm list -n kuberay-system | grep -q kuberay-operator; then
            log "Installing KubeRay operator..."
            helm install kuberay-operator kuberay/kuberay-operator \
                --namespace kuberay-system --wait
            log "KubeRay operator installed"
        else
            # Check if operator pods are running
            if ! kubectl get pods -n kuberay-system -l app.kubernetes.io/name=kuberay-operator --no-headers 2>/dev/null | grep -q Running; then
                log "Upgrading KubeRay operator..."
                helm upgrade kuberay-operator kuberay/kuberay-operator --namespace kuberay-system --wait
            fi
            log "KubeRay operator is running"
        fi
        
        # Wait for KubeRay operator to be ready
        log "Waiting for KubeRay operator to be ready..."
        kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=kuberay-operator -n kuberay-system --timeout=300s || true
    fi
    
    success "KubeRay operator installed successfully"
}

# Install AWS Load Balancer Controller
install_alb_controller() {
    log "Installing AWS Load Balancer Controller..."
    
    if kubectl get deployment aws-load-balancer-controller -n kube-system &> /dev/null; then
        log "AWS Load Balancer Controller already installed"
        success "AWS Load Balancer Controller is ready"
        return 0
    fi
    
    # Associate IAM OIDC provider with cluster first
    log "Checking if IAM OIDC provider is associated..."
    if ! eksctl utils describe-stacks --region="$AWS_REGION" --cluster="$CLUSTER_NAME" | grep -q oidc; then
        log "Associating IAM OIDC provider with cluster..."
        eksctl utils associate-iam-oidc-provider --region="$AWS_REGION" --cluster="$CLUSTER_NAME" --approve || {
            warn "Failed to associate IAM OIDC provider. Skipping AWS Load Balancer Controller installation."
            warn "You can install it later with: eksctl utils associate-iam-oidc-provider --cluster=$CLUSTER_NAME --approve"
            return 0
        }
    fi
    
    # Install using Helm (cleaner approach)
    if command -v helm &> /dev/null; then
        log "Installing AWS Load Balancer Controller using Helm..."
        helm repo add eks https://aws.github.io/eks-charts &> /dev/null || true
        helm repo update &> /dev/null
        
        helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
            --namespace kube-system \
            --set clusterName="$CLUSTER_NAME" \
            --set region="$AWS_REGION" \
            --set vpcId=$(aws eks describe-cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" --query 'cluster.resourcesVpcConfig.vpcId' --output text) \
            --set serviceAccount.create=true \
            --set serviceAccount.name=aws-load-balancer-controller \
            --wait
        
        success "AWS Load Balancer Controller installed successfully"
    else
        warn "Helm is not installed. Skipping AWS Load Balancer Controller installation."
        warn "You can install it later manually."
        return 0
    fi
}

# Install cert-manager (optional)
install_cert_manager() {
    log "Installing cert-manager (optional)..."
    
    if kubectl get namespace cert-manager &> /dev/null; then
        log "cert-manager already installed"
        success "cert-manager is ready"
        return 0
    fi
    
    # Install cert-manager
    if kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.2/cert-manager.yaml 2>/dev/null; then
        kubectl wait --for=condition=available --timeout=300s deployment/cert-manager -n cert-manager 2>/dev/null || true
        success "cert-manager installed successfully"
    else
        warn "Failed to install cert-manager. This is optional."
        warn "cert-manager is only needed for TLS certificates."
        return 0
    fi
}

# Main function
main() {
    log "Starting AWS EKS initialization..."
    
    check_prerequisites
    load_env
    configure_aws
    create_ecr_repos
    login_ecr
    create_eks_cluster
    update_kubeconfig
    create_namespace
    install_kuberay
    
    # ALB Controller is optional
    install_alb_controller || warn "AWS Load Balancer Controller installation failed (optional)"
    
    # cert-manager is optional
    install_cert_manager || warn "cert-manager installation failed (optional)"
    
    success "AWS EKS initialization completed successfully!"
    
    echo
    echo "Next steps:"
    echo "1. Build and push Docker images: ./build-and-push.sh"
    echo "2. Deploy SeedCore: ./deploy-all.sh"
    echo "3. Check deployment status: kubectl get pods -n $NAMESPACE"
    echo
    echo "📝 Note: AWS Load Balancer Controller and cert-manager are optional."
    echo "   They are only needed for LoadBalancer services and TLS certificates."
}

# Run main function
main "$@"


