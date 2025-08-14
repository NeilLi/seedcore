#!/bin/bash

# Cleanup Docker Network for SeedCore Local Development
# This script removes the external Docker network

set -e

echo "🧹 Cleaning up Docker network for SeedCore..."

# Check if network exists
if docker network ls | grep -q "seedcore-network"; then
    echo "⚠️  WARNING: This will remove the 'seedcore-network' and all containers using it"
    echo "   Make sure all containers are stopped first!"
    echo ""
    read -p "Are you sure you want to continue? (y/N): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "🛑 Stopping all containers using seedcore-network..."
        docker compose down --remove-orphans || true
        
        echo "🗑️  Removing 'seedcore-network'..."
        docker network rm seedcore-network
        echo "✅ Network 'seedcore-network' removed successfully"
    else
        echo "❌ Operation cancelled"
        exit 0
    fi
else
    echo "✅ Network 'seedcore-network' doesn't exist"
fi

echo ""
echo "📋 Remaining networks:"
docker network ls --filter name=seedcore || echo "No seedcore networks found"


