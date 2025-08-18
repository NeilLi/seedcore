#!/bin/bash
set -euo pipefail

echo "🛑 Stopping all SeedCore services..."

# Stop Ray workers
echo "⏹️  Stopping Ray workers..."
docker compose -f ray-workers.yml -p seedcore down --remove-orphans 2>/dev/null || true

# Stop main services
echo "⏹️  Stopping main services..."
docker compose -f docker-compose.yml -p seedcore down --remove-orphans 2>/dev/null || true

# Stop any remaining containers
echo "🧹 Cleaning up any remaining containers..."
docker ps -q --filter "name=seedcore" | xargs -r docker stop 2>/dev/null || true
docker ps -q --filter "name=seedcore" | xargs -r docker rm 2>/dev/null || true

echo "✅ All SeedCore services stopped"
