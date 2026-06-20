#!/usr/bin/env bash
# Run the TypeScript verification API against the host-mode SeedCore runtime.

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

cd "${PROJECT_ROOT}"

source "${SCRIPT_DIR}/host-env.sh"

export PORT="${PORT:-7071}"
export SEEDCORE_RUNTIME_API_BASE="${SEEDCORE_RUNTIME_API_BASE:-${SEEDCORE_API_URL}/api/v1}"

exec npm --prefix "${PROJECT_ROOT}/ts" run serve:verification-api
