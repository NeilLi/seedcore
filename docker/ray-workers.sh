#!/bin/bash

# Ray Workers Management Script
# This script helps manage Ray worker nodes independently

set -e

WORKERS_FILE="ray-workers.yml"
MAIN_COMPOSE_FILE="docker-compose.yml"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to show usage
show_usage() {
    echo "Ray Workers Management Script"
    echo ""
    echo "Usage: $0 [COMMAND] [OPTIONS]"
    echo ""
    echo "Commands:"
    echo "  start [N]     Start N Ray workers (default: 4)"
    echo "  stop          Stop all Ray workers"
    echo "  restart [N]   Restart N Ray workers (default: 4)"
    echo "  scale N       Scale to N Ray workers"
    echo "  status        Show status of Ray workers"
    echo "  logs          Show logs from all Ray workers"
    echo "  help          Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 start 5    # Start 5 Ray workers"
    echo "  $0 scale 3    # Scale to 3 Ray workers"
    echo "  $0 status     # Show worker status"
}

# Function to check if main services are running
check_main_services() {
    if ! docker compose -f "$MAIN_COMPOSE_FILE" ps ray-head | grep -q "Up"; then
        print_error "Ray head node is not running. Please start the main services first:"
        echo "  docker compose up -d"
        exit 1
    fi
    print_success "Ray head node is running"
}

# Function to generate workers configuration
generate_workers_config() {
    local num_workers=$1
    
    print_status "Generating configuration for $num_workers workers..."
    
    # Create the workers file
    cat > "$WORKERS_FILE" << EOF
services:
  ray-worker:
    build:
      context: ..
      dockerfile: docker/Dockerfile.ray
    shm_size: '2gb'
    working_dir: /app
    environment:
      PYTHONPATH: /app:/app/src
      # ── stream every worker's stdout/stderr to the container log ──
      RAY_worker_stdout_file: /dev/stdout
      RAY_worker_stderr_file: /dev/stderr
      # ── keep the driver  (seedcore‑api)  log lines too ──
      RAY_log_to_driver: 1
      # ── lower Ray's own log level so we still see our INFO lines ──
      RAY_BACKEND_LOG_LEVEL: info
      # ── Ray Dashboard monitoring configuration ──
      RAY_PROMETHEUS_HOST: http://prometheus:9090
      RAY_GRAFANA_HOST: http://grafana:3000
      RAY_GRAFANA_IFRAME_HOST: ${PUBLIC_GRAFANA_URL}
      RAY_PROMETHEUS_NAME: Prometheus
    volumes:
      - ..:/app  # Mounts the project root into /app in the container
      - ./artifacts:/data  # Mount artifacts directory for UUID access
    # Note: ray-head service is defined in main docker-compose.yml
    # Workers connect to ray-head via the shared network
    networks:
      - docker_seedcore-network
    restart: unless-stopped
    # Ray workers connect to the head's Redis port 6379
    command: ray start --address=ray-head:6379 --num-cpus 1 --block
    deploy:
      replicas: $num_workers

networks:
  docker_seedcore-network:
    external: true
EOF

    print_success "Generated configuration for $num_workers workers in $WORKERS_FILE"
}

# Function to start workers
start_workers() {
    local num_workers=${1:-4}
    
    print_status "Starting $num_workers Ray workers..."
    
    check_main_services
    generate_workers_config $num_workers
    
    docker compose -f "$WORKERS_FILE" up -d
    
    print_success "Started $num_workers Ray workers"
    print_status "You can monitor them with: $0 status"
}

# Function to stop workers
stop_workers() {
    print_status "Stopping all Ray workers..."
    
    if [ -f "$WORKERS_FILE" ]; then
        docker compose -f "$WORKERS_FILE" down
        print_success "Stopped all Ray workers"
    else
        print_warning "No workers configuration file found"
    fi
}

# Function to restart workers
restart_workers() {
    local num_workers=${1:-4}
    
    print_status "Restarting $num_workers Ray workers..."
    
    stop_workers
    start_workers $num_workers
}

# Function to scale workers
scale_workers() {
    local num_workers=$1
    
    if [ -z "$num_workers" ]; then
        print_error "Please specify number of workers to scale to"
        show_usage
        exit 1
    fi
    
    print_status "Scaling to $num_workers Ray workers..."
    
    check_main_services
    generate_workers_config $num_workers
    
    # Stop existing workers
    if [ -f "$WORKERS_FILE" ]; then
        docker compose -f "$WORKERS_FILE" down
    fi
    
    # Start new configuration
    docker compose -f "$WORKERS_FILE" up -d
    
    print_success "Scaled to $num_workers Ray workers"
}

# Function to show status
show_status() {
    print_status "Ray Workers Status:"
    echo ""
    
    if [ -f "$WORKERS_FILE" ]; then
        docker compose -f "$WORKERS_FILE" ps
    else
        print_warning "No workers configuration file found"
    fi
    
    echo ""
    print_status "Ray Cluster Status:"
    if docker compose -f "$MAIN_COMPOSE_FILE" ps ray-head | grep -q "Up"; then
        echo "Ray Head: ✅ Running"
        echo "Dashboard: http://localhost:8265"
    else
        echo "Ray Head: ❌ Not running"
    fi
}

# Function to show logs
show_logs() {
    print_status "Showing logs from all Ray workers..."
    
    if [ -f "$WORKERS_FILE" ]; then
        docker compose -f "$WORKERS_FILE" logs -f
    else
        print_warning "No workers configuration file found"
    fi
}

# Main script logic
case "${1:-help}" in
    start)
        start_workers $2
        ;;
    stop)
        stop_workers
        ;;
    restart)
        restart_workers $2
        ;;
    scale)
        scale_workers $2
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs
        ;;
    help|--help|-h)
        show_usage
        ;;
    *)
        print_error "Unknown command: $1"
        show_usage
        exit 1
        ;;
esac 