#!/bin/bash

# Enhanced error handling for production
set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Configuration
RAY_PORT=6379
DASHBOARD_PORT=8265
SERVE_PORT=8000
METRICS_PORT=8080
MAX_RETRIES=30
RETRY_DELAY=3

# Signal handling for graceful shutdown
cleanup() {
    echo "🛑 Received shutdown signal, cleaning up..."
    if command -v ray &> /dev/null; then
        ray stop || true
    fi
    echo "✅ Cleanup completed"
    exit 0
}

# Trap signals for graceful shutdown
trap cleanup SIGTERM SIGINT

echo "🚀 Starting SeedCore Ray Head with ML Serve..."



# Clean up any existing Ray processes
echo "🧹 Cleaning up any existing Ray processes..."
ray stop || true
pkill -f ray || true
sleep 2

# Start Ray head node with optimized configuration
echo "🔧 Starting Ray head node..."
ray start --head \
    --dashboard-host 0.0.0.0 \
    --dashboard-port ${DASHBOARD_PORT} \
    --port=${RAY_PORT} \
    --ray-client-server-port=10001 \
    --include-dashboard true \
    --metrics-export-port=${METRICS_PORT} \
    --num-cpus 1 \
    --temp-dir /tmp/ray \
    --log-style record

echo "⏳ Starting Ray cluster..."

# Start Ray Serve with proper configuration
echo "🚀 Starting Ray Serve..."
python -c "
import ray
from ray import serve
import os

# Initialize Ray connection - use 'auto' when running in same container
ray.init(address='auto', log_to_driver=False, namespace='serve')

# Start Serve with external access
serve.start(
    detached=True,
    http_options={
        'host': '0.0.0.0',
        'port': ${SERVE_PORT}
    }
)
print('✅ Ray Serve started successfully')
"

# Deploy ML applications
echo "🚀 Deploying ML applications..."
python /app/docker/serve_entrypoint.py

echo "⏳ Deploying ML applications..."

# Display status and endpoints
echo ""
echo "🎉 SeedCore Ray Head with ML Serve is ready!"
echo "================================================"
echo "📊 Ray Dashboard:     http://localhost:${DASHBOARD_PORT}"
echo "🔗 ML Serve API:      http://localhost:${SERVE_PORT}"
echo "📈 Metrics Export:    http://localhost:${METRICS_PORT}"
echo ""
echo "🤖 Available ML Endpoints:"
echo "   • Salience Scoring:    http://localhost:${SERVE_PORT}/ml/score/salience"
echo "   • Anomaly Detection:   http://localhost:${SERVE_PORT}/ml/detect/anomaly"
echo "   • Scaling Prediction:  http://localhost:${SERVE_PORT}/ml/predict/scaling"
echo "================================================"

# Keep the container running
echo "🔄 Ray head container is running..."
echo "📊 Health checks are handled by Docker Compose"
echo "🔍 Monitor logs with: docker logs seedcore-ray-head -f"

# Keep the container alive
while true; do
    sleep 60
done 