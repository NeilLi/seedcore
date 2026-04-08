#!/usr/bin/env bash
# Spec-aligned integration bundle for the memory refactor work.

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

RUN_RUNTIME=0
RUN_LIVE_BACKEND=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime)
      RUN_RUNTIME=1
      shift
      ;;
    --live-backend)
      RUN_LIVE_BACKEND=1
      shift
      ;;
    --all)
      RUN_RUNTIME=1
      RUN_LIVE_BACKEND=1
      shift
      ;;
    *)
      echo "Usage: $(basename "$0") [--runtime] [--live-backend] [--all]" >&2
      exit 1
      ;;
  esac
done

cd "${PROJECT_ROOT}"

if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

if [[ -f "deploy/local/host-env.sh" ]]; then
  # shellcheck disable=SC1091
  source "deploy/local/host-env.sh"
fi

export PYTHONPATH="${PROJECT_ROOT}/src:${PROJECT_ROOT}:${PYTHONPATH:-}"

PYTEST_TARGETS=(
  tests/test_memory_tool_integration.py
  tests/test_memory_contracts.py
  tests/test_memory_aggregator.py
  tests/test_memory_runtime_lifecycle.py
  tests/test_cognitive_memory_bridge.py
  tests/test_cognitive_memory_wiring.py
  tests/test_memory_telemetry.py
  tests/test_semantic_memory_service.py
  tests/test_neo4j_graph_backend.py
  tests/test_mw_manager.py
  tests/test_host_local_runtime_defaults.py
  tests/test_cognitive_package_imports.py
)

echo "==> Running memory refactor pytest bundle"
python -m pytest -q "${PYTEST_TARGETS[@]}"

if [[ "${RUN_LIVE_BACKEND}" == "1" ]]; then
  echo
  echo "==> Running live semantic-memory backend integration"
  SEEDCORE_LIVE_MEMORY_BACKENDS=1 python -m pytest -q \
    tests/test_semantic_memory_live_integration.py
fi

if [[ "${RUN_RUNTIME}" == "1" ]]; then
  echo
  echo "==> Running live memory runtime verification"
  python scripts/host/verify_memory_runtime.py
fi

echo
echo "Memory refactor integration checks passed."
