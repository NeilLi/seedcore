#!/usr/bin/env bash
# Two-phase local drill: fill promotion window with clean parity, then restart with
# SEEDCORE_HOT_PATH_PARITY_DRILL_STABLE_DENY=1 and send one allow-case to force a
# recorded mismatch (JSONL + promotion gate + enforce_ready on /api/v1/pdp/hot-path/status).
#
# Requires: API on PORT (default 8002), same repo as deploy/local/run-api.sh, .venv, DB/Redis up.
# Usage:
#   bash scripts/host/drill_hot_path_parity_mismatch.sh
# Optional:
#   PORT=8002 BASE_URL=http://127.0.0.1:8002/api/v1 bash scripts/host/drill_hot_path_parity_mismatch.sh

set -euo pipefail
# Avoid "Killed: 9" job-status lines when we SIGKILL the drill uvicorn we backgrounded.
set +m

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"
cd "${REPO_ROOT}"

PORT="${PORT:-8002}"
BASE_URL="${BASE_URL:-http://127.0.0.1:${PORT}/api/v1}"
HOT_PATH_LOG="${SEEDCORE_HOT_PATH_PARITY_LOG:-${REPO_ROOT}/.local-runtime/hot_path_parity/events.jsonl}"
WINDOW_N="${SEEDCORE_HOT_PATH_PROMOTION_WINDOW_N:-10}"

export PATH="${REPO_ROOT}/.venv/bin:/opt/homebrew/opt/postgresql@17/bin:${PATH}"
export PYTHONPATH="${REPO_ROOT}/src"

# `lsof -ti :PORT` is unreliable on some hosts; target TCP listeners explicitly.
free_tcp_port() {
  local p="${1:?port}"
  local attempt
  for attempt in $(seq 1 80); do
    local pids
    pids="$(lsof -nP -iTCP:"${p}" -sTCP:LISTEN -t 2>/dev/null || true)"
    if [[ -z "${pids}" ]]; then
      return 0
    fi
    # shellcheck disable=SC2086
    kill -9 ${pids} 2>/dev/null || true
    sleep 0.25
  done
  echo "ERROR: could not free TCP port ${p} (still listening)." >&2
  lsof -nP -iTCP:"${p}" -sTCP:LISTEN || true
  return 1
}

assert_drill_uvicorn_listening() {
  local phase="$1" logf="$2" expected_pid="$3"
  sleep 0.75
  if grep -q "address already in use" "${logf}" 2>/dev/null; then
    echo "ERROR: ${phase} uvicorn did not bind (port busy). See ${logf}" >&2
    tail -25 "${logf}" >&2
    exit 1
  fi
  local lp
  lp="$(lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN -t 2>/dev/null | head -n1 || true)"
  if [[ -z "${lp}" ]]; then
    echo "ERROR: no TCP listener on port ${PORT} after ${phase} start." >&2
    tail -25 "${logf}" >&2
    exit 1
  fi
  if [[ "${lp}" != "${expected_pid}" ]]; then
    echo "ERROR: port ${PORT} is held by PID ${lp}, expected drill uvicorn ${expected_pid}." >&2
    echo "Stop the other process or run with PORT=<free-port>." >&2
    exit 1
  fi
}

status_json() {
  curl -sS "${BASE_URL}/pdp/hot-path/status"
}

echo "==> Using BASE_URL=${BASE_URL}"
echo "==> Parity JSONL: ${HOT_PATH_LOG} (window N=${WINDOW_N})"

mkdir -p "$(dirname "${HOT_PATH_LOG}")"
: > "${HOT_PATH_LOG}"

echo "==> Phase A: restart API without parity drill (fill window with real matching parity)"
free_tcp_port "${PORT}"

export SEEDCORE_HOT_PATH_PARITY_LOG="${HOT_PATH_LOG}"
export SEEDCORE_HOT_PATH_PROMOTION_WINDOW_N="${WINDOW_N}"
unset SEEDCORE_HOT_PATH_PARITY_DRILL_STABLE_DENY || true
unset SEEDCORE_HOT_PATH_PROMOTION_GATE_DISABLED || true

nohup env \
  SEEDCORE_RCT_HOT_PATH_MODE=shadow \
  SEEDCORE_HOT_PATH_PARITY_LOG="${HOT_PATH_LOG}" \
  SEEDCORE_HOT_PATH_PROMOTION_WINDOW_N="${WINDOW_N}" \
  PYTHONPATH="${PYTHONPATH}" \
  PG_DSN="${PG_DSN:-postgresql://ningli@127.0.0.1:5432/seedcore}" \
  PG_DSN_ASYNC="${PG_DSN_ASYNC:-postgresql+asyncpg://ningli@127.0.0.1:5432/seedcore}" \
  REDIS_HOST="${REDIS_HOST:-127.0.0.1}" \
  REDIS_PORT="${REDIS_PORT:-6379}" \
  "${REPO_ROOT}/.venv/bin/uvicorn" seedcore.main:app --host 127.0.0.1 --port "${PORT}" \
  > "${REPO_ROOT}/.local-runtime/api-parity-drill-a.log" 2>&1 &
echo $! > "${REPO_ROOT}/.local-runtime/api-parity-drill-a.pid"

for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
    break
  fi
  sleep 1
done
curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null || {
  echo "API failed to start (phase A); tail log:"
  tail -50 "${REPO_ROOT}/.local-runtime/api-parity-drill-a.log" || true
  exit 1
}

assert_drill_uvicorn_listening "phase A" "${REPO_ROOT}/.local-runtime/api-parity-drill-a.log" "$(cat "${REPO_ROOT}/.local-runtime/api-parity-drill-a.pid")"

ACTIVE_SNAPSHOT="$(curl -sS "${BASE_URL}/pkg/status" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('active_version') or d.get('version') or '')" 2>/dev/null || true)"
if [[ -z "${ACTIVE_SNAPSHOT}" ]]; then
  echo "WARN: could not read active PKG snapshot from ${BASE_URL}/pkg/status; verify_rct may fail"
fi

echo "==> Posting ${WINDOW_N} allow-case evaluations (no drill)..."
for i in $(seq 1 "${WINDOW_N}"); do
  python3 "${REPO_ROOT}/scripts/host/verify_rct_hot_path_shadow.py" \
    --base-url "${BASE_URL}" \
    --only allow_case \
    --request-id-suffix "drill-fill-${i}" \
    >/dev/null
done

echo "==> Status after clean window (expect promotion_eligible true if runtime_ready):"
status_json | python3 -m json.tool | head -40

echo "==> Phase B: restart API WITH SEEDCORE_HOT_PATH_PARITY_DRILL_STABLE_DENY=1"
kill "$(cat "${REPO_ROOT}/.local-runtime/api-parity-drill-a.pid" 2>/dev/null || true)" 2>/dev/null || true
free_tcp_port "${PORT}"

nohup env \
  SEEDCORE_RCT_HOT_PATH_MODE=shadow \
  SEEDCORE_HOT_PATH_PARITY_LOG="${HOT_PATH_LOG}" \
  SEEDCORE_HOT_PATH_PROMOTION_WINDOW_N="${WINDOW_N}" \
  SEEDCORE_HOT_PATH_PARITY_DRILL_STABLE_DENY=1 \
  PYTHONPATH="${PYTHONPATH}" \
  PG_DSN="${PG_DSN:-postgresql://ningli@127.0.0.1:5432/seedcore}" \
  PG_DSN_ASYNC="${PG_DSN_ASYNC:-postgresql+asyncpg://ningli@127.0.0.1:5432/seedcore}" \
  REDIS_HOST="${REDIS_HOST:-127.0.0.1}" \
  REDIS_PORT="${REDIS_PORT:-6379}" \
  "${REPO_ROOT}/.venv/bin/uvicorn" seedcore.main:app --host 127.0.0.1 --port "${PORT}" \
  > "${REPO_ROOT}/.local-runtime/api-parity-drill-b.log" 2>&1 &
echo $! > "${REPO_ROOT}/.local-runtime/api-parity-drill-b.pid"

for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
    break
  fi
  sleep 1
done
curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null || {
  echo "API failed to start (phase B); tail log:"
  tail -50 "${REPO_ROOT}/.local-runtime/api-parity-drill-b.log" || true
  exit 1
}

assert_drill_uvicorn_listening "phase B" "${REPO_ROOT}/.local-runtime/api-parity-drill-b.log" "$(cat "${REPO_ROOT}/.local-runtime/api-parity-drill-b.pid")"

echo "==> One allow-case with drill (expect parity_ok false in JSONL)..."
# verify exits 1 when parity mismatches; that is expected here.
( python3 "${REPO_ROOT}/scripts/host/verify_rct_hot_path_shadow.py" \
  --base-url "${BASE_URL}" \
  --only allow_case \
  --request-id-suffix "drill-mismatch-1" \
  2>&1 || true ) | tail -15

echo "==> Status after mismatch (expect promotion_eligible false, enforce_ready false):"
status_json | python3 -m json.tool | head -45

echo "==> Last JSONL event (pretty):"
if [[ -s "${HOT_PATH_LOG}" ]]; then
  tail -n 1 "${HOT_PATH_LOG}" | python3 -m json.tool
else
  echo "WARN: ${HOT_PATH_LOG} is empty — requests may have hit a different API process or parity persistence failed." >&2
  exit 1
fi

echo ""
echo "Done. To restore a normal API: kill PID $(cat "${REPO_ROOT}/.local-runtime/api-parity-drill-b.pid") and run: bash deploy/local/run-api.sh"
echo "Unset SEEDCORE_HOT_PATH_PARITY_DRILL_STABLE_DENY in production."
