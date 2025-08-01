#!/usr/bin/env bash
set -euo pipefail

PROJECT=seedcore
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

monitor_startup() {
    local start_time=$(date +%s.%N)
    log_info "Starting Ray head startup monitoring..."
    
    # Start the container
    local container_start=$(date +%s.%N)
    log_info "Starting ray-head container..."
    docker compose -f "$SCRIPT_DIR/docker-compose.yml" -p $PROJECT up -d ray-head
    
    # Wait for container to be running
    local container_running=false
    local attempts=0
    while [[ "$container_running" == "false" && $attempts -lt 30 ]]; do
        if docker ps -qf "name=${PROJECT}-ray-head" &>/dev/null; then
            container_running=true
            local container_ready=$(date +%s.%N)
            local container_duration=$(echo "$container_ready - $container_start" | bc -l)
            log_success "Container running after ${container_duration}s"
        else
            sleep 2
            ((attempts++))
        fi
    done
    
    if [[ "$container_running" == "false" ]]; then
        log_error "Container failed to start within 60s"
        return 1
    fi
    
    # Monitor startup phases
    local phase_start=$(date +%s.%N)
    log_info "Monitoring startup phases..."
    
    # Phase 1: Ray head initialization
    local ray_ready=false
    attempts=0
    while [[ "$ray_ready" == "false" && $attempts -lt 60 ]]; do
        if docker logs seedcore-ray-head 2>&1 | grep -q "Started a local Ray instance"; then
            ray_ready=true
            local ray_ready_time=$(date +%s.%N)
            local ray_duration=$(echo "$ray_ready_time - $container_ready" | bc -l)
            log_success "Ray head ready after ${ray_duration}s"
        else
            sleep 2
            ((attempts++))
        fi
    done
    
    # Phase 2: Ray Serve deployment
    local serve_ready=false
    attempts=0
    while [[ "$serve_ready" == "false" && $attempts -lt 60 ]]; do
        if docker logs seedcore-ray-head 2>&1 | grep -q "Application.*is ready"; then
            serve_ready=true
            local serve_ready_time=$(date +%s.%N)
            local serve_duration=$(echo "$serve_ready_time - $ray_ready_time" | bc -l)
            log_success "Ray Serve ready after ${serve_duration}s"
        else
            sleep 2
            ((attempts++))
        fi
    done
    
    # Phase 3: Health endpoint
    local health_ready=false
    attempts=0
    while [[ "$health_ready" == "false" && $attempts -lt 60 ]]; do
        if curl -sf http://localhost:8000/health &>/dev/null; then
            health_ready=true
            local health_ready_time=$(date +%s.%N)
            local health_duration=$(echo "$health_ready_time - $serve_ready_time" | bc -l)
            log_success "Health endpoint ready after ${health_duration}s"
        else
            sleep 2
            ((attempts++))
        fi
    done
    
    # Final timing
    local end_time=$(date +%s.%N)
    local total_duration=$(echo "$end_time - $start_time" | bc -l)
    
    echo ""
    log_info "Startup Performance Summary:"
    echo "================================"
    echo "Container startup: ${container_duration}s"
    echo "Ray head init:     ${ray_duration}s"
    echo "Ray Serve deploy:  ${serve_duration}s"
    echo "Health endpoint:   ${health_duration}s"
    echo "Total startup:     ${total_duration}s"
    echo "================================"
    
    # Performance analysis
    if (( $(echo "$total_duration < 60" | bc -l) )); then
        log_success "Excellent startup performance (< 60s)"
    elif (( $(echo "$total_duration < 90" | bc -l) )); then
        log_info "Good startup performance (< 90s)"
    elif (( $(echo "$total_duration < 120" | bc -l) )); then
        log_warning "Acceptable startup performance (< 120s)"
    else
        log_error "Poor startup performance (> 120s)"
    fi
    
    # Bottleneck identification
    local max_phase=$(echo "$container_duration $ray_duration $serve_duration $health_duration" | tr ' ' '\n' | sort -nr | head -1)
    if (( $(echo "$max_phase == $ray_duration" | bc -l) )); then
        log_warning "Bottleneck: Ray head initialization (${ray_duration}s)"
    elif (( $(echo "$max_phase == $serve_duration" | bc -l) )); then
        log_warning "Bottleneck: Ray Serve deployment (${serve_duration}s)"
    elif (( $(echo "$max_phase == $health_duration" | bc -l) )); then
        log_warning "Bottleneck: Health endpoint readiness (${health_duration}s)"
    fi
}

# Main execution
case "${1:-}" in
    monitor)
        monitor_startup
        ;;
    *)
        echo "Usage: $0 {monitor}"
        echo ""
        echo "Commands:"
        echo "  monitor  - Monitor Ray head startup performance"
        exit 1
        ;;
esac 