#!/usr/bin/env bash
set -euo pipefail

PROJECT=seedcore
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_MAIN="$SCRIPT_DIR/docker-compose.yml" 
WORKERS_FILE="$SCRIPT_DIR/ray-workers.yml"
WORKERS_PROJECT="${PROJECT}-workers"               # <── own project name
NETWORK=seedcore-network

APP_SERVICES=(ray-head seedcore-api ray-metrics-proxy ray-dashboard-proxy \
              prometheus grafana node-exporter)

# ---------- utilities ---------------------------------------------------------
network_ensure() { docker network inspect "$NETWORK" &>/dev/null || docker network create "$NETWORK"; }

wait_for_head() {
  local max_tries=90         # 90 × 2 s = 3 minutes
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

    # 2️⃣ Serve HTTP health must return 200
    if curl -sf http://localhost:8000/health &>/dev/null; then
      printf "\r✅ ray-head is ready!%-20s\n" ""
      return 0
    fi

    # 3️⃣ animate spinner
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
  [[ -f "$WORKERS_FILE" ]] || { echo "⚠️  no $WORKERS_FILE – skipping workers"; return; }
  docker compose -f "$WORKERS_FILE" -p "$WORKERS_PROJECT" up -d --scale ray-worker="$n"
}

# ---------- commands ----------------------------------------------------------
cmd_up() {
  local W=${1:-3}
  network_ensure
  docker compose -f "$COMPOSE_MAIN" -p $PROJECT --profile core --profile ray --profile api --profile obs up -d
  wait_for_head
  start_workers "$W"
  echo -e "\n🎉 cluster up → http://localhost:8265\n"
}

cmd_restart() {
  echo "🔄 restarting app tier (DBs stay up, workers will be bounced)…"

  # 1️⃣ stop workers (only their project)
  if [[ -f "$WORKERS_FILE" ]]; then
    echo "⏸️  stopping workers first …"
    CUR_WORKERS=$(docker compose -f "$WORKERS_FILE" -p "$WORKERS_PROJECT" ps --services --filter "status=running" | wc -l)
    docker compose -f "$WORKERS_FILE" -p "$WORKERS_PROJECT" down --remove-orphans
  else
    CUR_WORKERS=0
  fi

  # 2️⃣ bounce app containers via 'restart' (compose file path fixed)
  sleep 5          # <── here, total pause ~9 s; TIME_WAIT normally < 4 s
  docker compose -f "$COMPOSE_MAIN" -p $PROJECT restart --no-deps "${APP_SERVICES[@]}"
  wait_for_head

  # 3️⃣ start workers again
  if (( CUR_WORKERS > 0 )); then
    echo "🚀 restarting $CUR_WORKERS workers …"
    docker compose -f "$WORKERS_FILE" -p "$WORKERS_PROJECT" up -d --scale ray-worker="$CUR_WORKERS"
  fi

  echo "✅ restart complete (head healthy, $CUR_WORKERS workers running)"
}

cmd_down() {
  [[ -f "$WORKERS_FILE" ]] && docker compose -f "$WORKERS_FILE" -p "$WORKERS_PROJECT" down --remove-orphans
  docker compose -f "$COMPOSE_MAIN" -p $PROJECT down --remove-orphans
}

cmd_logs() {
  case "${1:-}" in
    head) docker compose -f "$COMPOSE_MAIN" -p $PROJECT logs -f --tail=100 ray-head ;;
    api)  docker compose -f "$COMPOSE_MAIN" -p $PROJECT logs -f --tail=100 seedcore-api ;;
    *) echo "logs {head|api}"; exit 1 ;;
  esac
}

cmd_status() { docker compose -f "$COMPOSE_MAIN" -p $PROJECT ps; }
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