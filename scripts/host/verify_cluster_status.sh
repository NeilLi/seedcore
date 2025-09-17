#!/bin/bash

# Cluster Status Verification Script
# This script verifies the current state of the SeedCore cluster by checking:
# - Current epoch
# - Active organs status
# - Agent instances
# - Duplicate instance detection

set -e

# Configuration
NAMESPACE="${NAMESPACE:-seedcore-dev}"
DB_NAME="${DB_NAME:-seedcore}"
DB_USER="${DB_USER:-postgres}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to find PostgreSQL pod
find_postgres_pod() {
    local pod=""
    for selector in \
        'app.kubernetes.io/name=postgresql,app.kubernetes.io/component=primary' \
        'app.kubernetes.io/name=postgresql' \
        'app=postgresql'
    do
        pod="$(kubectl -n "$NAMESPACE" get pods -l "$selector" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
        [[ -n "$pod" ]] && break
    done
    echo "$pod"
}

# Function to print colored output
print_status() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# Function to execute SQL query
execute_query() {
    local query="$1"
    local description="$2"
    
    print_status $BLUE "=== $description ==="
    
    kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
        psql -U "$DB_USER" -d "$DB_NAME" -c "$query"
    
    if [ $? -eq 0 ]; then
        print_status $GREEN "✓ Query executed successfully"
    else
        print_status $RED "✗ Query failed"
        return 1
    fi
    echo
}

# Function to check if database is accessible
check_database_connection() {
    print_status $BLUE "=== Checking Database Connection ==="
    
    kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
        psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1;" > /dev/null 2>&1
    
    if [ $? -eq 0 ]; then
        print_status $GREEN "✓ Database connection successful"
    else
        print_status $RED "✗ Cannot connect to database"
        print_status $YELLOW "Please check your database configuration:"
        print_status $YELLOW "  NAMESPACE: $NAMESPACE"
        print_status $YELLOW "  POSTGRES_POD: $POSTGRES_POD"
        print_status $YELLOW "  DB_NAME: $DB_NAME"
        print_status $YELLOW "  DB_USER: $DB_USER"
        exit 1
    fi
    echo
}

# Main verification function
main() {
    print_status $BLUE "=========================================="
    print_status $BLUE "SeedCore Cluster Status Verification"
    print_status $BLUE "=========================================="
    echo
    
    # Find PostgreSQL pod
    print_status $BLUE "🔍 Finding PostgreSQL pod..."
    POSTGRES_POD=$(find_postgres_pod)
    
    if [[ -z "$POSTGRES_POD" ]]; then
        print_status $RED "❌ Could not locate a Postgres pod in namespace '$NAMESPACE'."
        print_status $YELLOW "   Tip: kubectl -n $NAMESPACE get pods --show-labels | grep -i postgres"
        exit 1
    fi
    
    print_status $GREEN "✅ Found Postgres pod: $POSTGRES_POD"
    echo
    
    # Check database connection first
    check_database_connection
    
    # 1. Current epoch
    execute_query "SELECT current_epoch FROM cluster_metadata;" "Current Epoch"
    
    # 2. Active organs fresh within 15s
    execute_query "SELECT logical_id, instance_id, status, now()-last_heartbeat AS age FROM registry_instance WHERE logical_id IN ('utility_organ_1','actuator_organ_1','cognitive_organ_1') AND status = 'alive' ORDER BY logical_id;" "Active Organs (Fresh within 15s)"
    
    # 3. Agents (if registered)
    execute_query "SELECT agent_id, display_name, created_at FROM agent_registry ORDER BY agent_id;" "Registered Agents"
    
    # 3b. Agent-to-Organ relationships
    execute_query "SELECT agent_id, organ_id FROM agent_member_of_organ ORDER BY agent_id;" "Agent-Organ Relationships"
    
    # 4. Ensure no duplicates per logical_id (unless rolling)
    execute_query "SELECT logical_id, COUNT(*) AS alive_count FROM registry_instance WHERE status = 'alive' GROUP BY logical_id HAVING COUNT(*) > 1;" "Duplicate Instance Check"
    
    print_status $GREEN "=========================================="
    print_status $GREEN "Verification Complete"
    print_status $GREEN "=========================================="
}

# Help function
show_help() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -h, --help              Show this help message"
    echo "  --namespace NAMESPACE   Kubernetes namespace (default: seedcore-dev)"
    echo "  --db-name NAME          Database name (default: seedcore)"
    echo "  --db-user USER          Database user (default: postgres)"
    echo ""
    echo "Environment Variables:"
    echo "  NAMESPACE                Kubernetes namespace"
    echo "  DB_NAME                  Database name"
    echo "  DB_USER                  Database user"
    echo ""
    echo "Examples:"
    echo "  $0                                    # Use default settings"
    echo "  $0 --namespace my-namespace           # Use specific namespace"
    echo "  NAMESPACE=my-ns $0                    # Using environment variable"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        --namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        --db-name)
            DB_NAME="$2"
            shift 2
            ;;
        --db-user)
            DB_USER="$2"
            shift 2
            ;;
        *)
            print_status $RED "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Run main function
main
