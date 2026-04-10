#!/usr/bin/env bash
# Optional Postgres-backed RESULT_VERIFIER queue integration lane.
#
# Enabled when:
#   SEEDCORE_ENABLE_RESULT_VERIFIER_PG_TESTS=1
# and requires:
#   SEEDCORE_RESULT_VERIFIER_TEST_DSN (SQLAlchemy async DSN)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

if [[ "${SEEDCORE_ENABLE_RESULT_VERIFIER_PG_TESTS:-0}" != "1" ]]; then
  echo "Skipping RESULT_VERIFIER Postgres integration lane (set SEEDCORE_ENABLE_RESULT_VERIFIER_PG_TESTS=1 to enable)."
  exit 0
fi

if [[ -z "${SEEDCORE_RESULT_VERIFIER_TEST_DSN:-}" ]]; then
  echo "SEEDCORE_ENABLE_RESULT_VERIFIER_PG_TESTS=1 requires SEEDCORE_RESULT_VERIFIER_TEST_DSN." >&2
  exit 1
fi

python -m pytest -q tests/test_result_verifier_postgres_integration.py

echo "RESULT_VERIFIER Postgres integration checks passed."
