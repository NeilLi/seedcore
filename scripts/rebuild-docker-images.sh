#!/bin/bash

# Script to rebuild Docker images with consistent naming (without docker- prefix)

echo "🔧 Rebuilding Docker images with consistent naming..."
echo "=================================================="

# Stop all containers first
echo "📦 Stopping all containers..."
cd docker
docker compose down
docker compose -f ray-workers.yml down

# Verify .env file location
if [ ! -f ".env" ]; then
    echo "❌ Error: .env file not found in docker/ directory"
    echo "   Please ensure .env file is located at docker/.env"
    exit 1
fi
echo "✅ .env file found in docker/ directory"

# Remove old images with docker- prefix
echo "🗑️  Removing old images with docker- prefix..."
docker rmi seedcore-ray-head:latest 2>/dev/null || echo "  - seedcore-ray-head:latest not found"
docker rmi seedcore-ray-worker:latest 2>/dev/null || echo "  - seedcore-ray-worker:latest not found"
docker rmi seedcore-api:latest 2>/dev/null || echo "  - seedcore-api:latest not found"
docker rmi seedcore-db-seed:latest 2>/dev/null || echo "  - seedcore-db-seed:latest not found"

# Build new images with consistent naming
echo "🔨 Building new images with consistent naming..."

echo "  - Building seedcore-api:latest..."
docker compose build seedcore-api

echo "  - Building seedcore-ray-head:latest..."
docker compose build seedcore-ray-head

echo "  - Building db-seed:latest..."
docker compose build db-seed

echo "  - Building seedcore-ray-worker:latest..."
docker compose -f ray-workers.yml build seedcore-ray-worker

# Show the new image list
echo ""
echo "✅ Rebuild complete! New image list:"
echo "===================================="
docker images | grep -E "seedcore" | grep -v "docker-"

echo ""
echo "🚀 To start services with new images:"
echo "  cd docker"
echo "  docker compose up -d"
echo "  ./ray-workers.sh start 3" 