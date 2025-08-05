#!/usr/bin/env bash
set -euo pipefail

PROJECT=seedcore
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_MAIN="$SCRIPT_DIR/docker-compose.yml" 
WORKERS_FILE="$SCRIPT_DIR/ray-workers.yml"
WORKERS_PROJECT="${PROJECT}-workers"               # <── own project name
NETWORK=seedcore-network

APP_SERVICES=(ray-head seedcore-api ray-proxy \
              prometheus grafana node-exporter)

# ---------- utilities ---------------------------------------------------------
network_ensure() { docker network inspect "$NETWORK" &>/dev/null || docker network create "$NETWORK"; }

wait_for_head_stop() {
  local max_tries=30         # 30 × 2 s = 1 minute
  local delay=2
  local spin='|/-\'          # spinner frames
  local i=0
  local frame

  printf "⏳ waiting for ray-head to stop "

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
  printf "⏳ waiting for ray-head "

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

start_workers() {
  local n=${1:-3}
  echo "🚀 starting $n ray workers..."
  
  # Generate workers configuration dynamically (like ray-workers.sh does)
  cat > "$WORKERS_FILE" << EOF
services:
  ray-worker:
    build:
      context: ..
      dockerfile: docker/Dockerfile.ray
    image: seedcore-ray-worker:latest
    shm_size: '2gb'
    working_dir: /app
    environment:
      PYTHONPATH: /app:/app/src
      # Override RAY_ADDRESS for workers to connect to head container
      RAY_ADDRESS: ray://ray-head:10001
      RAY_worker_stdout_file: /dev/stdout
      RAY_worker_stderr_file: /dev/stderr
      RAY_log_to_driver: 1
      RAY_BACKEND_LOG_LEVEL: info
      RAY_PROMETHEUS_HOST: http://prometheus:9090
      RAY_GRAFANA_HOST: http://grafana:3000
      RAY_GRAFANA_IFRAME_HOST: \${PUBLIC_GRAFANA_URL}
      RAY_PROMETHEUS_NAME: Prometheus
    volumes:
      - ..:/app
      - ./artifacts:/data
    networks:
      - seedcore-network
    restart: unless-stopped
    command: ["wait_for_head.sh",
              "ray-head:6379",
              "ray", "start", "--address=ray-head:6379",
              "--num-cpus", "1", "--block"]
    deploy:
      replicas: $n

networks:
  seedcore-network:
    external: true
EOF
  
  # Use separate project name for workers to avoid conflicts
  docker compose -f "$WORKERS_FILE" -p $WORKERS_PROJECT up -d
  echo "✅ workers started"
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
  
  start_workers "$W"
  echo -e "\n🎉 cluster up → http://localhost:8265\n"
  echo "📊 Check worker status with: docker compose -f ray-workers.yml -p seedcore-workers ps"
}

cmd_restart() {
  echo "🔄 restarting app tier (DBs stay up, workers will be bounced)…"

  if [[ -f "$WORKERS_FILE" ]]; then
    echo "⏸️  stopping workers first …"
    CUR_WORKERS=$(docker compose -f "$WORKERS_FILE" -p $WORKERS_PROJECT ps --services --filter "status=running" | wc -l)
    docker compose -f "$WORKERS_FILE" -p $WORKERS_PROJECT down --remove-orphans
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
    start_workers "$CUR_WORKERS"
  fi

  echo "✅ restart complete (head healthy, $CUR_WORKERS workers running)"
}

cmd_down() {
  [[ -f "$WORKERS_FILE" ]] && docker compose -f "$WORKERS_FILE" -p $WORKERS_PROJECT down --remove-orphans
  docker compose -f "$COMPOSE_MAIN" -p $PROJECT down --remove-orphans
}

cmd_logs() {
  case "${1:-}" in
    head) docker compose -f "$COMPOSE_MAIN" -p $PROJECT logs -f --tail=100 ray-head ;;
    api)  docker compose -f "$COMPOSE_MAIN" -p $PROJECT logs -f --tail=100 seedcore-api ;;
    workers) docker compose -f "$WORKERS_FILE" -p $WORKERS_PROJECT logs -f --tail=100 ;;
    *) echo "logs {head|api|workers}"; exit 1 ;;
  esac
}

cmd_status() { 
  echo "📊 Main services:"
  docker compose -f "$COMPOSE_MAIN" -p $PROJECT ps
  echo ""
  echo "📊 Ray workers:"
  docker compose -f "$WORKERS_FILE" -p $WORKERS_PROJECT ps 2>/dev/null || echo "No workers running"
}
cmd_seed()   { docker compose -f "$COMPOSE_MAIN" -p $PROJECT --profile core --profile seed up db-seed; }

# ---------- entry -------------------------------------------------------------
case "${1:-}" in
  up)       shift; cmd_up   "${1:-3}"   ;;
  restart)         cmd_restart        ;;
  down)            cmd_down           ;;
  logs)    shift; cmd_logs "$@"       ;;
  status)          cmd_status         ;;
  seed-db)         cmd_seed           ;;
  *) echo "Usage: $0 {up|restart|down|logs|status|seed-db}"; exit 1 ;;
esac 