#!/usr/bin/env bash
set -euo pipefail

PROJECT=seedcore
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_MAIN="$SCRIPT_DIR/docker-compose.yml" 
WORKERS_FILE="$SCRIPT_DIR/ray-workers.yml"   # checked‑in, no longer generated
NETWORK=seedcore-network

APP_SERVICES=(ray-head seedcore-api \
              prometheus grafana node-exporter)

# ---------- utilities ---------------------------------------------------------
network_ensure() { docker network inspect "$NETWORK" &>/dev/null || docker network create "$NETWORK"; }

wait_for_head_stop() {
  local max_tries=30         # 30 × 2 s = 1 minute
  local delay=2
  local spin='|/-\'          # spinner frames
  local i=0
  local frame

  printf "⏳ waiting for ray-cluster to stop "

  while (( i < max_tries )); do
    # Check if container is still running
    if ! docker ps -qf "name=${PROJECT}-ray-head" &>/dev/null; then
      printf "\r✅ ray-head stopped%-20s\n" ""
      return 0
    fi

    # Animate spinner
    frame=${spin:i%${#spin}:1}
    printf "\r⏳ waiting for ray-head to stop %c  [%2ds] " "$frame" $(( i*delay ))
    sleep "$delay"
    (( i++ ))
  done

  printf "\r❌ ray-head did not stop in $((max_tries*delay))s%-20s\n" ""
  return 1
}

wait_for_head() {
  local max_tries=120        # 120 × 2 s = 4 minutes (increased for slower startup)
  local delay=2
  local spin='|/-\'          # spinner frames
  local i=0
  local frame

  # Pretty output without spamming newlines
  printf "⏳ waiting for ray-cluster "

  while (( i < max_tries )); do
    # 1️⃣ container must exist
    if ! docker ps -qf "name=${PROJECT}-ray-head" &>/dev/null; then
      printf "\r❌ ray-head container is not running%-20s\n" ""
      return 1
    fi

    # 2️⃣ Check if Ray Serve applications are running inside the container
    if docker exec "${PROJECT}-ray-head" python -c "
import ray
from ray import serve
try:
    # Connect to the existing Ray instance
    ray.init()
    # Check if Serve is running and has applications
    status = serve.status()
    if status.applications:
        print('READY')
    else:
        # Check if there are Serve-related processes running
        import subprocess
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        if 'ServeReplica' in result.stdout or 'ServeController' in result.stdout:
            print('READY')
        else:
            print('NOT_READY')
except Exception as e:
    print('ERROR:', str(e))
" 2>/dev/null | grep -q "READY"; then
      printf "\r✅ ray-head is ready!%-20s\n" ""
      return 0
    fi

    # 3️⃣ Fallback: Check HTTP health endpoint (in case port binding works)
    if curl -sf http://localhost:8000/health &>/dev/null; then
      printf "\r✅ ray-head is ready!%-20s\n" ""
      return 0
    fi

    # 4️⃣ animate spinner
    frame=${spin:i%${#spin}:1}
    printf "\r⏳ waiting for ray-head %c  [%2ds] " "$frame" $(( i*delay ))
    sleep "$delay"
    (( i++ ))
  done

  printf "\r❌ ray-head did not become ready in $((max_tries*delay))s%-20s\n" ""
  return 1
}

# Use docker‑compose native scaling instead of generating YAML on the fly
scale_workers() {
  local n=${1:-3}
  echo "🚀 scaling workers to $n replicas…"
  docker compose -f "$COMPOSE_MAIN" -f "$WORKERS_FILE" -p $PROJECT up -d --scale ray-worker=$n
}

# ---------- commands ----------------------------------------------------------
cmd_up() {
  local W=${1:-3}
  echo "🚀 Starting cluster with $W workers..."
  network_ensure
  docker compose -f "$COMPOSE_MAIN" -p $PROJECT --profile core --profile ray --profile api --profile obs up -d
  
  if ! wait_for_head; then
    echo "❌ Failed to wait for ray-head to be ready"
    exit 1
  fi
  
  scale_workers "$W"
  echo -e "\n🎉 cluster up → http://localhost:8265\n"
  echo "📊 Check worker status with: docker compose -f ray-workers.yml -p $PROJECT ps"
}

cmd_restart() {
  echo "🔄 restarting app tier (DBs stay up, workers will be bounced)…"

  if [[ -f "$WORKERS_FILE" ]]; then
    echo "⏸️  stopping workers first …"
    CUR_WORKERS=$(docker compose -f "$COMPOSE_MAIN" -f "$WORKERS_FILE" -p $PROJECT ps ray-worker --filter "status=running" | wc -l)
    docker compose -f "$COMPOSE_MAIN" -f "$WORKERS_FILE" -p $PROJECT down ray-worker --remove-orphans
  else
    CUR_WORKERS=0
  fi

  # Explicitly restart only app services, keeping databases running
  echo "🔄 restarting app services: ${APP_SERVICES[*]}"
  # Use --no-deps to prevent restarting dependencies (like databases)
  docker compose -f "$COMPOSE_MAIN" -p $PROJECT restart --no-deps "${APP_SERVICES[@]}"
  
  if ! wait_for_head; then
    echo "❌ Failed to wait for ray-head to be ready"
    exit 1
  fi

  if (( CUR_WORKERS > 0 )); then
    echo "🚀 restarting $CUR_WORKERS workers …"
    scale_workers "$CUR_WORKERS"
  fi

  echo "✅ restart complete (head healthy, $CUR_WORKERS workers running)"
}

cmd_down() {
  echo "🛑 Stopping all services..."
  # Stop all services including workers, using the same profiles as up command
  docker compose -f "$COMPOSE_MAIN" -f "$WORKERS_FILE" -p $PROJECT --profile core --profile ray --profile api --profile obs down --remove-orphans
  echo "✅ All services stopped"
}

cmd_logs() {
  case "${1:-}" in
    head) docker compose -f "$COMPOSE_MAIN" -p $PROJECT --profile core --profile ray logs -f --tail=100 ray-head ;;
    api)  docker compose -f "$COMPOSE_MAIN" -p $PROJECT --profile core --profile ray --profile api logs -f --tail=100 seedcore-api ;;
    workers) 
      # Use the main project name for consistency
      docker compose -f "$COMPOSE_MAIN" -f "$WORKERS_FILE" -p $PROJECT logs -f --tail=100 ray-worker
      ;;
    *) echo "logs {head|api|workers}"; exit 1 ;;
  esac
}

cmd_status() { 
  echo "📊 Main services:"
  # Show all services except ray-worker to avoid duplication, with simplified format
  docker compose -f "$COMPOSE_MAIN" -p $PROJECT ps --format "table {{.Service}}\t{{.State}}\t{{.Status}}" | grep -v "ray-worker"
  echo ""
  echo "📊 Ray workers:"
  docker compose -f "$COMPOSE_MAIN" -f "$WORKERS_FILE" -p $PROJECT ps ray-worker --format "table {{.Service}}\t{{.State}}\t{{.Status}}" 2>/dev/null || echo "No workers running"
}

# Restart only seedcore-api (keeps everything else untouched)
cmd_restart_api() {
  echo "🔄 restarting seedcore-api …"
  docker compose -f "$COMPOSE_MAIN" -p $PROJECT restart --no-deps seedcore-api
  echo "✅ seedcore-api restarted"
}

cmd_up_worker() {
  if [[ $# -lt 1 ]]; then
    echo "Usage: $0 up-worker <RAY_HEAD_PRIVATE_IP> [num_workers]"
    echo "Note: Only 1 worker per EC2 host is recommended for stability."
    exit 1
  fi

  local HEAD_IP="$1"
  local NUM_WORKERS="${2:-1}"

  if [[ "$NUM_WORKERS" -gt 1 ]]; then
    echo "⚠️  Warning: Only 1 Ray worker per EC2 host is recommended."
    echo "    Continuing with $NUM_WORKERS as requested..."
    echo
  fi

  echo "🚀 Launching $NUM_WORKERS worker(s) connecting to Ray head at $HEAD_IP…"

  local WORKER_IP
  WORKER_IP=$(hostname -I | awk '{print $1}')
  echo "📍 This worker's IP address is $WORKER_IP"

  local PROJECT_ROOT
  PROJECT_ROOT=$(realpath "$SCRIPT_DIR/..")

  local REMOTE_WORKERS_FILE="/tmp/remote-worker-$$.yml"
  cat > "$REMOTE_WORKERS_FILE" << EOF
services:
  ray-worker:
    image: seedcore-ray-worker:latest
    build:
      context: ${PROJECT_ROOT}
      dockerfile: docker/Dockerfile.ray
    shm_size: "3gb"
    working_dir: /app
    environment:
      PYTHONPATH: /app:/app/src
      RAY_LOG_TO_STDERR: "1"
      RAY_BACKEND_LOG_LEVEL: "debug"
      # only if you actually use Ray Client from inside this container:
      RAY_ADDRESS: ray://${HEAD_IP}:10001
      RAY_SERVE_ADDRESS: ${HEAD_IP}:8000
    volumes:
      - ${PROJECT_ROOT}:/app
      - ${PROJECT_ROOT}/artifacts:/data
    restart: unless-stopped
    network_mode: host
    command:
      - bash
      - -lc
      - >
        ray start
        --address=${HEAD_IP}:6380
        --node-ip-address=${WORKER_IP}
        --object-manager-port=8076
        --node-manager-port=8077
        --min-worker-port=11000 --max-worker-port=11020
        --block
    healthcheck:
      test: ["CMD-SHELL", "ps aux | grep -v grep | grep 'ray start' >/dev/null || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 60s
EOF

  docker compose -f "$REMOTE_WORKERS_FILE" -p "$PROJECT" up -d --scale ray-worker="$NUM_WORKERS"
  rm -f "$REMOTE_WORKERS_FILE"

  echo
  echo "✅ Ray worker(s) started and should be connecting to head at $HEAD_IP:6380."
  echo "💡 Dashboard: http://$HEAD_IP:8265"
}


# ---------- entry -------------------------------------------------------------
case "${1:-}" in
  up)       shift; cmd_up   "${1:-3}"   ;;
  restart)         cmd_restart        ;;
  restart-api)     cmd_restart_api    ;;
  down)            cmd_down           ;;
  logs)    shift; cmd_logs "$@"       ;;
  status)          cmd_status         ;;
  up-worker) shift; cmd_up_worker "$@" ;;
  *) echo "Usage: $0 {up|restart|restart-api|down|logs|status|up-worker <RAY_HEAD_PRIVATE_IP> [num_workers]}"; exit 1 ;;
esac 