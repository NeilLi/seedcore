#!/usr/bin/env bash
# Run the local authz engine parity matrix against fixture-backed governance payloads.

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

cd "${PROJECT_ROOT}"
source .venv/bin/activate
export PYTHONPATH="${PROJECT_ROOT}/src"

python scripts/host/verify_authz_engine_parity.py
