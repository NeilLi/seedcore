#!/usr/bin/env bash
# CI enforcement: Q2 degraded-edge / adversarial drills acceptance matrix.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
bash "${ROOT}/scripts/host/verify_q2_degraded_edge_drill_matrix.sh"

echo "CI Q2 degraded-edge drill matrix passed."
