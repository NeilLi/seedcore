#!/usr/bin/env bash
# Bring up the local host-mode task execution stack:
# Ray head + coordinator/organism Serve apps + organism/bootstrap dispatchers.

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

source "${SCRIPT_DIR}/host-env.sh"

RUNTIME_DIR="${PROJECT_ROOT}/.local-runtime"
LOG_DIR="${RUNTIME_DIR}/logs"
mkdir -p "${LOG_DIR}"

wait_for_url() {
  local url="$1"
  local label="$2"
  local attempts="${3:-30}"
  local delay_s="${4:-1}"

  for ((i=1; i<=attempts; i++)); do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      echo "${label}: ready"
      return 0
    fi
    sleep "${delay_s}"
  done

  echo "${label}: not ready after ${attempts}s (${url})" >&2
  return 1
}

show_routes() {
  curl -fsS "${SERVE_GATEWAY}/-/routes" || true
  echo
}

show_actor_status() {
  (
    cd "${PROJECT_ROOT}"
    source .venv/bin/activate
    python - <<'PY'
import ray

ray.init(address="127.0.0.1:26079", namespace="seedcore-local", ignore_reinit_error=True)
for name in ("seedcore_reaper", "queue_dispatcher_0"):
    try:
        actor = ray.get_actor(name, namespace="seedcore-local")
        print(f"{name}: present")
    except Exception as exc:
        print(f"{name}: missing ({type(exc).__name__})")
PY
  ) || true
}

cmd="${1:-start}"

case "${cmd}" in
  start)
    (
      cd "${PROJECT_ROOT}"
      APPS="organism coordinator" bash "${SCRIPT_DIR}/run-ray-stack.sh" start
    )

    wait_for_url "${SERVE_GATEWAY}/organism/health" "organism health"
    wait_for_url "${SERVE_GATEWAY}/-/routes" "serve routes"

    (
      cd "${PROJECT_ROOT}"
      BOOTSTRAP_MODE=organism bash "${SCRIPT_DIR}/run-bootstrap.sh"
      BOOTSTRAP_MODE=dispatchers DISPATCHER_COUNT=1 ENABLE_GRAPH_DISPATCHERS=false SEEDCORE_GRAPH_DISPATCHERS=0 bash "${SCRIPT_DIR}/run-bootstrap.sh"
    ) | tee "${LOG_DIR}/task-stack-bootstrap.log"

    echo
    echo "Routes:"
    show_routes
    echo "Actors:"
    show_actor_status
    ;;
  stop)
    (
      cd "${PROJECT_ROOT}"
      APPS="organism coordinator" bash "${SCRIPT_DIR}/run-ray-stack.sh" stop
    )
    ;;
  status)
    (
      cd "${PROJECT_ROOT}"
      APPS="organism coordinator" bash "${SCRIPT_DIR}/run-ray-stack.sh" status
    )
    echo
    echo "Routes:"
    show_routes
    echo "Actors:"
    show_actor_status
    ;;
  *)
    echo "Usage: $(basename "$0") {start|stop|status}" >&2
    exit 1
    ;;
esac
