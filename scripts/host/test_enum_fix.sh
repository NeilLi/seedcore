#!/bin/bash
# Test script for TaskStatus enum fix
# This script helps verify that the enum case sensitivity issue is resolved

set -euo pipefail

NAMESPACE="${NAMESPACE:-seedcore-dev}"
DB_NAME="${DB_NAME:-seedcore}"
DB_USER="${DB_USER:-postgres}"

echo "🧪 Testing TaskStatus enum fix..."
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
kubectl -n "$NAMESPACE" cp "verify_enum_fix.sql" "$POSTGRES_POD:/tmp/verify_enum_fix.sql"

# Run verification script
echo "🚀 Running enum verification tests..."
echo "=========================================="

kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
    psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/verify_enum_fix.sql"

echo "=========================================="
echo "✅ Enum verification tests completed!"

# Additional verification
echo ""
echo "🔍 Additional verification:"
echo "1. Check enum values:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
    psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT unnest(enum_range(NULL::taskstatus)) as enum_value;"

echo ""
echo "2. Check tasks table structure:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
    psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ tasks" | head -20

echo ""
echo "🎉 If you see no errors above, the enum fix is working correctly!"
echo "💡 Next step: Update your application code to use lowercase status values"
echo "   Example: Use 'queued' instead of 'QUEUED'"
