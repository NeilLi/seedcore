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

# Ignore SIGTERM during startup to prevent premature shutdown
trap '' SIGTERM

echo "🚀 Starting SeedCore Ray Head with ML Serve..."



# Clean up any existing Ray processes
echo "🧹 Cleaning up any existing Ray processes..."
ray stop || true
pkill -f ray || true
sleep 10             # <-- longer sleep to ensure ports are fully released and TIME_WAIT expires

# Simple port availability check using Python
echo "⏳ checking if port ${DASHBOARD_PORT} is available..."
python3 -c "
import socket
import time
for i in range(10):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('localhost', ${DASHBOARD_PORT}))
        sock.close()
        if result != 0:
            print(f'Port ${DASHBOARD_PORT} is available')
            exit(0)
        else:
            print(f'Port ${DASHBOARD_PORT} still in use, waiting...')
            time.sleep(1)
    except:
        pass
print(f'Port ${DASHBOARD_PORT} check completed')
"

# Start Ray head node with optimized configuration
echo "🔧 Starting Ray head node..."
if ! ray status --address=auto 2>/dev/null | grep -q "Ray is running"; then
    ray start --head \
        --dashboard-host 0.0.0.0 \
        --dashboard-port ${DASHBOARD_PORT} \
        --port=${RAY_PORT} \
        --ray-client-server-port=10001 \
        --include-dashboard true \
        --metrics-export-port=${METRICS_PORT} \
        --num-cpus 1 \
        --temp-dir /tmp/ray \
        --log-style record \
        --disable-usage-stats
else
    echo "✅ Ray is already running"
fi

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