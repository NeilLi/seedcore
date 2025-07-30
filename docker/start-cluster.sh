#!/bin/bash

# One-liner to spin up the full Ray Serve cluster
echo "🚀 Starting SeedCore Ray Serve cluster..."

# Create the external network if it doesn't exist
docker network create seedcore-network 2>/dev/null || true

# Start all core services (databases, monitoring, Ray stack)
echo "📦 Starting core services..."
docker compose -p seedcore up -d postgres mysql neo4j prometheus grafana node-exporter

# Start Ray stack and API
echo "🚀 Starting Ray stack and API..."
docker compose -p seedcore up -d ray-head ray-serve seedcore-api

# Start proxy services
echo "🌐 Starting proxy services..."
docker compose -p seedcore up -d ray-metrics-proxy ray-dashboard-proxy

# Wait for head node to be healthy before starting workers
echo "⏳ Waiting for head node to be healthy..."
for i in {1..60}; do
    if docker compose -p seedcore ps ray-head | grep -q "healthy"; then
        echo "✅ Head node is healthy"
        break
    fi
    if [ $i -eq 60 ]; then
        echo "❌ Head node failed to become healthy"
        docker compose -p seedcore logs ray-head
        exit 1
    fi
    sleep 2
done

# Start workers using the ray-workers.sh script
echo "🚀 Starting Ray workers..."
./ray-workers.sh start 3

echo "✅ Cluster startup initiated!"
echo ""
echo "📊 Monitoring & Observability:"
echo "   🔗 Ray Dashboard: http://localhost:8265"
echo "   📈 Prometheus: http://localhost:9090"
echo "   📊 Grafana: http://localhost:3000"
echo "   📊 Node Exporter: http://localhost:9100"
echo ""
echo "🌐 Application Services:"
echo "   🍽️  Ray Serve: http://localhost:8000"
echo "   🌐 API: http://localhost:80"
echo "   🔄 Metrics Proxy: http://localhost:8081"
echo "   📊 Dashboard Proxy: http://localhost:8082"
echo ""
echo "🗄️  Databases:"
echo "   🐘 PostgreSQL: localhost:5432"
echo "   🐬 MySQL: localhost:3306"
echo "   🕸️  Neo4j: http://localhost:7474"
echo ""
echo "📊 Monitor progress with: docker compose logs -f seedcore-ray-head" 