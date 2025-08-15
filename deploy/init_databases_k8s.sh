#!/bin/bash

# Database Initialization Script for Kubernetes
# This script initializes the required database schemas for SeedCore

set -e

echo "🔧 Initializing SeedCore databases in Kubernetes..."

# Get the namespace (default to seedcore-dev if not specified)
NAMESPACE=${1:-seedcore-dev}
echo "📋 Using namespace: $NAMESPACE"

# Function to wait for a pod to be ready
wait_for_pod() {
    local pod_name=$1
    local max_wait=60
    local wait_time=0
    
    echo "⏳ Waiting for $pod_name to be ready..."
    while [ $wait_time -lt $max_wait ]; do
        if kubectl get pod -n $NAMESPACE $pod_name | grep -q "Running"; then
            echo "✅ $pod_name is ready"
            return 0
        fi
        sleep 5
        wait_time=$((wait_time + 5))
        echo "⏳ Still waiting... ($wait_time/$max_wait seconds)"
    done
    
    echo "❌ Timeout waiting for $pod_name to be ready"
    return 1
}

# Function to initialize PostgreSQL
init_postgresql() {
    echo "🐘 Initializing PostgreSQL..."
    
    # Find PostgreSQL pod
    PG_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=postgresql -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    
    if [ -z "$PG_POD" ]; then
        echo "❌ PostgreSQL pod not found. Make sure PostgreSQL is deployed."
        return 1
    fi
    
    echo "📦 Found PostgreSQL pod: $PG_POD"
    
    # Wait for pod to be ready
    wait_for_pod $PG_POD
    
    # Copy initialization script to pod
    echo "📝 Copying PostgreSQL initialization script..."
    kubectl cp docker/setup/init_pgvector.sql $NAMESPACE/$PG_POD:/tmp/init_pgvector.sql
    
    # Run the initialization script
    echo "🚀 Running PostgreSQL initialization..."
    kubectl exec -n $NAMESPACE $PG_POD -- psql -U postgres -d postgres -f /tmp/init_pgvector.sql
    
    echo "✅ PostgreSQL initialized successfully"
}

# Function to initialize MySQL
init_mysql() {
    echo "🐬 Initializing MySQL..."
    
    # Find MySQL pod
    MYSQL_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=mysql -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    
    if [ -z "$MYSQL_POD" ]; then
        echo "❌ MySQL pod not found. Make sure MySQL is deployed."
        return 1
    fi
    
    echo "📦 Found MySQL pod: $MYSQL_POD"
    
    # Wait for pod to be ready
    wait_for_pod $MYSQL_POD
    
    # Copy initialization script to pod
    echo "📝 Copying MySQL initialization script..."
    kubectl cp docker/setup/init_mysql.sql $NAMESPACE/$MYSQL_POD:/tmp/init_mysql.sql
    
    # Run the initialization script
    echo "🚀 Running MySQL initialization..."
    # FIX: Drop and recreate the database to make the script idempotent. Run as 'root'.
    kubectl exec -n $NAMESPACE $MYSQL_POD -- sh -c 'mysql -u root -ppassword -e "DROP DATABASE IF EXISTS seedcore; CREATE DATABASE seedcore;"'
    kubectl exec -n $NAMESPACE $MYSQL_POD -- sh -c 'mysql -u root -ppassword seedcore < /tmp/init_mysql.sql'

    echo "✅ MySQL initialized successfully"
}

# Function to initialize Neo4j
init_neo4j() {
    echo "🟢 Initializing Neo4j..."
    
    # Find Neo4j pod
    NEO4J_POD=$(kubectl get pods -n $NAMESPACE -l app=neo4j -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    
    if [ -z "$NEO4J_POD" ]; then
        echo "❌ Neo4j pod not found. Make sure Neo4j is deployed."
        return 1
    fi
    
    echo "📦 Found Neo4j pod: $NEO4J_POD"
    
    # Wait for pod to be ready
    wait_for_pod $NEO4J_POD
    
    # Copy initialization script to pod
    echo "📝 Copying Neo4j initialization script..."
    kubectl cp docker/setup/init_neo4j.cypher $NAMESPACE/$NEO4J_POD:/tmp/init_neo4j.cypher
    
    # Run the initialization script using cypher-shell
    echo "🚀 Running Neo4j initialization..."
    kubectl exec -n $NAMESPACE $NEO4J_POD -- cypher-shell -u neo4j -p password -d neo4j -f /tmp/init_neo4j.cypher

    echo "✅ Neo4j initialized successfully"
}

# Function to verify database initialization
verify_databases() {
    echo "🔍 Verifying database initialization..."
    
    # Check PostgreSQL
    echo "🐘 Checking PostgreSQL..."
    PG_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=postgresql -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    if [ -n "$PG_POD" ]; then
        kubectl exec -n $NAMESPACE $PG_POD -- psql -U postgres -d postgres -c "SELECT COUNT(*) FROM holons;" 2>/dev/null && echo "✅ PostgreSQL: holons table exists" || echo "❌ PostgreSQL: holons table missing"
    fi
    
    # Check MySQL
    echo "🐬 Checking MySQL..."
    MYSQL_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=mysql -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    if [ -n "$MYSQL_POD" ]; then
        # Verify as the 'root' user and specify the database.
        kubectl exec -n $NAMESPACE $MYSQL_POD -- mysql -u root -ppassword seedcore -e "SHOW TABLES;" 2>/dev/null && echo "✅ MySQL: tables exist" || echo "❌ MySQL: tables missing"
    fi
    
    # In the verify_databases function, under "Checking Neo4j..."
    if [ -n "$NEO4J_POD" ]; then
        # This is the new, correct command
        COUNT=$(kubectl exec -n $NAMESPACE $NEO4J_POD -- bash -c 'echo "MATCH (h:Holon) RETURN COUNT(h) AS count;" | /var/lib/neo4j/bin/cypher-shell -u neo4j -p password -d neo4j --format plain | tail -n 1')
        if [ "$COUNT" -gt 0 ]; then
            echo "✅ Neo4j: Holon nodes exist (Count: $COUNT)"
        else
            echo "❌ Neo4j: Holon nodes missing"
        fi
    fi
}

# Main execution
main() {
    echo "🚀 Starting SeedCore database initialization..."
    
    # Check if kubectl is available
    if ! command -v kubectl &> /dev/null; then
        echo "❌ kubectl is not installed or not in PATH"
        exit 1
    fi
    
    # Check if namespace exists
    if ! kubectl get namespace $NAMESPACE &> /dev/null; then
        echo "❌ Namespace $NAMESPACE does not exist"
        exit 1
    fi
    
    # Initialize databases
    init_postgresql
    init_mysql
    init_neo4j
    
    # Verify initialization
    verify_databases
    
    echo "🎉 Database initialization completed!"
    echo ""
    echo "Next steps:"
    echo "1. Restart your seedcore-api pod to pick up the new database schema"
    echo "2. Check the logs to ensure no more database errors"
    echo "3. Verify the application is working correctly"
}

# Run main function
main "$@"
