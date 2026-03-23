#!/usr/bin/env bash
# Targeted host-local regression bundle for the active SeedCore governance/authz stack.

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
echo "==> Running host runtime verification"
python scripts/host/verify_host_runtime.py

echo
echo "==> Running governance/authz live verification"
bash scripts/host/verify_authz_governance_flow.sh
