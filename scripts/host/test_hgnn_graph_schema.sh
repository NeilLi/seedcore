#!/bin/bash
# Test script for HGNN graph schema (007 migration)
# This script verifies that objects from 007_hgnn_graph_schema.sql are present and queryable

set -euo pipefail

NAMESPACE="${NAMESPACE:-seedcore-dev}"
DB_NAME="${DB_NAME:-seedcore}"
DB_USER="${DB_USER:-postgres}"

echo "🧪 Testing HGNN graph schema (007) ..."
echo "📋 Namespace: $NAMESPACE"
echo "📋 Database: $DB_NAME"
echo "📋 User: $DB_USER"

# Find PostgreSQL pod
echo "🔍 Finding PostgreSQL pod..."
POSTGRES_POD=""
for selector in \
    'app.kubernetes.io/name=postgresql,app.kubernetes.io/component=primary' \
    'app.kubernetes.io/name=postgresql' \
    'app=postgresql'
do
    POSTGRES_POD="$(kubectl -n "$NAMESPACE" get pods -l "$selector" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
    [[ -n "$POSTGRES_POD" ]] && break
done

if [[ -z "$POSTGRES_POD" ]]; then
    echo "❌ Could not locate a Postgres pod in namespace '$NAMESPACE'."
    echo "   Tip: kubectl -n $NAMESPACE get pods --show-labels | grep -i postgres"
    exit 1
fi

echo "✅ Found Postgres pod: $POSTGRES_POD"

# Copy verification script to pod
echo "📝 Copying verification script to pod..."
kubectl -n "$NAMESPACE" cp "verify_hgnn_graph_schema.sql" "$POSTGRES_POD:/tmp/verify_hgnn_graph_schema.sql"

# Run verification script
echo "🚀 Running HGNN schema verification..."
echo "=========================================="

kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
    psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/verify_hgnn_graph_schema.sql"

echo "=========================================="
echo "✅ HGNN schema verification completed!"

# Optional: show view definitions briefly
echo "" 
echo "🔍 Inspecting view columns (heads):"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
    psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ hgnn_edges" | head -20
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
    psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ task_embeddings" | head -20

echo ""
echo "🎉 If you see 'OK' statuses above and no errors, 007 migration is installed correctly."


