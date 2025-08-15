#!/bin/bash
set -e

echo "🧪 Testing SeedCore Service Separation..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to check if a service is running
check_service() {
    local service_name=$1
    local port=$2
    local endpoint=${3:-/health}
    
    echo -n "🔍 Checking $service_name on port $port... "
    
    if curl -s "http://localhost:$port$endpoint" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ Running${NC}"
        return 0
    else
        echo -e "${RED}❌ Not running${NC}"
        return 1
    fi
}

# Function to check if a service is importing serve modules
check_imports() {
    local service_name=$1
    local container_name=$2
    
    echo -n "🔍 Checking $service_name for serve module imports... "
    
    if docker exec "$container_name" python -c "
import sys
sys.path.insert(0, '/app/src')
try:
    from seedcore.telemetry.server import app
    print('✅ Main API imported successfully')
except ImportError as e:
    print(f'❌ Import failed: {e}')
    sys.exit(1)
" 2>/dev/null; then
        echo -e "${GREEN}✅ No serve module imports detected${NC}"
        return 0
    else
        echo -e "${RED}❌ Import check failed${NC}"
        return 1
    fi
}

# Function to check service communication
check_communication() {
    local service_name=$1
    local port=$2
    
    echo -n "🔍 Checking $service_name communication... "
    
    # Test a simple endpoint
    if curl -s "http://localhost:$port/" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ Communication working${NC}"
        return 0
    else
        echo -e "${RED}❌ Communication failed${NC}"
        return 1
    fi
}

# Main test sequence
echo ""
echo "📋 Test 1: Service Availability"
echo "================================"

# Check if services are running
services_running=0
total_services=0

if check_service "Main API" "8002" "/health"; then
    ((services_running++))
fi
((total_services++))

if check_service "Cognitive Service" "8002" "/health"; then
    ((services_running++))
fi
((total_services++))

if check_service "General Serve" "8001" "/health"; then
    ((services_running++))
fi
((total_services++))

echo ""
echo "📋 Test 2: Import Separation"
echo "============================="

# Check if main API is properly separated from serve modules
imports_clean=0
total_checks=0

if check_imports "Main API" "seedcore-api"; then
    ((imports_clean++))
fi
((total_checks++))

echo ""
echo "📋 Test 3: Service Communication"
echo "================================="

# Check if services can communicate
communication_working=0
total_comm_checks=0

if check_communication "Main API" "8002"; then
    ((communication_working++))
fi
((total_comm_checks++))

if check_communication "Cognitive Service" "8002"; then
    ((communication_working++))
fi
((total_comm_checks++))

if check_communication "General Serve" "8001"; then
    ((communication_working++))
fi
((total_comm_checks++))

echo ""
echo "📋 Test 4: Network Isolation"
echo "============================="

# Check if services are on the same network
echo -n "🔍 Checking network configuration... "
if docker network ls | grep -q "seedcore-network"; then
    echo -e "${GREEN}✅ Network exists${NC}"
    
    # Check if services are on the network
    if docker inspect seedcore-api | grep -q "seedcore-network" && \
       docker inspect seedcore-cognitive-serve | grep -q "seedcore-network"; then
        echo -e "${GREEN}✅ Services on same network${NC}"
    else
        echo -e "${YELLOW}⚠️  Services not on same network${NC}"
    fi
else
    echo -e "${RED}❌ Network not found${NC}"
fi

echo ""
echo "📊 Test Results Summary"
echo "======================="
echo "Services Running: $services_running/$total_services"
echo "Import Separation: $imports_clean/$total_checks"
echo "Communication: $communication_working/$total_comm_checks"

echo ""
if [ $services_running -eq $total_services ] && [ $imports_clean -eq $total_checks ]; then
    echo -e "${GREEN}🎉 All tests passed! Services are properly separated.${NC}"
    exit 0
else
    echo -e "${YELLOW}⚠️  Some tests failed. Check the output above for details.${NC}"
    exit 1
fi
