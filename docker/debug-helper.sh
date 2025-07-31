#!/bin/bash

# SeedCore Debug Helper Script
# Provides quick commands for common debug operations

set -euo pipefail

PROJECT_NAME="seedcore"
COMPOSE_FILE="docker-compose.yml"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
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

# Show usage
show_usage() {
    cat << EOF
SeedCore Debug Helper

Usage: $0 <command> [options]

Commands:
  start-ray          Start only Ray stack + databases
  start-full         Start full stack (all profiles)
  restart-head       Restart ray-head container only
  restart-api        Restart seedcore-api container only
  logs-head          Show ray-head logs with follow
  logs-api           Show seedcore-api logs with follow
  status             Show container status
  clean              Stop and remove all containers
  seed-db            Run database seeding manually
  help               Show this help message

Examples:
  $0 start-ray                    # Start Ray + DBs for debugging
  $0 restart-head                 # Quick ray-head restart
  $0 logs-head                    # Monitor ray-head logs
  $0 clean                        # Clean slate

EOF
}

# Start Ray stack only
start_ray() {
    log_info "Starting Ray stack + databases..."
    docker compose -p $PROJECT_NAME --profile core --profile ray up -d
    log_success "Ray stack started!"
    log_info "Ray Dashboard: http://localhost:8265"
    log_info "ML Serve API: http://localhost:8000"
}

# Start full stack
start_full() {
    log_info "Starting full stack..."
    docker compose -p $PROJECT_NAME --profile core --profile ray --profile api --profile obs up -d
    log_success "Full stack started!"
}

# Restart ray-head only
restart_head() {
    log_info "Restarting ray-head container..."
    docker compose -p $PROJECT_NAME restart --no-deps ray-head
    log_success "ray-head restarted!"
}

# Restart API only
restart_api() {
    log_info "Restarting seedcore-api container..."
    docker compose -p $PROJECT_NAME restart --no-deps seedcore-api
    log_success "seedcore-api restarted!"
}

# Show logs
logs_head() {
    log_info "Showing ray-head logs (Ctrl+C to exit)..."
    docker logs seedcore-ray-head -f
}

logs_api() {
    log_info "Showing seedcore-api logs (Ctrl+C to exit)..."
    docker logs seedcore-api -f
}

# Show status
status() {
    log_info "Container status:"
    docker compose -p $PROJECT_NAME ps
}

# Clean everything
clean() {
    log_warning "Stopping and removing all containers..."
    docker compose -p $PROJECT_NAME down
    log_success "All containers stopped and removed!"
}

# Seed database manually
seed_db() {
    log_info "Running database seeding..."
    docker compose -p $PROJECT_NAME --profile core --profile seed up db-seed
    log_success "Database seeding completed!"
}

# Main command handler
case "${1:-help}" in
    start-ray)
        start_ray
        ;;
    start-full)
        start_full
        ;;
    restart-head)
        restart_head
        ;;
    restart-api)
        restart_api
        ;;
    logs-head)
        logs_head
        ;;
    logs-api)
        logs_api
        ;;
    status)
        status
        ;;
    clean)
        clean
        ;;
    seed-db)
        seed_db
        ;;
    help|--help|-h)
        show_usage
        ;;
    *)
        log_error "Unknown command: $1"
        show_usage
        exit 1
        ;;
esac 