#!/bin/bash

# Quick Start Script for Salience Scoring Service
# This script automates the complete setup and validation process

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Check if we're in the right directory
if [ ! -f "docker/docker-compose.yml" ]; then
    log_error "Please run this script from the project root directory"
    echo "Usage: ./scripts/quick_start_salience.sh"
    exit 1
fi

echo "🎯 SeedCore Salience Scoring Service - Quick Start"
echo "=================================================="

# Step 1: Check dependencies
log_info "Step 1: Checking dependencies..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    log_error "Docker is not running. Please start Docker and try again."
    exit 1
fi

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    log_error "docker-compose is not installed. Please install Docker Compose."
    exit 1
fi

log_success "Dependencies check passed"

# Step 2: Start the cluster
log_info "Step 2: Starting SeedCore cluster..."

cd docker

# Check if cluster is already running
if docker-compose -p seedcore ps | grep -q "Up"; then
    log_warning "Cluster is already running. Stopping and restarting..."
    docker-compose -p seedcore down --remove-orphans
fi

# Start the cluster
log_info "Starting core services..."
docker-compose -p seedcore up -d postgres mysql neo4j prometheus grafana node-exporter

log_info "Starting Ray stack and API..."
docker-compose -p seedcore up -d ray-head ray-serve seedcore-api

log_info "Starting proxy services..."
docker-compose -p seedcore up -d ray-metrics-proxy ray-dashboard-proxy

# Wait for head node to be healthy
log_info "Waiting for Ray head node to be healthy..."
for i in {1..60}; do
    if docker-compose -p seedcore ps ray-head | grep -q "healthy"; then
        log_success "Ray head node is healthy"
        break
    fi
    if [ $i -eq 60 ]; then
        log_error "Ray head node failed to become healthy"
        docker-compose -p seedcore logs ray-head
        exit 1
    fi
    sleep 2
done

# Start Ray workers
log_info "Starting Ray workers..."
./ray-workers.sh start 3

cd ..

log_success "Cluster startup completed"

# Step 3: Train the salience model
log_info "Step 3: Training salience model..."

if [ ! -f "src/seedcore/ml/models/salience_model.pkl" ]; then
    log_info "Training new salience model..."
    python scripts/train_salience_model.py
    if [ $? -eq 0 ]; then
        log_success "Model training completed"
    else
        log_error "Model training failed"
        exit 1
    fi
else
    log_success "Trained model already exists"
fi

# Step 4: Deploy Ray Serve
log_info "Step 4: Deploying Ray Serve..."

python scripts/deploy_ml_serve.py
if [ $? -eq 0 ]; then
    log_success "Ray Serve deployment completed"
else
    log_error "Ray Serve deployment failed"
    exit 1
fi

# Step 5: Wait for services to be ready
log_info "Step 5: Waiting for services to be ready..."

# Wait for API to be ready
log_info "Waiting for API server..."
for i in {1..30}; do
    if curl -s http://localhost/health > /dev/null 2>&1; then
        log_success "API server is ready"
        break
    fi
    if [ $i -eq 30 ]; then
        log_error "API server failed to start"
        docker-compose -p seedcore logs seedcore-api
        exit 1
    fi
    sleep 2
done

# Wait for salience service to be ready
log_info "Waiting for salience service..."
for i in {1..30}; do
    if curl -s http://localhost/salience/health > /dev/null 2>&1; then
        log_success "Salience service is ready"
        break
    fi
    if [ $i -eq 30 ]; then
        log_error "Salience service failed to start"
        exit 1
    fi
    sleep 2
done

# Step 6: Run validation tests
log_info "Step 6: Running validation tests..."

python scripts/validate_salience_container.py
if [ $? -eq 0 ]; then
    log_success "All validation tests passed"
else
    log_warning "Some validation tests failed. Check the output above."
fi

# Step 7: Display service information
echo ""
echo "🎉 SeedCore Salience Scoring Service is ready!"
echo "=============================================="
echo ""
echo "📊 Service URLs:"
echo "   🌐 API Server: http://localhost"
echo "   📚 API Docs: http://localhost/docs"
echo "   🔧 Ray Dashboard: http://localhost:8265"
echo "   📈 Grafana: http://localhost:3000 (admin/seedcore)"
echo "   📊 Prometheus: http://localhost:9090"
echo ""
echo "🧪 Salience Service Endpoints:"
echo "   🔍 Health Check: http://localhost/salience/health"
echo "   ℹ️  Service Info: http://localhost/salience/info"
echo "   🎯 Single Scoring: POST http://localhost/salience/score"
echo "   📦 Batch Scoring: POST http://localhost/salience/score/batch"
echo ""
echo "🔧 Management Commands:"
echo "   📊 Check status: docker-compose -p seedcore ps"
echo "   📋 View logs: docker-compose -p seedcore logs seedcore-api"
echo "   🔄 Restart API: docker-compose -p seedcore restart seedcore-api"
echo "   🛑 Stop cluster: cd docker && docker-compose -p seedcore down"
echo ""
echo "🧪 Testing Commands:"
echo "   🎯 Quick test: curl http://localhost/salience/health"
echo "   📊 Full validation: python scripts/validate_salience_container.py"
echo "   🤖 Agent test: curl -X POST http://localhost/tier0/agents/create -H 'Content-Type: application/json' -d '{\"agent_id\": \"test_agent\", \"role_probs\": {\"E\": 0.7, \"S\": 0.2, \"O\": 0.1}}'"
echo ""
echo "📚 Documentation:"
echo "   📖 Operations Guide: docs/guides/salience-service-operations.md"
echo "   🐳 Docker Guide: docs/guides/docker-setup-guide.md"
echo "   ⚡ Quick Reference: docs/guides/QUICK_REFERENCE.md"
echo ""

# Step 8: Optional - Run a quick test
read -p "Would you like to run a quick salience scoring test? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    log_info "Running quick salience scoring test..."
    
    # Test data
    test_data='[{
        "task_risk": 0.8,
        "failure_severity": 0.9,
        "agent_capability": 0.7,
        "system_load": 0.6,
        "memory_usage": 0.5,
        "cpu_usage": 0.4,
        "response_time": 2.0,
        "error_rate": 0.1,
        "task_complexity": 0.8,
        "user_impact": 0.9,
        "business_criticality": 0.8,
        "agent_memory_util": 0.3
    }]'
    
    response=$(curl -s -X POST "http://localhost/salience/score" \
        -H "Content-Type: application/json" \
        -d "$test_data")
    
    if [ $? -eq 0 ]; then
        score=$(echo "$response" | grep -o '"scores":\[[0-9.]*\]' | grep -o '[0-9.]*')
        log_success "Salience scoring test successful!"
        echo "   Score: $score"
        echo "   Response: $response"
    else
        log_error "Salience scoring test failed"
    fi
fi

log_success "Quick start completed successfully!"
echo ""
echo "🚀 Your SeedCore Salience Scoring Service is now running!"
echo "   Use the URLs and commands above to interact with the system."
echo ""
echo "💡 Tip: Run 'python scripts/validate_salience_container.py' anytime to verify the system is working correctly." 