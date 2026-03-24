#!/usr/bin/env bash
# Experimental localhost Serve stack for SeedCore on a single-node Ray head.

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

source "${SCRIPT_DIR}/host-env.sh"

RUNTIME_DIR="${PROJECT_ROOT}/.local-runtime"
LOG_DIR="${RUNTIME_DIR}/logs"
PID_DIR="${RUNTIME_DIR}/pids"
APPS="${APPS:-organism cognitive coordinator ops mcp}"
START_DELAY_S="${START_DELAY_S:-2}"

mkdir -p "${LOG_DIR}" "${PID_DIR}"

route_prefix_for_app() {
  case "$1" in
    organism) echo "/organism" ;;
    cognitive) echo "/cognitive" ;;
    coordinator) echo "/pipeline" ;;
    ops) echo "/ops" ;;
    mcp) echo "/mcp" ;;
    ml) echo "/ml" ;;
    *) echo "" ;;
  esac
}

serve_route_present() {
  local route_prefix="$1"
  [[ -n "${route_prefix}" ]] || return 1
  curl -fsS "${SERVE_GATEWAY}/-/routes" 2>/dev/null | rg -q "\"${route_prefix}\""
}

start_app() {
  local app="$1"
  local pidfile="${PID_DIR}/${app}.pid"
  local logfile="${LOG_DIR}/${app}.log"

  if [[ -f "${pidfile}" ]] && kill -0 "$(cat "${pidfile}")" >/dev/null 2>&1; then
    echo "${app} already running (pid $(cat "${pidfile}"))"
    return 0
  fi

  (
    cd "${PROJECT_ROOT}"
    nohup "${PROJECT_ROOT}/.venv/bin/python" "${SCRIPT_DIR}/run-serve-app.py" "${app}" \
      >"${logfile}" 2>&1 &
    echo $! >"${pidfile}"
  )
  echo "Started ${app} (pid $(cat "${pidfile}"))"
}

stop_app() {
  local app="$1"
  local pidfile="${PID_DIR}/${app}.pid"
  if [[ -f "${pidfile}" ]]; then
    local pid
    pid="$(cat "${pidfile}")"
    kill "${pid}" >/dev/null 2>&1 || true
    rm -f "${pidfile}"
    echo "Stopped ${app}"
  fi
}

cmd="${1:-start}"

case "${cmd}" in
  start)
    bash "${SCRIPT_DIR}/run-ray-head.sh" start
    for app in ${APPS}; do
      start_app "${app}"
      sleep "${START_DELAY_S}"
    done
    ;;
  stop)
    for app in ${APPS}; do
      stop_app "${app}"
    done
    bash "${SCRIPT_DIR}/run-ray-head.sh" stop
    ;;
  status)
    bash "${SCRIPT_DIR}/run-ray-head.sh" status || true
    echo
    for app in ${APPS}; do
      local_pid_file="${PID_DIR}/${app}.pid"
      if [[ -f "${local_pid_file}" ]] && kill -0 "$(cat "${local_pid_file}")" >/dev/null 2>&1; then
        echo "${app}: running (pid $(cat "${local_pid_file}"))"
      elif serve_route_present "$(route_prefix_for_app "${app}")"; then
        echo "${app}: running (serve route present)"
      else
        echo "${app}: stopped"
      fi
    done
    echo
    curl -fsS "${SERVE_GATEWAY}/-/healthz" || true
    ;;
  logs)
    app="${2:-organism}"
    tail -n 200 -f "${LOG_DIR}/${app}.log"
    ;;
  *)
    echo "Usage: $(basename "$0") {start|stop|status|logs [app]}" >&2
    exit 1
    ;;
esac
