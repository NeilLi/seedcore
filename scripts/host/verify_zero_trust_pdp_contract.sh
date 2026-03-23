#!/usr/bin/env bash
# Verify the zero-trust PDP contract against the local SeedCore host runtime.

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

cd "${PROJECT_ROOT}"
source deploy/local/host-env.sh

python scripts/host/verify_zero_trust_pdp_contract.py
