#!/bin/bash
set -euo pipefail

echo "🧪 Testing Standalone SeedCore App Pod"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    local status=$1
    local message=$2
    if [ "$status" = "OK" ]; then
        echo -e "${GREEN}✅ $message${NC}"
    elif [ "$status" = "WARN" ]; then
        echo -e "${YELLOW}⚠️  $message${NC}"
    else
        echo -e "${RED}❌ $message${NC}"
    fi
}

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    print_status "ERROR" "docker-compose or docker compose not found"
    exit 1
fi

# Check if ray-head is running
echo "🔍 Checking if ray-head is running..."
if ! docker ps --format "table {{.Names}}" | grep -q "ray-head"; then
    print_status "ERROR" "ray-head container is not running. Start it first with: docker compose --profile ray up -d ray-head"
    exit 1
fi
print_status "OK" "ray-head container is running"

# Check if ray-head is healthy
echo "🔍 Checking ray-head health..."
if ! docker inspect ray-head --format='{{.State.Health.Status}}' | grep -q "healthy"; then
    print_status "WARN" "ray-head container is not healthy yet. Waiting..."
    echo "⏳ Waiting for ray-head to become healthy..."
    timeout=120
    while [ $timeout -gt 0 ]; do
        if docker inspect ray-head --format='{{.State.Health.Status}}' | grep -q "healthy"; then
            print_status "OK" "ray-head is now healthy"
            break
        fi
        sleep 5
        timeout=$((timeout - 5))
    done
    
    if [ $timeout -le 0 ]; then
        print_status "ERROR" "ray-head did not become healthy within 120 seconds"
        exit 1
    fi
else
    print_status "OK" "ray-head container is healthy"
fi

# Build and start the standalone app pod
echo "🔨 Building standalone app pod..."
if docker compose -f docker/docker-compose.app.standalone.yml build seedcore-app; then
    print_status "OK" "Standalone app pod built successfully"
else
    print_status "ERROR" "Failed to build standalone app pod"
    exit 1
fi

echo "🚀 Starting standalone app pod..."
if docker compose -f docker/docker-compose.app.standalone.yml up -d seedcore-app; then
    print_status "OK" "Standalone app pod started successfully"
else
    print_status "ERROR" "Failed to start standalone app pod"
    exit 1
fi

# Wait for the app pod to be ready
echo "⏳ Waiting for app pod to be ready..."
timeout=180
while [ $timeout -gt 0 ]; do
    if docker inspect seedcore-app --format='{{.State.Health.Status}}' | grep -q "healthy"; then
        print_status "OK" "App pod is healthy"
        break
    fi
    
    # Check if container is running
    if ! docker ps --format "table {{.Names}}" | grep -q "seedcore-app"; then
        print_status "ERROR" "App pod container stopped unexpectedly"
        docker logs seedcore-app
        exit 1
    fi
    
    sleep 5
    timeout=$((timeout - 5))
    echo "   Waiting... ($timeout seconds remaining)"
done

if [ $timeout -le 0 ]; then
    print_status "ERROR" "App pod did not become healthy within 180 seconds"
    echo "📋 App pod logs:"
    docker logs seedcore-app
    exit 1
fi

# Test the health endpoint
echo "🔍 Testing health endpoint..."
if curl -f -s http://localhost:8003/health > /dev/null; then
    print_status "OK" "Health endpoint is responding"
else
    print_status "ERROR" "Health endpoint is not responding"
    exit 1
fi

# Test the API endpoints
echo "🔍 Testing API endpoints..."
if curl -f -s http://localhost:8003/ | grep -q "seedcore"; then
    print_status "OK" "API root endpoint is responding"
else
    print_status "ERROR" "API root endpoint is not responding correctly"
    exit 1
fi

# Check Ray connection
echo "🔍 Verifying Ray connection..."
if docker exec seedcore-app python -c "import ray; print('Ray available')" 2>/dev/null; then
    print_status "OK" "Ray is available in app pod"
else
    print_status "ERROR" "Ray is not available in app pod"
    exit 1
fi

# Check if telemetry server is running
echo "🔍 Checking telemetry server..."
if docker exec seedcore-app python -c "from seedcore.telemetry.server import app; print('Telemetry server available')" 2>/dev/null; then
    print_status "OK" "Telemetry server is available in app pod"
else
    print_status "ERROR" "Telemetry server is not available in app pod"
    exit 1
fi

echo ""
print_status "OK" "🎉 Standalone app pod test completed successfully!"
echo ""
echo "📊 Service Status:"
echo "   - Ray Head: http://localhost:8265"
echo "   - API Server: http://localhost:8003"
echo "   - Health: http://localhost:8003/health"
echo ""
echo "🔧 Useful Commands:"
echo "   - View logs: docker logs seedcore-app"
echo "   - Stop service: docker compose -f docker/docker-compose.app.standalone.yml down"
echo "   - Restart: docker compose -f docker/docker-compose.app.standalone.yml restart seedcore-app"


