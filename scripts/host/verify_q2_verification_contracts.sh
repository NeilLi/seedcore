#!/usr/bin/env bash
# Local mirror of CI Q2 gates.
# Host flow intentionally runs the same core acceptance slices as CI:
# - Python hot-path and envelope tests
# - TypeScript typecheck and contract tests
# - fixture-backed verification API HTTP matrix (via CI launcher script)
# - degraded-edge drill matrix
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

python -m pytest -q \
  tests/test_pdp_hot_path_router.py \
  tests/test_edge_telemetry_envelope.py

cd "${ROOT}/ts"
npm run typecheck
npm test
cd "${ROOT}"

bash "${ROOT}/scripts/ci/q2_verification_api_fixture_gate.sh"
bash "${ROOT}/scripts/host/verify_q2_degraded_edge_drill_matrix.sh"

echo "Q2 verification contract checks passed."
