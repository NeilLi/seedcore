#!/bin/bash
set -euo pipefail

# Graceful shutdown
cleanup() {
    echo "🛑 Received shutdown signal, cleaning up..."
    ray stop || true
    exit 0
}
trap cleanup SIGTERM SIGINT

echo "🚀 Starting SeedCore Ray Head with ML Serve..."

# Ensure metrics server is disabled via environment variable
export RAY_DISABLE_METRICS_SERVER=1

# Start Ray head node with more resources
ray start --head \
    --dashboard-host 0.0.0.0 \
    --dashboard-port 8265 \
    --port=6379 \
    --ray-client-server-port=10001 \
    --include-dashboard true \
    --metrics-export-port=8080 \
    --num-cpus 4 \
    --memory 4000000000 \
    --temp-dir /tmp/ray \
    --log-style record \
    --disable-usage-stats \
    --object-store-memory 2000000000

# Wait for Ray to be fully ready
echo "⏳ Waiting for Ray to be fully ready..."
sleep 5

# Start Ray Serve with proper HTTP configuration for Ray 2.9
echo "🔧 Starting Ray Serve with HTTP configuration..."
python -c "
import ray
from ray import serve
import time

# Initialize Ray connection
ray.init()

# Start Serve with proper HTTP configuration for Ray 2.9
# Use default namespace and bind to 0.0.0.0 for external access
serve.start(
    http_options={
        'host': '0.0.0.0',
        'port': 8000
    },
    detached=True
)
print('✅ Ray Serve started successfully in default namespace')
"

# Set RAY_ADDRESS for the serve entrypoint script
# Exports the same Ray Client URL for any subsequent shell commands inside the container
# Keeps one source of truth for the address during manual debugging
# Note: In the head container, we don't need to set RAY_ADDRESS as we connect directly
# export RAY_ADDRESS=ray://localhost:10001

# Deploy applications
python /app/docker/serve_entrypoint.py

echo "🎉 SeedCore Ray Head with ML Serve is ready!"
echo "================================================"
echo "📊 Ray Dashboard:     http://localhost:8265"
echo "🔗 ML Serve API:      http://localhost:8000"
echo "📈 Metrics Export:    http://localhost:8080"
echo "================================================"

# Keep the container running and wait for child processes
tail -f /dev/null 