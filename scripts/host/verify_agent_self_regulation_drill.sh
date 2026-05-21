#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

echo "== Agent Self-Regulation drill tests =="
python -m pytest -q tests/test_agent_self_regulation_drill.py

echo "== Agent Self-Regulation drill evidence =="
python scripts/host/run_agent_self_regulation_drill.py \
  --manifest-output artifacts/agent_self_regulation/gated_actions_manifest.json \
  --output artifacts/agent_self_regulation/drill_evidence.json

echo "Agent Self-Regulation drill passed."
