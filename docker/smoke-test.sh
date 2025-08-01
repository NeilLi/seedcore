#!/bin/bash

# Quick smoke test for Ray 2.9.3 + Python 3.10 dashboard fixes
# Based on the suggested checklist

set -e

echo "🚀 Ray Dashboard Smoke Test"
echo "=========================="

echo ""
echo "1️⃣ Building and starting Ray services..."
docker compose build ray-head ray-worker
docker compose up -d ray-head ray-worker

echo ""
echo "2️⃣ Waiting for services to start..."
sleep 30

echo ""
echo "3️⃣ Checking Ray logs for port allocation..."
docker compose logs ray-head | grep -E "dashboard agent|Listening" || echo "No port allocation logs found yet"

echo ""
echo "4️⃣ Testing dashboard API..."
if curl -sf http://localhost:8265/api/version; then
    echo "✅ Dashboard API responding"
    curl -s http://localhost:8265/api/version | head -1
else
    echo "❌ Dashboard API not responding"
    echo "📋 Checking recent logs..."
    docker compose logs --tail=20 ray-head
fi

echo ""
echo "5️⃣ Checking port binding..."
docker compose exec ray-head ss -lntp | grep 5236 || echo "No 5236x ports found"

echo ""
echo "🎉 Smoke test completed!"
echo "📊 Dashboard should be available at: http://localhost:8265" 