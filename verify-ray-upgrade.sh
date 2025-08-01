#!/bin/bash

# Ray 2.20.0 Upgrade Verification Script
# This script verifies that all containers are using Ray 2.20.0 consistently

set -e

echo "🔍 Verifying Ray 2.20.0 Upgrade..."
echo "=================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to check if container exists and is running
check_container() {
    local container_name=$1
    if docker ps --format "table {{.Names}}" | grep -q "^${container_name}$"; then
        return 0
    else
        return 1
    fi
}

# Function to get Ray version from container
get_ray_version() {
    local container_name=$1
    if check_container "$container_name"; then
        docker exec "$container_name" python -c "import ray; print(ray.__version__)" 2>/dev/null || echo "Failed to get version"
    else
        echo "Container not running"
    fi
}

echo -e "\n📋 Checking Ray versions in all containers:"
echo "----------------------------------------"

# Check Ray head node
echo -n "Ray Head Node (seedcore-ray-head): "
RAY_HEAD_VERSION=$(get_ray_version "seedcore-ray-head")
if [[ "$RAY_HEAD_VERSION" == "2.20.0" ]]; then
    echo -e "${GREEN}✅ $RAY_HEAD_VERSION${NC}"
else
    echo -e "${RED}❌ $RAY_HEAD_VERSION${NC}"
fi

# Check Ray workers
echo -n "Ray Worker (seedcore-ray-worker): "
RAY_WORKER_VERSION=$(get_ray_version "seedcore-ray-worker")
if [[ "$RAY_WORKER_VERSION" == "2.20.0" ]]; then
    echo -e "${GREEN}✅ $RAY_WORKER_VERSION${NC}"
else
    echo -e "${RED}❌ $RAY_WORKER_VERSION${NC}"
fi

# Check application container
echo -n "Application (seedcore-db-seed): "
APP_VERSION=$(get_ray_version "seedcore-db-seed")
if [[ "$APP_VERSION" == "2.20.0" ]]; then
    echo -e "${GREEN}✅ $APP_VERSION${NC}"
else
    echo -e "${RED}❌ $APP_VERSION${NC}"
fi

echo -e "\n🔧 Checking Ray cluster status:"
echo "-------------------------------"

# Check if Ray head is running
if check_container "seedcore-ray-head"; then
    echo -n "Ray Cluster Status: "
    CLUSTER_STATUS=$(docker exec seedcore-ray-head ray status 2>/dev/null | head -1 || echo "Failed to get status")
    if [[ "$CLUSTER_STATUS" == *"Ray cluster is running"* ]]; then
        echo -e "${GREEN}✅ $CLUSTER_STATUS${NC}"
    else
        echo -e "${YELLOW}⚠️  $CLUSTER_STATUS${NC}"
    fi
else
    echo -e "${RED}❌ Ray head container not running${NC}"
fi

echo -e "\n🌐 Checking Ray dashboard:"
echo "---------------------------"

# Check Ray dashboard
if check_container "seedcore-ray-head"; then
    echo -n "Ray Dashboard (http://localhost:8265): "
    if curl -s http://localhost:8265 > /dev/null 2>&1; then
        echo -e "${GREEN}✅ Accessible${NC}"
    else
        echo -e "${YELLOW}⚠️  Not accessible (may be starting up)${NC}"
    fi
else
    echo -e "${RED}❌ Ray head not running${NC}"
fi

echo -e "\n📊 Checking container resource usage:"
echo "-------------------------------------"

# Check container resource usage
if check_container "seedcore-ray-head"; then
    echo "Ray Head Memory Usage:"
    docker stats seedcore-ray-head --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}"
fi

if check_container "seedcore-ray-worker"; then
    echo -e "\nRay Worker Memory Usage:"
    docker stats seedcore-ray-worker --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}"
fi

echo -e "\n🧪 Testing Ray functionality:"
echo "----------------------------"

# Test basic Ray functionality
if check_container "seedcore-ray-head"; then
    echo -n "Basic Ray Test: "
    TEST_RESULT=$(docker exec seedcore-ray-head python -c "
import ray
try:
    ray.init()
    @ray.remote
    def hello():
        return 'Hello from Ray 2.20.0!'
    result = ray.get(hello.remote())
    print('SUCCESS: ' + result)
    ray.shutdown()
except Exception as e:
    print('FAILED: ' + str(e))
" 2>/dev/null || echo "FAILED: Container error")
    
    if [[ "$TEST_RESULT" == *"SUCCESS"* ]]; then
        echo -e "${GREEN}✅ $TEST_RESULT${NC}"
    else
        echo -e "${RED}❌ $TEST_RESULT${NC}"
    fi
else
    echo -e "${RED}❌ Ray head not running${NC}"
fi

echo -e "\n📝 Summary:"
echo "----------"

# Count successful checks
SUCCESS_COUNT=0
TOTAL_CHECKS=0

[[ "$RAY_HEAD_VERSION" == "2.20.0" ]] && ((SUCCESS_COUNT++))
((TOTAL_CHECKS++))

[[ "$RAY_WORKER_VERSION" == "2.20.0" ]] && ((SUCCESS_COUNT++))
((TOTAL_CHECKS++))

[[ "$APP_VERSION" == "2.20.0" ]] && ((SUCCESS_COUNT++))
((TOTAL_CHECKS++))

echo -e "Ray Version Consistency: ${SUCCESS_COUNT}/${TOTAL_CHECKS} containers using Ray 2.20.0"

if [[ $SUCCESS_COUNT -eq $TOTAL_CHECKS ]]; then
    echo -e "${GREEN}🎉 All containers are using Ray 2.20.0 consistently!${NC}"
    exit 0
else
    echo -e "${YELLOW}⚠️  Some containers may need to be rebuilt or restarted${NC}"
    echo -e "\nTo rebuild containers:"
    echo "cd docker"
    echo "docker compose --profile ray build --no-cache"
    echo "docker compose --profile ray up -d"
    exit 1
fi 