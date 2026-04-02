#!/usr/bin/env bash
# Local mirror of CI Q2 gates: Python hot-path slice + TypeScript verification contracts.
# CI also runs scripts/ci/q2_verification_api_fixture_gate.sh (starts verification-api + HTTP matrix).
# Optional: SEEDCORE_VERIFICATION_API_BASE=http://127.0.0.1:7071 to run live API fixture matrix locally.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"
python -m pytest -q \
  tests/test_pdp_hot_path_router.py \
  tests/test_edge_telemetry_envelope.py \
  tests/test_benchmark_rct_hot_path.py \
  tests/test_rct_degraded_edge_drill_matrix.py
cd "${ROOT}/ts"
npm run typecheck
npm test
if [[ -n "${SEEDCORE_VERIFICATION_API_BASE:-}" ]]; then
  bash "${ROOT}/scripts/host/verify_q2_verification_api_fixtures.sh"
fi
echo "Q2 verification contract checks passed."
