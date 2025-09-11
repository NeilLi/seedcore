#!/bin/bash
# Safe rollout script for predicate system without Prometheus/Grafana

set -e

echo "🚀 Starting safe rollout of predicate system..."

# Set safe environment variables
export METRICS_ENABLED=0
export GPU_GUARD_ENABLED=0
export COORD_PREDICATES_PATH=/app/config/predicates-bootstrap.yaml
export CB_ML_TIMEOUT_S=5
export CB_COG_TIMEOUT_S=8
export CB_ORG_TIMEOUT_S=6
export CB_FAIL_THRESHOLD=5
export CB_RESET_S=30

# Optional Redis configuration (will fallback to in-memory if not available)
export REDIS_URL=${REDIS_URL:-"redis://localhost:6379"}

echo "📋 Environment configured:"
echo "  METRICS_ENABLED=$METRICS_ENABLED"
echo "  GPU_GUARD_ENABLED=$GPU_GUARD_ENABLED"
echo "  COORD_PREDICATES_PATH=$COORD_PREDICATES_PATH"
echo "  CB_ML_TIMEOUT_S=$CB_ML_TIMEOUT_S"
echo "  CB_COG_TIMEOUT_S=$CB_COG_TIMEOUT_S"
echo "  CB_ORG_TIMEOUT_S=$CB_ORG_TIMEOUT_S"
echo "  CB_FAIL_THRESHOLD=$CB_FAIL_THRESHOLD"
echo "  CB_RESET_S=$CB_RESET_S"
echo "  REDIS_URL=$REDIS_URL"

# Copy bootstrap configuration if it doesn't exist
if [ ! -f "/app/config/predicates-bootstrap.yaml" ]; then
    echo "📄 Copying bootstrap configuration..."
    cp config/predicates-bootstrap.yaml /app/config/predicates-bootstrap.yaml
fi

# Start the coordinator service
echo "🎯 Starting Coordinator service with safe configuration..."
python -m seedcore.services.coordinator_service

echo "✅ Safe rollout complete!"
echo ""
echo "🔍 To verify the system is working:"
echo "  1. Check status: curl http://localhost:8000/pipeline/predicates/status"
echo "  2. Test routing: curl -X POST http://localhost:8000/pipeline/route-and-execute -H 'Content-Type: application/json' -d '{\"type\": \"health_check\", \"params\": {}}'"
echo "  3. Test anomaly triage: curl -X POST http://localhost:8000/pipeline/anomaly-triage -H 'Content-Type: application/json' -d '{\"agent_id\": \"test\", \"series\": [1,2,3], \"drift_score\": 0.1}'"
echo ""
echo "📊 To enable metrics later:"
echo "  export METRICS_ENABLED=1"
echo "  # Add Prometheus scrape config and restart"
echo ""
echo "🛡️ To enable GPU guard later:"
echo "  export GPU_GUARD_ENABLED=1"
echo "  # Update predicates.yaml and reload"
