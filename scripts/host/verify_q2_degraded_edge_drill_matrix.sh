#!/usr/bin/env bash
# Q2 degraded-edge / adversarial acceptance drills (no live runtime required).
# Includes:
# - stale telemetry / stale graph (RCT hot-path drill matrix)
# - intermittent connectivity (synthetic flaky transport benchmark)
# - coordinate tamper (agent action gateway coordinate mismatch)
# - replay injection / authority mismatch (replay router tamper surfaces)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

echo "== Q2 degraded-edge drill matrix =="

python -m pytest -q tests/test_rct_degraded_edge_drill_matrix.py
python -m pytest -q tests/test_agent_actions_router.py::test_agent_actions_evaluate_denies_when_scope_coordinate_mismatch
python -m pytest -q tests/test_replay_router.py::test_verify_by_audit_id_surfaces_owner_identity_mismatch
python -m pytest -q tests/test_replay_router.py::test_verify_token_surfaces_reference_subject_mismatch
python -m pytest -q tests/test_benchmark_rct_hot_path.py

echo "Q2 degraded-edge drill matrix passed."

