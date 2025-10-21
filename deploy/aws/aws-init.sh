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
    
    if kubectl get namespace kuberay-system &> /dev/null; then
        log "KubeRay operator already installed"
    else
        kubectl apply -f https://raw.githubusercontent.com/ray-project/kuberay/master/ray-operator/config/default/bases/kuberay-operator.yaml
        kubectl wait --for=condition=available --timeout=300s deployment/kuberay-operator -n kuberay-system
    fi
    
    success "KubeRay operator installed successfully"
}

# Install AWS Load Balancer Controller
install_alb_controller() {
    log "Installing AWS Load Balancer Controller..."
    
    if kubectl get deployment aws-load-balancer-controller -n kube-system &> /dev/null; then
        log "AWS Load Balancer Controller already installed"
    else
        # Download IAM policy
        curl -o iam_policy.json https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v2.7.2/docs/install/iam_policy.json
        
        # Create IAM role
        aws iam create-role \
            --role-name AmazonEKSLoadBalancerControllerRole \
            --assume-role-policy-document file://trust-policy.json || true
        
        aws iam attach-role-policy \
            --role-name AmazonEKSLoadBalancerControllerRole \
            --policy-arn arn:aws:iam::${AWS_ACCOUNT_ID}:policy/AWSLoadBalancerControllerIAMPolicy || true
        
        # Install controller
        eksctl create iamserviceaccount \
            --cluster="$CLUSTER_NAME" \
            --namespace=kube-system \
            --name=aws-load-balancer-controller \
            --role-name=AmazonEKSLoadBalancerControllerRole \
            --attach-policy-arn=arn:aws:iam::${AWS_ACCOUNT_ID}:policy/AWSLoadBalancerControllerIAMPolicy \
            --approve
        
        kubectl apply -f https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v2.7.2/docs/install/v2_7_2_full.yaml
        
        kubectl wait --for=condition=available --timeout=300s deployment/aws-load-balancer-controller -n kube-system
    fi
    
    success "AWS Load Balancer Controller installed successfully"
}

# Install cert-manager
install_cert_manager() {
    log "Installing cert-manager..."
    
    if kubectl get namespace cert-manager &> /dev/null; then
        log "cert-manager already installed"
    else
        kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.2/cert-manager.yaml
        kubectl wait --for=condition=available --timeout=300s deployment/cert-manager -n cert-manager
    fi
    
    success "cert-manager installed successfully"
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
    install_alb_controller
    install_cert_manager
    
    success "AWS EKS initialization completed successfully!"
    
    echo
    echo "Next steps:"
    echo "1. Build and push Docker images: ./build-and-push.sh"
    echo "2. Deploy SeedCore: ./deploy-all.sh"
    echo "3. Check deployment status: kubectl get pods -n $NAMESPACE"
}

# Run main function
main "$@"


