#!/usr/bin/env bash
# Helper for common SeedCore Docker tasks
#
#   ./debug-helper.sh start-full         – start ALL services
#   ./debug-helper.sh restart-app        – restart ALL non-DB containers
#   ./debug-helper.sh restart-api        – restart seedcore-api only
#   ./debug-helper.sh logs-head          – follow ray-head logs
#   ./debug-helper.sh logs-api           – follow seedcore-api logs
#   ./debug-helper.sh debug-head         – health & last 100 log lines
#   ./debug-helper.sh status             – show container status
#   ./debug-helper.sh clean              – stop and remove all containers
#   ./debug-helper.sh seed-db            – run database seeding manually
#

set -euo pipefail

COMPOSE_FILE="docker-compose.yml"
PROJECT_NAME="seedcore"

# All services you want to restart in one shot (using service names, not container names)
APP_STACK=(
  node-exporter
  db-seed
  ray-head
  seedcore-api
  ray-metrics-proxy
  ray-proxy
  prometheus
  grafana
)

function start_ray() {
  echo "🚀 Starting Ray stack + databases..."
  docker compose -p $PROJECT_NAME --profile core --profile ray up -d
  echo "✅ Ray stack started!"
  echo "🔗 Ray Dashboard: http://localhost:8265"
  echo "🍽️  Ray Serve API: http://localhost:8000"
}

function start_full() {
  echo "📦 Starting full stack..."
  docker compose -p $PROJECT_NAME --profile core --profile ray --profile api --profile obs up -d
  echo "✅ Full stack started!"
}

function restart_app() {
  echo "🔄  Restarting application stack (databases stay untouched)…"
  
  # 1. First stop ray-workers if they exist (before ray-head)
  if [ -f "ray-workers.yml" ]; then
    echo "🔄  Stopping Ray workers first..."
    docker compose -f ray-workers.yml -p $PROJECT_NAME down
  fi
  
  # 2. Use Docker Compose's dependency resolution to restart services in correct order
  # This mimics the start-full approach but only restarts non-DB services
  echo "🔄  Restarting services using Docker Compose dependency resolution..."
  
  # Stop all non-DB services first
  docker compose -p $PROJECT_NAME stop ray-head seedcore-api ray-metrics-proxy ray-proxy prometheus grafana node-exporter db-seed
  
  # Start them in the correct order using profiles (like start-full does)
  docker compose -p $PROJECT_NAME --profile core --profile ray --profile api --profile obs up -d
  
  # 3. Finally restart ray-workers
  if [ -f "ray-workers.yml" ]; then
    echo "🔄  Starting Ray workers..."
    docker compose -f ray-workers.yml -p $PROJECT_NAME up -d
    echo "✅ Ray workers restarted!"
  else
    echo "ℹ️  No ray-workers.yml found, skipping worker restart"
  fi
  
  echo "✅ Application stack restarted!"
}



function restart_api() {
  echo "🔄 Restarting seedcore-api container..."
  docker compose -p $PROJECT_NAME restart --no-deps seedcore-api
  echo "✅ seedcore-api restarted!"
}

function logs_head() {
  docker compose -p $PROJECT_NAME logs -f --tail=100 ray-head
}

function logs_api() {
  docker compose -p $PROJECT_NAME logs -f --tail=100 seedcore-api
}

function debug_head() {
  echo "🩺  ray-head health status:"
  docker inspect -f '{{ .State.Health.Status }}' seedcore-ray-head || true
  echo "— ray health-check (inside the container) —"
  docker compose -p $PROJECT_NAME exec -T ray-head ray health-check || true
  echo "— last 100 log lines —"
  docker compose -p $PROJECT_NAME logs --tail=100 ray-head
}

function status() {
  echo "📊 Container status:"
  docker compose -p $PROJECT_NAME ps
}

function clean() {
  echo "🧹 Stopping and removing all containers..."
  docker compose -p $PROJECT_NAME down
  echo "✅ All containers stopped and removed!"
}

function seed_db() {
  echo "🌱 Running database seeding..."
  docker compose -p $PROJECT_NAME --profile core --profile seed up db-seed
  echo "✅ Database seeding completed!"
}

case "${1:-}" in
  start-ray)    start_ray    ;;
  start-full)   start_full   ;;
  restart-app)  restart_app  ;;
  restart-api)  restart_api  ;;
  logs-head)    logs_head    ;;
  logs-api)     logs_api     ;;
  debug-head)   debug_head   ;;
  status)       status       ;;
  clean)        clean        ;;
  seed-db)      seed_db      ;;
  *) echo "Usage: $0 {start-ray|start-full|restart-app|restart-api|logs-head|logs-api|debug-head|status|clean|seed-db}"; exit 1 ;;
esac 