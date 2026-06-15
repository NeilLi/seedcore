#!/usr/bin/env bash
# Local mirror of CI Q2 gates.
# Host flow intentionally runs the same core acceptance slices as CI:
# - Python parity / replay / hot-path contract tests
# - TypeScript typecheck and contract tests
# - fixture-backed verification API HTTP matrix (via CI launcher script)
# - hot-path observability alert checks and benchmark lane checks
# - degraded-edge drill matrix
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

python -m pytest -q \
  tests/test_authz_parity_service.py \
  tests/test_replay_service.py \
  tests/test_rct_replay_verification_phase4.py \
  tests/test_pdp_hot_path_router.py \
  tests/test_edge_telemetry_envelope.py

cd "${ROOT}/ts"
npm run typecheck
npm test
cd "${ROOT}"

bash "${ROOT}/scripts/ci/q2_verification_api_fixture_gate.sh"
bash "${ROOT}/scripts/host/verify_hot_path_alert_rules.sh"
bash "${ROOT}/scripts/host/verify_hot_path_benchmark_lane.sh"
bash "${ROOT}/scripts/host/verify_q2_degraded_edge_drill_matrix.sh"
bash "${ROOT}/scripts/host/verify_result_verifier_telemetry_contract.sh"
bash "${ROOT}/scripts/host/verify_result_verifier_postgres_integration.sh"

echo "Q2 verification contract checks passed."
