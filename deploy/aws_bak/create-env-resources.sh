#!/usr/bin/env bash
# Create Environment Resources for AWS EKS Deployment
# Creates ConfigMaps and Secrets from env.example file

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
    source "$env_file"
}

# Create ConfigMap from env.example
create_configmap() {
    log "Creating ConfigMap from env.example..."
    
    local env_example="${PROJECT_ROOT}/docker/env.example"
    local configmap_file="${SCRIPT_DIR}/seedcore-env-configmap.yaml"
    
    if [ ! -f "$env_example" ]; then
        error "env.example file not found: $env_example"
        exit 1
    fi
    
    # Create ConfigMap YAML
    cat > "$configmap_file" << EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: seedcore-env
  namespace: \${NAMESPACE}
  labels:
    app: seedcore
    component: config
data:
EOF
    
    # Process env.example and add to ConfigMap
    while IFS= read -r line || [ -n "$line" ]; do
        # Skip comments and empty lines
        if [[ "$line" =~ ^[[:space:]]*# ]] || [[ -z "${line// }" ]]; then
            continue
        fi
        
        # Skip lines with placeholder values that should be secrets
        if [[ "$line" =~ (PASSWORD|API_KEY|SECRET|TOKEN) ]]; then
            continue
        fi
        
        # Extract key=value pairs
        if [[ "$line" =~ ^([^=]+)=(.*)$ ]]; then
            local key="${BASH_REMATCH[1]}"
            local value="${BASH_REMATCH[2]}"
            
            # Skip if value is empty or contains placeholder
            if [[ -z "$value" ]] || [[ "$value" =~ (your-|sk-proj-|localhost|YOUR_) ]]; then
                continue
            fi
            
            # Escape special characters in value
            value=$(echo "$value" | sed 's/"/\\"/g')
            
            echo "  $key: \"$value\"" >> "$configmap_file"
        fi
    done < "$env_example"
    
    # Apply ConfigMap
    envsubst < "$configmap_file" | kubectl apply -f -
    
    success "ConfigMap created successfully"
}

# Create Secret from env.example
create_secret() {
    log "Creating Secret from env.example..."
    
    local env_example="${PROJECT_ROOT}/docker/env.example"
    local secret_file="${SCRIPT_DIR}/seedcore-env-secret.yaml"
    
    if [ ! -f "$env_example" ]; then
        error "env.example file not found: $env_example"
        exit 1
    fi
    
    # Create Secret YAML
    cat > "$secret_file" << EOF
apiVersion: v1
kind: Secret
metadata:
  name: seedcore-env-secret
  namespace: \${NAMESPACE}
  labels:
    app: seedcore
    component: secret
type: Opaque
stringData:
EOF
    
    # Process env.example and add sensitive values to Secret
    while IFS= read -r line || [ -n "$line" ]; do
        # Skip comments and empty lines
        if [[ "$line" =~ ^[[:space:]]*# ]] || [[ -z "${line// }" ]]; then
            continue
        fi
        
        # Only include lines with sensitive information
        if [[ "$line" =~ (PASSWORD|API_KEY|SECRET|TOKEN) ]]; then
            # Extract key=value pairs
            if [[ "$line" =~ ^([^=]+)=(.*)$ ]]; then
                local key="${BASH_REMATCH[1]}"
                local value="${BASH_REMATCH[2]}"
                
                # Skip if value is empty or placeholder
                if [[ -z "$value" ]] || [[ "$value" =~ (your-|sk-proj-|password) ]]; then
                    # Use default values for placeholders
                    case "$key" in
                        "POSTGRES_PASSWORD"|"MYSQL_ROOT_PASSWORD"|"NEO4J_PASSWORD"|"REDIS_PASSWORD")
                            value="${!key:-password}"
                            ;;
                        "OPENAI_API_KEY")
                            value="${OPENAI_API_KEY:-sk-placeholder-key}"
                            ;;
                        *)
                            continue
                            ;;
                    esac
                fi
                
                echo "  $key: \"$value\"" >> "$secret_file"
            fi
        fi
    done < "$env_example"
    
    # Apply Secret
    envsubst < "$secret_file" | kubectl apply -f -
    
    success "Secret created successfully"
}

# Create client-specific ConfigMap
create_client_configmap() {
    log "Creating client-specific ConfigMap..."
    
    local configmap_file="${SCRIPT_DIR}/seedcore-client-env-configmap.yaml"
    
    # Create client-specific ConfigMap
    cat > "$configmap_file" << EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: seedcore-client-env
  namespace: \${NAMESPACE}
  labels:
    app: seedcore
    component: client-config
data:
  # Client-specific configuration
  SEEDCORE_NS: "\${SEEDCORE_NS}"
  SEEDCORE_STAGE: "prod"
  COG_APP_NAME: "\${NAMESPACE}-prod-cognitive_core"
  COG_MIN_READY: "1"
  SEEDCORE_API_ADDRESS: "\${SEEDCORE_API_ADDRESS}"
  
  # Ray configuration
  RAY_HOST: "\${RAY_HEAD_SVC}"
  RAY_PORT: "\${RAY_HEAD_PORT}"
  RAY_SERVE_URL: "http://seedcore-svc-serve-svc.\${NAMESPACE}.svc.cluster.local:8000"
  RAY_DASHBOARD_URL: "http://\${RAY_HEAD_SVC}.\${NAMESPACE}.svc.cluster.local:8265"
  RAY_NAMESPACE: "\${SEEDCORE_NS}"
  
  # Database configuration for AWS
  POSTGRES_HOST: "postgresql.\${NAMESPACE}.svc.cluster.local"
  POSTGRES_PORT: "5432"
  POSTGRES_DB: "seedcore"
  POSTGRES_USER: "postgres"
  PG_DSN: "postgresql://postgres:\${POSTGRES_PASSWORD}@postgresql.\${NAMESPACE}.svc.cluster.local:5432/seedcore"
  
  MYSQL_HOST: "mysql.\${NAMESPACE}.svc.cluster.local"
  MYSQL_PORT: "3306"
  MYSQL_DB: "seedcore"
  MYSQL_USER: "seedcore"
  MYSQL_DSN: "mysql+pymysql://seedcore:\${MYSQL_ROOT_PASSWORD}@mysql.\${NAMESPACE}.svc.cluster.local:3306/seedcore"
  
  REDIS_HOST: "redis.\${NAMESPACE}.svc.cluster.local"
  REDIS_PORT: "6379"
  REDIS_DB: "0"
  REDIS_URL: "redis://redis.\${NAMESPACE}.svc.cluster.local:6379/0"
  
  NEO4J_HOST: "neo4j.\${NAMESPACE}.svc.cluster.local"
  NEO4J_BOLT_PORT: "7687"
  NEO4J_HTTP_PORT: "7474"
  NEO4J_USER: "neo4j"
  NEO4J_BOLT_URL: "bolt://neo4j.\${NAMESPACE}.svc.cluster.local:7687"
  NEO4J_HTTP_URL: "http://neo4j.\${NAMESPACE}.svc.cluster.local:7474"
  NEO4J_URI: "bolt://neo4j.\${NAMESPACE}.svc.cluster.local:7687"
  NEO4J_ENCRYPTED: "false"
  
  # AWS-specific configuration
  AWS_REGION: "\${AWS_REGION}"
  AWS_DEFAULT_REGION: "\${AWS_REGION}"
  
  # Environment
  ENVIRONMENT: "production"
  LOG_LEVEL: "INFO"
  
  # Performance tuning
  OMP_NUM_THREADS: "1"
  MKL_NUM_THREADS: "1"
  TOKENIZERS_PARALLELISM: "false"
  
  # Bootstrap configuration
  SEEDCORE_BOOTSTRAP_OPTIONAL: "0"
  AUTO_CREATE: "0"
  
  # Ray configuration
  RAY_MIN_NODES: "2"
  RAY_MIN_CPUS: "2"
EOF
    
    # Apply ConfigMap
    envsubst < "$configmap_file" | kubectl apply -f -
    
    success "Client ConfigMap created successfully"
}

# Clean up generated files
cleanup_files() {
    log "Cleaning up generated files..."
    
    rm -f "${SCRIPT_DIR}/seedcore-env-configmap.yaml"
    rm -f "${SCRIPT_DIR}/seedcore-env-secret.yaml"
    rm -f "${SCRIPT_DIR}/seedcore-client-env-configmap.yaml"
    
    success "Cleanup completed"
}

# Main function
main() {
    local action="${1:-create}"
    
    case "$action" in
        "create")
            log "Creating environment resources for AWS EKS deployment..."
            
            load_env
            create_configmap
            create_secret
            create_client_configmap
            cleanup_files
            
            success "Environment resources created successfully!"
            echo
            echo "Created resources:"
            echo "  - ConfigMap: seedcore-env"
            echo "  - Secret: seedcore-env-secret"
            echo "  - ConfigMap: seedcore-client-env"
            ;;
        "delete")
            log "Deleting environment resources..."
            
            load_env
            kubectl delete configmap seedcore-env -n "$NAMESPACE" || true
            kubectl delete secret seedcore-env-secret -n "$NAMESPACE" || true
            kubectl delete configmap seedcore-client-env -n "$NAMESPACE" || true
            
            success "Environment resources deleted successfully!"
            ;;
        "help"|"-h"|"--help")
            echo "Usage: $0 [create|delete|help]"
            echo
            echo "Commands:"
            echo "  create  - Create ConfigMaps and Secrets from env.example (default)"
            echo "  delete  - Delete environment resources"
            echo "  help    - Show this help message"
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


