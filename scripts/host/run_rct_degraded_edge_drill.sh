#!/usr/bin/env bash
# Q2 degraded-edge / adversarial drill slice (no live API; uses FastAPI TestClient).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"
export PYTHONWARNINGS="${PYTHONWARNINGS:-ignore::DeprecationWarning}"
python -m pytest -q tests/test_rct_degraded_edge_drill_matrix.py "$@"
echo "RCT degraded-edge drill matrix passed."
