#!/usr/bin/env bash
# Targeted verification bundle for the most recent SeedCore commit themes.

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

cd "${PROJECT_ROOT}"
source .venv/bin/activate

PYTEST_TARGETS=(
  tests/test_action_intent.py
  tests/test_api_router_registry.py
  tests/test_coordinator_dao.py
  tests/test_coordinator_persistence.py
  tests/test_custody_graph_service.py
  tests/test_external_authority.py
  tests/test_governed_closure.py
  tests/test_pkg_authz_graph.py
  tests/test_pkg_authz_graph_manager.py
  tests/test_pkg_authz_graph_service.py
  tests/test_pkg_dao.py
  tests/test_pkg_manager.py
  tests/test_pkg_router.py
  tests/test_replay_router.py
  tests/test_replay_service.py
)

echo "==> Running targeted pytest bundle"
pytest "${PYTEST_TARGETS[@]}"

echo
echo "==> Running live runtime verification"
python scripts/host/verify_recent_runtime.py
