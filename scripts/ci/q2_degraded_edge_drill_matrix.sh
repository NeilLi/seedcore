#!/usr/bin/env bash
# CI enforcement: Q2 degraded-edge / adversarial drills acceptance matrix.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

python -m pytest -q tests/test_rct_degraded_edge_drill_matrix.py
python -m pytest -q tests/test_agent_actions_router.py::test_agent_actions_evaluate_denies_when_scope_coordinate_mismatch
python -m pytest -q tests/test_replay_router.py::test_verify_by_audit_id_surfaces_owner_identity_mismatch
python -m pytest -q tests/test_replay_router.py::test_verify_token_surfaces_reference_subject_mismatch
python -m pytest -q tests/test_benchmark_rct_hot_path.py

echo "CI Q2 degraded-edge drill matrix passed."

