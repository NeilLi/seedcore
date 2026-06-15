#!/usr/bin/env bash
# Always-on RESULT_VERIFIER telemetry contract gate.
#
# This intentionally avoids live Postgres or a running coordinator. It verifies
# that the embedded verifier exposes the ADR-trigger metrics needed as June
# gate evidence, while the separate Postgres integration lane remains opt-in.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

python -m pytest -q tests/test_result_verifier_telemetry_contract.py

echo "RESULT_VERIFIER telemetry contract checks passed."
