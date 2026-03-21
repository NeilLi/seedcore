#!/usr/bin/env bash
# Experimental localhost-friendly SeedCore bootstrap runner for host-mode Ray.

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

source "${SCRIPT_DIR}/host-env.sh"

cd "${PROJECT_ROOT}"
source .venv/bin/activate

export BOOTSTRAP_MODE="${BOOTSTRAP_MODE:-all}"
export EXIT_AFTER_BOOTSTRAP="${EXIT_AFTER_BOOTSTRAP:-true}"
export FORCE_REPLACE_DISPATCHERS="${FORCE_REPLACE_DISPATCHERS:-true}"
export DISPATCHER_COUNT="${DISPATCHER_COUNT:-1}"
export SEEDCORE_GRAPH_DISPATCHERS="${SEEDCORE_GRAPH_DISPATCHERS:-0}"
export ENABLE_GRAPH_DISPATCHERS="${ENABLE_GRAPH_DISPATCHERS:-false}"
export STRICT_GRAPH_DISPATCHERS="${STRICT_GRAPH_DISPATCHERS:-false}"
export RUNNING_IN_CLUSTER="${RUNNING_IN_CLUSTER:-0}"
export PIN_TO_HEAD_NODE="${PIN_TO_HEAD_NODE:-false}"
export SERVE_BASE_URL="${SERVE_BASE_URL:-${SERVE_GATEWAY}}"
export ORGANISM_URL="${ORGANISM_URL:-${SERVE_GATEWAY}/organism}"

exec python "${PROJECT_ROOT}/bootstraps/bootstrap_entry.py"
