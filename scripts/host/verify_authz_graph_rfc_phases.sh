#!/usr/bin/env bash
# Verify the staged authz-graph RFC implementation against code and local runtime.

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

cd "${PROJECT_ROOT}"
source .venv/bin/activate

PYTEST_TARGETS=(
  tests/test_pkg_authz_graph.py
  tests/test_pkg_authz_graph_service.py
  tests/test_pkg_authz_graph_manager.py
  tests/test_action_intent.py
  tests/test_pkg_router.py
)

echo "==> Running focused authz-graph RFC pytest suite"
PYTHONPATH=src pytest -q "${PYTEST_TARGETS[@]}"

echo
echo "==> Running live authz-graph RFC phase verification"
python scripts/host/verify_authz_graph_rfc_phases.py
