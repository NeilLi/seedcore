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

# Function to check if Ray is ready
check_ray_ready() {
    python -c "
import ray
try:
    ray.init(address='auto', log_to_driver=False)
    print('✅ Ray cluster is ready')
    ray.shutdown()
    exit(0)
except Exception as e:
    print(f'❌ Ray not ready: {e}')
    exit(1)
" 2>/dev/null || return 1
}

# Function to check if Serve is ready
check_serve_ready() {
    # Try health endpoint first, then fallback to salience endpoint
    if curl -s -f http://localhost:${SERVE_PORT}/health >/dev/null 2>&1; then
        return 0
    elif curl -s -f http://localhost:${SERVE_PORT}/ml/score/salience >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

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

echo "⏳ Waiting for Ray cluster to be ready..."
retry_count=0
while [ $retry_count -lt $MAX_RETRIES ]; do
    if check_ray_ready; then
        echo "✅ Ray cluster is ready!"
        break
    fi
    retry_count=$((retry_count + 1))
    echo "🔄 Waiting for Ray... (attempt $retry_count/$MAX_RETRIES)"
    sleep $RETRY_DELAY
done

if [ $retry_count -eq $MAX_RETRIES ]; then
    echo "❌ Failed to start Ray cluster after $MAX_RETRIES attempts"
    exit 1
fi

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

# Wait for Serve to be ready
echo "⏳ Waiting for ML Serve applications to be ready..."
retry_count=0
while [ $retry_count -lt $MAX_RETRIES ]; do
    if check_serve_ready; then
        echo "✅ ML Serve applications are ready!"
        break
    fi
    retry_count=$((retry_count + 1))
    echo "🔄 Waiting for ML Serve... (attempt $retry_count/$MAX_RETRIES)"
    sleep $RETRY_DELAY
done

if [ $retry_count -eq $MAX_RETRIES ]; then
    echo "❌ Failed to start ML Serve applications after $MAX_RETRIES attempts"
    exit 1
fi

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
echo ""
echo "🔍 Health Check:      http://localhost:${SERVE_PORT}/health"
echo "================================================"

# Keep the container running and monitor health
echo "🔄 Starting health monitoring..."
health_check_count=0
while true; do
    health_check_count=$((health_check_count + 1))
    
    # Check Ray cluster health
    if ! check_ray_ready; then
        echo "❌ Ray cluster health check failed (check #$health_check_count)"
        exit 1
    fi
    
    # Check ML Serve health
    if ! check_serve_ready; then
        echo "❌ ML Serve health check failed (check #$health_check_count)"
        exit 1
    fi
    
    # Log health status every 10 checks (every 5 minutes)
    if [ $((health_check_count % 10)) -eq 0 ]; then
        echo "✅ Health check #$health_check_count passed - $(date)"
        echo "📊 Ray cluster and ML Serve are healthy"
    fi
    
    sleep 30
done 