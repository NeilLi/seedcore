#!/usr/bin/env bash
# Seed governed audit cases and verify governance/replay endpoints against the local host stack.

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

cd "${PROJECT_ROOT}"
source deploy/local/host-env.sh

python scripts/host/verify_authz_governance_flow.py
