#!/usr/bin/env bash
# Run the SeedCore HAL bridge directly on macOS in simulation mode.

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

cd "${PROJECT_ROOT}"

source .venv/bin/activate

export PYTHONPATH="${PROJECT_ROOT}/src"

export HAL_DRIVER_MODE="${HAL_DRIVER_MODE:-simulation}"
export HAL_SIM_BACKEND="${HAL_SIM_BACKEND:-robot_sim}"
export HAL_REQUIRE_EXECUTION_TOKEN="${HAL_REQUIRE_EXECUTION_TOKEN:-false}"
export HOST="${HOST:-127.0.0.1}"
export PORT="${PORT:-8003}"

exec python -m seedcore.hal.service.main
