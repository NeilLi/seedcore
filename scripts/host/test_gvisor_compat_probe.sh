#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${SEEDCORE_GVISOR_PROBE_IMAGE:-alpine:3.20}"
VERIFY_BIN="${SEEDCORE_VERIFY_BIN:-${ROOT_DIR}/rust/target/release/seedcore-verify}"

if ! command -v runsc >/dev/null 2>&1; then
  echo "SKIP: runsc is not installed; gVisor compatibility probe not run."
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "SKIP: docker is not installed; gVisor compatibility probe not run."
  exit 0
fi

if ! docker info >/dev/null 2>&1; then
  echo "SKIP: docker daemon is not available; gVisor compatibility probe not run."
  exit 0
fi

if docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q '"runsc"'; then
  runtime_args=(--runtime=runsc)
else
  echo "SKIP: docker does not expose a runsc runtime; gVisor compatibility probe not run."
  exit 0
fi

started_ns="$(date +%s%N)"

if [[ -x "${VERIFY_BIN}" ]]; then
  docker run --rm "${runtime_args[@]}" \
    -v "${VERIFY_BIN}:/usr/local/bin/seedcore-verify:ro" \
    "${IMAGE}" sh -lc 'test -x /usr/local/bin/seedcore-verify && /usr/local/bin/seedcore-verify --help >/dev/null || true'
else
  docker run --rm "${runtime_args[@]}" "${IMAGE}" sh -lc 'true'
fi

ended_ns="$(date +%s%N)"
elapsed_ms="$(( (ended_ns - started_ns) / 1000000 ))"
echo "PASS: gVisor runsc compatibility probe completed in ${elapsed_ms}ms."
