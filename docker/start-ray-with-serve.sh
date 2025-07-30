#!/bin/bash

# Start Ray head node
echo "🚀 Starting Ray head node..."
ray start --head \
    --dashboard-host 0.0.0.0 \
    --dashboard-port 8265 \
    --port=6379 \
    --include-dashboard true \
    --metrics-export-port=8080 \
    --num-cpus 1

# Wait for Ray to be ready
echo "⏳ Waiting for Ray to be ready..."
sleep 10

# Deploy a simple Serve application
echo "🚀 Deploying Ray Serve application..."
python /app/scripts/deploy_simple_serve.py

# Keep the container running
echo "✅ Ray head with Serve is ready!"
echo "📊 Dashboard: http://localhost:8265"
echo "🔗 Serve endpoint: http://localhost:8000"

# Block forever
tail -f /dev/null 