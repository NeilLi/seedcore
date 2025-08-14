#!/bin/bash

# Cleanup Data Stores from Kubernetes Cluster
# This script removes PostgreSQL, MySQL, Redis, and Neo4j deployments

set -e

echo "🧹 Cleaning up data stores from Kubernetes cluster..."

# Remove Neo4j
echo "🗑️  Removing Neo4j..."
helm uninstall neo4j -n seedcore-dev --wait || true

# Remove Redis
echo "🗑️  Removing Redis..."
helm uninstall redis -n seedcore-dev --wait || true

# Remove MySQL
echo "🗑️  Removing MySQL..."
helm uninstall mysql -n seedcore-dev --wait || true

# Remove PostgreSQL
echo "🗑️  Removing PostgreSQL..."
helm uninstall postgresql -n seedcore-dev --wait || true

# Remove PVCs (optional - uncomment if you want to remove data)
# echo "🗑️  Removing Persistent Volume Claims..."
# kubectl delete pvc -n seedcore-dev -l app.kubernetes.io/name || true

echo "✅ All data stores cleaned up successfully!"
echo ""
echo "⚠️  Note: Persistent Volume Claims (PVCs) were not removed by default."
echo "   If you want to remove all data, uncomment the PVC removal line in this script."


