#!/bin/bash

# Test script for the battle-tested Ray Serve pattern

set -e

echo "🧪 Testing SeedCore Ray Serve Pattern"
echo "======================================"

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running"
    exit 1
fi

# Check if docker-compose is available
if ! command -v docker compose > /dev/null 2>&1; then
    echo "❌ docker compose is not available"
    exit 1
fi

echo "✅ Prerequisites check passed"

# Build the images
echo "🔨 Building Docker images..."
docker compose build seedcore-ray-head seedcore-serve

# Start the head node
echo "🚀 Starting Ray head node..."
docker compose up -d seedcore-ray-head

# Wait for head to be healthy
echo "⏳ Waiting for head node to be healthy..."
for i in {1..60}; do
    if docker compose ps seedcore-ray-head | grep -q "healthy"; then
        echo "✅ Head node is healthy"
        break
    fi
    if [ $i -eq 60 ]; then
        echo "❌ Head node failed to become healthy"
        docker compose logs seedcore-ray-head
        exit 1
    fi
    sleep 2
done

# Start the serve container
echo "🚀 Starting Serve container..."
docker compose up -d seedcore-serve

# Wait for serve to be ready
echo "⏳ Waiting for Serve app to be ready..."
for i in {1..30}; do
    if docker compose logs seedcore-serve | grep -q "🟢 Serve app is live"; then
        echo "✅ Serve app is live"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "❌ Serve app failed to start"
        docker compose logs seedcore-serve
        exit 1
    fi
    sleep 2
done

# Test the endpoints
echo "🧪 Testing Serve endpoints..."
sleep 5

# Test SalienceScorer
echo "Testing SalienceScorer..."
if curl -s http://localhost:8000/SalienceScorer > /dev/null; then
    echo "✅ SalienceScorer endpoint is accessible"
else
    echo "❌ SalienceScorer endpoint failed"
fi

# Test AnomalyDetector
echo "Testing AnomalyDetector..."
if curl -s http://localhost:8000/AnomalyDetector > /dev/null; then
    echo "✅ AnomalyDetector endpoint is accessible"
else
    echo "❌ AnomalyDetector endpoint failed"
fi

# Test ScalingPredictor
echo "Testing ScalingPredictor..."
if curl -s http://localhost:8000/ScalingPredictor > /dev/null; then
    echo "✅ ScalingPredictor endpoint is accessible"
else
    echo "❌ ScalingPredictor endpoint failed"
fi

echo ""
echo "🎉 Pattern test completed successfully!"
echo "📊 Dashboard: http://localhost:8265"
echo "🍽️  Serve endpoints: http://localhost:8000"

# Cleanup
echo ""
echo "🧹 Cleaning up..."
docker compose down

echo "✅ Test completed successfully!" 