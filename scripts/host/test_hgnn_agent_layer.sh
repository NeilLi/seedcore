#!/bin/bash
# Test script for HGNN agent/organ layer (008 migration)
# Verifies objects from 008_hgnn_agent_layer.sql and extended hgnn_edges view

set -euo pipefail

NAMESPACE="${NAMESPACE:-seedcore-dev}"
DB_NAME="${DB_NAME:-seedcore}"
DB_USER="${DB_USER:-postgres}"

echo "🧪 Testing HGNN agent/organ layer (008) ..."
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
kubectl -n "$NAMESPACE" cp "verify_hgnn_agent_layer.sql" "$POSTGRES_POD:/tmp/verify_hgnn_agent_layer.sql"

# Run verification script
echo "🚀 Running HGNN agent/organ layer verification..."
echo "=========================================="

kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
    psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/verify_hgnn_agent_layer.sql"

echo "=========================================="
echo "✅ HGNN agent/organ layer verification completed!"

# Optional: show a couple of view columns
echo ""
echo "🔍 Inspecting view columns (head):"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
    psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ hgnn_edges" | head -20

echo ""
echo "🎉 If you see 'OK' statuses above and no errors, 008 migration is installed correctly."


