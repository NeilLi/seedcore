#!/usr/bin/env bash
# Start verification-api on a local port and run the Q2 HTTP fixture matrix.
# Intended for GitHub Actions after `cd ts && npm ci`. Hosts can run the same script.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PORT="${PORT:-17071}"
API_BASE="http://127.0.0.1:${PORT}"
TSX_BIN="${ROOT}/ts/node_modules/.bin/tsx"

cd "${ROOT}/ts/services/verification-api"
if [[ ! -x "${TSX_BIN}" ]]; then
  echo "missing tsx binary at ${TSX_BIN}; run cd ts && npm ci first" >&2
  exit 1
fi
"${TSX_BIN}" src/server.ts &
PID=$!

cleanup() {
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

for i in $(seq 1 60); do
  if curl -fsS "${API_BASE}/health" >/dev/null 2>&1; then
    break
  fi
  if [[ "$i" -eq 60 ]]; then
    echo "verification-api did not become ready on ${API_BASE}" >&2
    exit 1
  fi
  sleep 1
done

SEEDCORE_VERIFICATION_API_BASE="${API_BASE}" bash "${ROOT}/scripts/host/verify_q2_verification_api_fixtures.sh"
echo "Q2 verification API fixture gate passed."
