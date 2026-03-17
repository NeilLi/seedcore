#!/bin/bash

# Validate SeedCore Configuration
# This script checks for configuration conflicts and validates settings
# Now extended to validate: Neo4j, PostgreSQL, MySQL, Redis

set -euo pipefail

echo "🔍 Validating SeedCore Configuration..."
echo "======================================"

# ------------------------------------------------------
# Helper: Check Config Presence in K8s and Docker
# ------------------------------------------------------
check_config() {
  local service=$1
  local var_name=$2
  local uri_pattern=$3

  echo "📋 Checking for duplicate $service configurations..."

  # Check Kubernetes configs
  echo "  Kubernetes deployments:"
  if grep -r "$var_name.*$uri_pattern" deploy/kustomize/ deploy/helm/ 2>/dev/null | wc -l | grep -q "0"; then
    echo "    ❌ No $service configurations found in Kubernetes"
  else
    echo "    ✅ $service configurations found in Kubernetes deployments"
  fi

  # Check Docker Compose configs
  echo "  Docker Compose files:"
  if grep -r "$var_name.*$uri_pattern" docker/ 2>/dev/null | wc -l | grep -q "0"; then
    echo "    ❌ No $service configurations found in Docker Compose"
  else
    echo "    ✅ $service configurations found in Docker Compose files"
  fi
  echo ""
}

# ------------------------------------------------------
# Neo4j Checks
# ------------------------------------------------------
check_config "Neo4j" "NEO4J_URI" "bolt://neo4j:7687"

echo "📦 Checking Helm chart configurations..."
if [ -d "deploy/helm/neo4j" ]; then
    echo "  ❌ Custom Neo4j Helm chart still exists (should be removed)"
else
    echo "  ✅ Custom Neo4j Helm chart removed (using official chart)"
fi
if helm repo list | grep -q "neo4j"; then
    echo "  ✅ Official Neo4j Helm repository available"
else
    echo "  ❌ Official Neo4j Helm repository not found"
    echo "     Run: helm repo add neo4j https://helm.neo4j.com/neo4j"
fi
echo ""

# ------------------------------------------------------
# PostgreSQL Checks
# ------------------------------------------------------
check_config "PostgreSQL" "POSTGRES_URI" "postgresql://postgres"

# ------------------------------------------------------
# MySQL Checks
# ------------------------------------------------------
check_config "MySQL" "MYSQL_URI" "mysql://mysql"

# ------------------------------------------------------
# Redis Checks
# ------------------------------------------------------
check_config "Redis" "REDIS_URI" "redis://redis:6379"

# ------------------------------------------------------
# Check Connection Strings Consistency
# ------------------------------------------------------
echo "🔗 Checking connection string consistency..."
for db in NEO4J_URI POSTGRES_URI MYSQL_URI REDIS_URI; do
  echo "  $db values:"
  grep -r "$db" deploy/ docker/ 2>/dev/null | sort | uniq || echo "    ❌ No $db defined"
done
echo ""

# ------------------------------------------------------
# Hardcoded Credentials
# ------------------------------------------------------
echo "🔐 Checking for hardcoded credentials..."
echo "  Note: Using default passwords for development only"
grep -r "password" deploy/ docker/ | grep -E "(NEO4J_PASSWORD|POSTGRES_PASSWORD|MYSQL_PASSWORD|REDIS_PASSWORD)" | head -10 || echo "    ✅ No obvious hardcoded passwords found"
echo ""

# ------------------------------------------------------
# Network Configurations
# ------------------------------------------------------
echo "🌐 Checking network configurations..."
for db in "neo4j:7687" "postgres:5432" "mysql:3306" "redis:6379"; do
  svc=$(echo "$db" | cut -d: -f1)
  port=$(echo "$db" | cut -d: -f2)

  echo "  $svc service:"
  grep -r "$db" deploy/ docker/ 2>/dev/null | head -1 | \
    sed "s/.*:\/\/\([^:]*\):.*/    $svc: \1:$port/" || echo "    ❌ No $svc service reference found"
done
echo ""

# ------------------------------------------------------
# Summary
# ------------------------------------------------------
echo "📊 Configuration Summary:"
echo "  ✅ Neo4j, PostgreSQL, MySQL, Redis configs checked"
echo "  ✅ Connection strings reviewed across environments"
echo "  ✅ Helm chart conflicts detected (Neo4j)"
echo "  ✅ Network service consistency checked"
echo ""
echo "🚀 Configuration validation complete!"
echo "   Next step: ./deploy/deploy-datastores.sh"
