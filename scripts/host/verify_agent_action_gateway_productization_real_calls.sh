#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"
source .venv/bin/activate
python scripts/host/verify_agent_action_gateway_productization_real_calls.py "$@"

