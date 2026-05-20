#!/usr/bin/env bash
# Stop SeedCore-owned localhost runtime processes and local containers.

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

RUNTIME_DIR="${PROJECT_ROOT}/.local-runtime"
PID_DIR="${RUNTIME_DIR}/pids"
RAY_GCS_PORT="${RAY_GCS_PORT:-26079}"
RAY_CLIENT_PORT="${RAY_CLIENT_PORT:-23001}"
RAY_DASHBOARD_PORT="${RAY_DASHBOARD_PORT:-8265}"
RAY_TEMP_DIR="${RAY_TEMP_DIR:-/tmp/seedcore-ray}"

DRY_RUN=false
WITH_SHARED_SERVICES=false

usage() {
  cat <<EOF
Usage: $(basename "$0") [--dry-run] [--with-shared-services]

Stops SeedCore-owned local runtime:
  - deploy/local Ray/Serve stack
  - API, HAL, gateway, local drill uvicorn processes
  - TypeScript verification/proof/operator services
  - SeedCore Kafka and Neo4j containers

Options:
  --dry-run                Show what would be stopped without killing anything.
  --with-shared-services   Also stop Homebrew postgresql@17 and redis.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --with-shared-services)
      WITH_SHARED_SERVICES=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

log() {
  printf '%s\n' "$*"
}

run_or_echo() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    printf '[dry-run] %q' "$1"
    shift || true
    for arg in "$@"; do
      printf ' %q' "${arg}"
    done
    printf '\n'
  else
    "$@"
  fi
}

pid_command() {
  local pid="$1"
  ps -p "${pid}" -o command= 2>/dev/null || true
}

is_seedcore_command() {
  local command="$1"

  [[ -n "${command}" ]] || return 1
  case "${command}" in
    *"${PROJECT_ROOT}"*) return 0 ;;
    *"seedcore.main:app"*) return 0 ;;
    *"seedcore.gateway_service.main:app"*) return 0 ;;
    *"seedcore.hal.service.main"*) return 0 ;;
    *"seedcore.infra.kafka.bridge"*) return 0 ;;
    *"seedcore.infra.kafka.intent_ingress"*) return 0 ;;
    *"run-serve-app.py"*) return 0 ;;
    *"bootstrap_entry.py"*) return 0 ;;
    *"@seedcore/verification-api"*) return 0 ;;
    *"@seedcore/proof-surface"*) return 0 ;;
    *"@seedcore/operator-console"*) return 0 ;;
    *"ts/services/verification-api"*) return 0 ;;
    *"ts/apps/proof-surface"*) return 0 ;;
    *"ts/apps/operator-console"*) return 0 ;;
    *"--temp-dir='${RAY_TEMP_DIR:-/tmp/seedcore-ray}'"*) return 0 ;;
    *"--temp-dir=${RAY_TEMP_DIR:-/tmp/seedcore-ray}"*) return 0 ;;
    *) return 1 ;;
  esac
}

stop_pid() {
  local pid="$1"
  local label="$2"
  local command

  [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
  command="$(pid_command "${pid}")"
  [[ -n "${command}" ]] || return 1

  if ! is_seedcore_command "${command}"; then
    log "Skip ${label}: pid ${pid} is not a recognized SeedCore process"
    return 1
  fi

  log "Stopping ${label} (pid ${pid})"
  run_or_echo kill "${pid}" || true

  if [[ "${DRY_RUN}" == "false" ]]; then
    for _ in 1 2 3 4 5; do
      kill -0 "${pid}" >/dev/null 2>&1 || return 0
      sleep 1
    done
    log "Force stopping ${label} (pid ${pid})"
    kill -9 "${pid}" >/dev/null 2>&1 || true
  fi
}

clean_pid_file() {
  local pidfile="$1"
  [[ -f "${pidfile}" ]] || return 0

  local pid
  pid="$(tr -d '[:space:]' <"${pidfile}" 2>/dev/null || true)"
  if [[ ! "${pid}" =~ ^[0-9]+$ ]]; then
    log "Removing invalid pid file ${pidfile}"
    run_or_echo rm -f "${pidfile}" || true
    return 0
  fi

  if stop_pid "${pid}" "${pidfile##*/}"; then
    run_or_echo rm -f "${pidfile}" || true
  elif ! kill -0 "${pid}" >/dev/null 2>&1; then
    log "Removing stale pid file ${pidfile}"
    run_or_echo rm -f "${pidfile}" || true
  fi
}

stop_pid_files() {
  [[ -d "${PID_DIR}" ]] || return 0

  while IFS= read -r -d '' pidfile; do
    clean_pid_file "${pidfile}"
  done < <(find "${PID_DIR}" -maxdepth 1 -type f -name '*.pid' -print0 | sort -z)

  while IFS= read -r -d '' pidfile; do
    clean_pid_file "${pidfile}"
  done < <(find "${RUNTIME_DIR}" -maxdepth 1 -type f -name '*.pid' -print0 2>/dev/null | sort -z)
}

stop_matching_processes() {
  local patterns=(
    "seedcore.main:app"
    "seedcore.gateway_service.main:app"
    "seedcore.hal.service.main"
    "seedcore.infra.kafka.bridge"
    "seedcore.infra.kafka.intent_ingress"
    "run-serve-app.py"
    "bootstrap_entry.py"
    "@seedcore/verification-api"
    "@seedcore/proof-surface"
    "@seedcore/operator-console"
    "ts/services/verification-api"
    "ts/apps/proof-surface"
    "ts/apps/operator-console"
  )

  local current_pid="$$"
  local line pid command pattern
  for pattern in "${patterns[@]}"; do
    while IFS= read -r line; do
      pid="${line%% *}"
      command="${line#* }"
      [[ "${pid}" =~ ^[0-9]+$ ]] || continue
      [[ "${pid}" != "${current_pid}" ]] || continue
      [[ "${command}" != *"stop-local-runtime.sh"* ]] || continue
      [[ "${command}" != rg\ -* ]] || continue
      is_seedcore_command "${command}" || continue
      stop_pid "${pid}" "${pattern}" || true
    done < <(ps -axo pid=,command= | awk '{$1=$1; print}' | rg -F "${pattern}" || true)
  done
}

stop_port_listener() {
  local port="$1"
  local label="$2"
  local pids pid command

  pids="$(lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)"
  [[ -n "${pids}" ]] || return 0

  while IFS= read -r pid; do
    [[ "${pid}" =~ ^[0-9]+$ ]] || continue
    command="$(pid_command "${pid}")"
    if is_seedcore_command "${command}"; then
      stop_pid "${pid}" "${label}:${port}"
    else
      log "Port ${port} is in use by a non-SeedCore process (pid ${pid}); leaving it alone"
    fi
  done <<<"${pids}"
}

stop_known_ports() {
  local port label
  local known_ports=(
    "7071:verification-api"
    "7072:proof-surface"
    "7073:operator-console"
    "8000:ray-serve"
    "8001:ray-dashboard"
    "8002:seedcore-api"
    "8003:seedcore-hal"
    "8022:seedcore-gateway"
    "${RAY_DASHBOARD_PORT}:ray-dashboard"
    "${RAY_CLIENT_PORT}:ray-client"
    "${RAY_GCS_PORT}:ray-gcs"
  )

  for entry in "${known_ports[@]}"; do
    port="${entry%%:*}"
    label="${entry#*:}"
    stop_port_listener "${port}" "${label}"
  done
}

stop_ray() {
  log "Stopping Ray runtime"
  if [[ "${DRY_RUN}" == "true" ]]; then
    log "[dry-run] bash ${SCRIPT_DIR}/run-ray-head.sh stop"
    log "[dry-run] ray stop --force"
    return 0
  fi

  bash "${SCRIPT_DIR}/run-ray-head.sh" stop || true
  ray stop --force >/dev/null 2>&1 || true
}

stop_seedcore_containers() {
  if command -v docker >/dev/null 2>&1; then
    if [[ "${DRY_RUN}" == "true" ]]; then
      log "[dry-run] docker compose -f ${SCRIPT_DIR}/docker-compose.kafka.yml down"
      log "[dry-run] docker stop seedcore-kafka seedcore-neo4j"
      return 0
    fi

    if ! docker info >/dev/null 2>&1; then
      log "Docker daemon is not reachable; skipping SeedCore containers"
      return 0
    fi

    if docker compose version >/dev/null 2>&1; then
      log "Stopping local Kafka compose stack"
      run_or_echo docker compose -f "${SCRIPT_DIR}/docker-compose.kafka.yml" down || true
    elif command -v docker-compose >/dev/null 2>&1; then
      log "Stopping local Kafka compose stack"
      run_or_echo docker-compose -f "${SCRIPT_DIR}/docker-compose.kafka.yml" down || true
    fi

    for container in seedcore-kafka seedcore-neo4j; do
      if docker ps -a --format '{{.Names}}' 2>/dev/null | rg -qx "${container}"; then
        log "Stopping container ${container}"
        run_or_echo docker stop "${container}" || true
      fi
    done
  fi
}

stop_shared_services() {
  [[ "${WITH_SHARED_SERVICES}" == "true" ]] || return 0
  command -v brew >/dev/null 2>&1 || return 0

  for service in postgresql@17 redis; do
    log "Stopping Homebrew service ${service}"
    run_or_echo brew services stop "${service}" || true
  done
}

main() {
  log "Stopping SeedCore local runtime from ${PROJECT_ROOT}"
  stop_pid_files
  stop_matching_processes
  stop_ray
  stop_known_ports
  stop_seedcore_containers
  stop_shared_services
  log "SeedCore local runtime stop complete"
}

main "$@"
