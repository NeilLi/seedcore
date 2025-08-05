#!/usr/bin/env bash
set -euo pipefail

PROJECT=seedcore
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_MAIN="$SCRIPT_DIR/docker-compose.yml"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
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

# Performance monitoring functions
measure_startup_time() {
    local start_time=$(date +%s.%N)
    log_info "Starting Ray cluster..."
    
    # Start the cluster
    docker compose -f "$COMPOSE_MAIN" -p $PROJECT --profile core --profile ray --profile api --profile obs up -d
    
    # Wait for ray-head to be ready
    local head_start_time=$(date +%s.%N)
    log_info "Waiting for ray-head to be ready..."
    
    # Use the existing wait_for_head function logic
    local max_tries=90
    local delay=2
    local i=0
    
    while (( i < max_tries )); do
        if ! docker ps -qf "name=${PROJECT}-ray-head" &>/dev/null; then
            log_error "ray-head container is not running"
            return 1
        fi
        
        if curl -sf http://localhost:8000/health &>/dev/null; then
            local head_end_time=$(date +%s.%N)
            local head_duration=$(echo "$head_end_time - $head_start_time" | bc -l)
            log_success "ray-head is ready! (${head_duration}s)"
            break
        fi
        
        sleep "$delay"
        (( i++ ))
    done
    
    if (( i >= max_tries )); then
        log_error "ray-head did not become ready in $((max_tries*delay))s"
        return 1
    fi
    
    local end_time=$(date +%s.%N)
    local total_duration=$(echo "$end_time - $start_time" | bc -l)
    
    log_success "Total startup time: ${total_duration}s"
    echo "startup_time=${total_duration}" >> /tmp/ray_performance.log
}

measure_restart_time() {
    local start_time=$(date +%s.%N)
    log_info "Restarting Ray cluster..."
    
    # Restart app services
    docker compose -f "$COMPOSE_MAIN" -p $PROJECT restart --no-deps ray-head seedcore-api ray-metrics-proxy ray-proxy prometheus grafana node-exporter
    
    # Wait for ray-head to be ready
    local head_start_time=$(date +%s.%N)
    log_info "Waiting for ray-head to be ready after restart..."
    
    # Use the existing wait_for_head function logic
    local max_tries=90
    local delay=2
    local i=0
    
    while (( i < max_tries )); do
        if ! docker ps -qf "name=${PROJECT}-ray-head" &>/dev/null; then
            log_error "ray-head container is not running"
            return 1
        fi
        
        if curl -sf http://localhost:8000/health &>/dev/null; then
            local head_end_time=$(date +%s.%N)
            local head_duration=$(echo "$head_end_time - $head_start_time" | bc -l)
            log_success "ray-head is ready! (${head_duration}s)"
            break
        fi
        
        sleep "$delay"
        (( i++ ))
    done
    
    if (( i >= max_tries )); then
        log_error "ray-head did not become ready in $((max_tries*delay))s"
        return 1
    fi
    
    local end_time=$(date +%s.%N)
    local total_duration=$(echo "$end_time - $start_time" | bc -l)
    
    log_success "Total restart time: ${total_duration}s"
    echo "restart_time=${total_duration}" >> /tmp/ray_performance.log
}

show_performance_stats() {
    if [[ ! -f /tmp/ray_performance.log ]]; then
        log_warning "No performance data found. Run startup or restart tests first."
        return
    fi
    
    log_info "Performance Statistics:"
    echo "========================"
    
    if grep -q "startup_time" /tmp/ray_performance.log; then
        echo "Startup Times:"
        grep "startup_time" /tmp/ray_performance.log | tail -5
        echo ""
    fi
    
    if grep -q "restart_time" /tmp/ray_performance.log; then
        echo "Restart Times:"
        grep "restart_time" /tmp/ray_performance.log | tail -5
        echo ""
    fi
    
    # Calculate averages if we have data
    local startup_count=$(grep -c "startup_time" /tmp/ray_performance.log 2>/dev/null || echo "0")
    local restart_count=$(grep -c "restart_time" /tmp/ray_performance.log 2>/dev/null || echo "0")
    
    if [[ "$startup_count" -gt 0 ]]; then
        local avg_startup=$(grep "startup_time" /tmp/ray_performance.log | awk -F'=' '{sum+=$2} END {print sum/NR}')
        log_info "Average startup time: ${avg_startup}s (${startup_count} measurements)"
    fi
    
    if [[ "$restart_count" -gt 0 ]]; then
        local avg_restart=$(grep "restart_time" /tmp/ray_performance.log | awk -F'=' '{sum+=$2} END {print sum/NR}')
        log_info "Average restart time: ${avg_restart}s (${restart_count} measurements)"
    fi
}

clear_performance_data() {
    rm -f /tmp/ray_performance.log
    log_success "Performance data cleared"
}

# Main command handling
case "${1:-}" in
    startup)
        measure_startup_time
        ;;
    restart)
        measure_restart_time
        ;;
    stats)
        show_performance_stats
        ;;
    clear)
        clear_performance_data
        ;;
    *)
        echo "Usage: $0 {startup|restart|stats|clear}"
        echo ""
        echo "Commands:"
        echo "  startup  - Measure startup time of the Ray cluster"
        echo "  restart  - Measure restart time of the Ray cluster"
        echo "  stats    - Show performance statistics"
        echo "  clear    - Clear performance data"
        exit 1
        ;;
esac 