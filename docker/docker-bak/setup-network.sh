#!/bin/bash

# Setup Docker Network for SeedCore Local Development
# This script creates the external Docker network needed for the compose setup

set -e

echo "🔧 Setting up Docker network for SeedCore..."

# Check if network already exists
if docker network ls | grep -q "seedcore-network"; then
    echo "✅ Network 'seedcore-network' already exists"
else
    echo "📡 Creating 'seedcore-network' bridge network..."
    docker network create --driver bridge seedcore-network
    echo "✅ Network 'seedcore-network' created successfully"
fi

echo ""
echo "🌐 Network configuration:"
docker network inspect seedcore-network --format='{{.Name}}: {{.Driver}}'

echo ""
echo "📋 Available networks:"
docker network ls --filter name=seedcore

echo ""
echo "🚀 You can now run your Docker Compose services:"
echo "   # Start core data stores:"
echo "   docker compose --profile core up -d"
echo ""
echo "   # Start Ray cluster:"
echo "   docker compose --profile ray up -d"
echo ""
echo "   # Start API:"
echo "   docker compose --profile api up -d"
echo ""
echo "   # Start observability stack:"
echo "   docker compose --profile obs up -d"
echo ""
echo "   # Or start everything:"
echo "   docker compose --profile core --profile ray --profile api --profile obs up -d"
