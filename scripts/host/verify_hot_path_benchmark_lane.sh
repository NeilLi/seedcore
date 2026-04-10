#!/usr/bin/env bash
# Repeatable benchmark lane for host/CI:
# - validates benchmark artifact generation + baseline capture contracts
# - optionally runs a live benchmark and baseline capture when a runtime is available
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

python -m pytest -q \
  tests/test_benchmark_rct_hot_path.py \
  tests/test_capture_hot_path_deployment_baseline.py

if [[ "${SEEDCORE_RUN_LIVE_HOT_PATH_BENCHMARK:-0}" == "1" ]]; then
  python scripts/host/benchmark_rct_hot_path.py \
    --base-url "${SEEDCORE_RUNTIME_API_BASE:-http://127.0.0.1:8002/api/v1}" \
    --requests "${SEEDCORE_BENCH_REQUESTS:-40}" \
    --warmup "${SEEDCORE_BENCH_WARMUP:-4}" \
    --concurrency "${SEEDCORE_BENCH_CONCURRENCY:-4}"
  python scripts/host/capture_hot_path_deployment_baseline.py \
    --runtime-api-base "${SEEDCORE_RUNTIME_API_BASE:-http://127.0.0.1:8002/api/v1}"
fi

echo "Hot-path benchmark lane checks passed."
