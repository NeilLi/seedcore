#!/usr/bin/env bash
# Experimental single-node local Ray head for SeedCore host-mode Serve apps.

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

source "${SCRIPT_DIR}/host-env.sh"

RUNTIME_DIR="${PROJECT_ROOT}/.local-runtime"
LOG_DIR="${RUNTIME_DIR}/logs"
PID_DIR="${RUNTIME_DIR}/pids"
PID_FILE="${PID_DIR}/ray-head.pid"
LOG_FILE="${LOG_DIR}/ray-head.log"
RAY_TEMP_DIR="${RAY_TEMP_DIR:-/tmp/seedcore-ray}"
RAY_NUM_CPUS="${RAY_NUM_CPUS:-2}"
RAY_OBJECT_STORE_MEMORY="${RAY_OBJECT_STORE_MEMORY:-268435456}"

mkdir -p "${RAY_TEMP_DIR}" "${LOG_DIR}" "${PID_DIR}"

is_running() {
  [[ -f "${PID_FILE}" ]] && kill -0 "$(cat "${PID_FILE}")" >/dev/null 2>&1
}

port_open() {
  python3 - "$1" "$2" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
s = socket.socket()
s.settimeout(1)
try:
    s.connect((host, port))
except OSError:
    raise SystemExit(1)
else:
    raise SystemExit(0)
finally:
    s.close()
PY
}

cmd="${1:-start}"

case "${cmd}" in
  start)
    if is_running; then
      echo "Ray head already running (pid $(cat "${PID_FILE}"))"
      exit 0
    fi
    if port_open "${RAY_HOST}" "${RAY_GCS_PORT}" && port_open "${RAY_HOST}" "${RAY_CLIENT_PORT}"; then
      echo "Ray head already running at ${RAY_STATUS_ADDRESS}"
      exit 0
    fi
    nohup script -q /dev/null bash -lc "
      cd '${PROJECT_ROOT}'
      source '${SCRIPT_DIR}/host-env.sh'
      exec ray start \
        --head \
        --port='${RAY_GCS_PORT}' \
        --ray-client-server-port='${RAY_CLIENT_PORT}' \
        --dashboard-host='127.0.0.1' \
        --dashboard-port='${RAY_DASHBOARD_PORT}' \
        --num-cpus='${RAY_NUM_CPUS}' \
        --object-store-memory='${RAY_OBJECT_STORE_MEMORY}' \
        --temp-dir='${RAY_TEMP_DIR}' \
        --disable-usage-stats \
        --block
    " >"${LOG_FILE}" 2>&1 &
    echo $! >"${PID_FILE}"
    sleep 8
    if is_running && port_open "${RAY_HOST}" "${RAY_GCS_PORT}"; then
      echo "Ray head started (pid $(cat "${PID_FILE}"))"
    else
      echo "Ray head failed to stay up; see ${LOG_FILE}" >&2
      exit 1
    fi
    ;;
  foreground)
    exec ray start \
      --head \
      --port="${RAY_GCS_PORT}" \
      --ray-client-server-port="${RAY_CLIENT_PORT}" \
      --dashboard-host="127.0.0.1" \
      --dashboard-port="${RAY_DASHBOARD_PORT}" \
      --num-cpus="${RAY_NUM_CPUS}" \
      --object-store-memory="${RAY_OBJECT_STORE_MEMORY}" \
      --temp-dir="${RAY_TEMP_DIR}" \
      --disable-usage-stats \
      --block
    ;;
  stop)
    if is_running; then
      kill "$(cat "${PID_FILE}")" >/dev/null 2>&1 || true
      sleep 2
      if is_running; then
        kill -9 "$(cat "${PID_FILE}")" >/dev/null 2>&1 || true
      fi
      rm -f "${PID_FILE}"
    fi
    ray stop --force >/dev/null 2>&1 || true
    ;;
  status)
    if is_running; then
      echo "pid: $(cat "${PID_FILE}")"
    else
      echo "pid: stopped"
    fi
    echo "gcs: ${RAY_STATUS_ADDRESS}"
    echo "client: ${RAY_CLIENT_ADDRESS}"
    if port_open "${RAY_HOST}" "${RAY_GCS_PORT}"; then
      echo "gcs_port: open"
    else
      echo "gcs_port: closed"
    fi
    if port_open "${RAY_HOST}" "${RAY_CLIENT_PORT}"; then
      echo "client_port: open"
    else
      echo "client_port: closed"
    fi
    ;;
  *)
    echo "Usage: $(basename "$0") {start|foreground|stop|status}" >&2
    exit 1
    ;;
esac
