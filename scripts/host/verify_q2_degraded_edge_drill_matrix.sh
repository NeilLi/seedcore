#!/usr/bin/env bash
# Q2 degraded-edge / adversarial acceptance drills (no live runtime required).
# Includes:
# - stale telemetry / stale graph (RCT hot-path drill matrix)
# - intermittent connectivity (synthetic flaky transport benchmark)
# - coordinate tamper (agent action gateway coordinate mismatch)
# - replay injection / authority mismatch (replay router tamper surfaces)
# - repeatable forensic/evidence export checks for quarantine / rollback investigations
# - commerce-slice drill matrix: stale-graph / dependency outage / coordinate
#   tamper / cross-product replay injection, with drill evidence tied to
#   product_ref / order_ref / quote_ref / workflow_join_key
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

echo "== Q2 degraded-edge drill matrix =="

python -m pytest -q tests/test_rct_degraded_edge_drill_matrix.py
python -m pytest -q tests/test_agent_actions_router.py::test_agent_actions_evaluate_denies_when_scope_coordinate_mismatch
python -m pytest -q tests/test_replay_router.py::test_verify_by_audit_id_surfaces_owner_identity_mismatch
python -m pytest -q tests/test_replay_router.py::test_verify_token_surfaces_reference_subject_mismatch
python -m pytest -q tests/test_benchmark_rct_hot_path.py
python -m pytest -q tests/test_coordinator_dao.py::TestTransferApprovalEnvelopeDAO
python -m pytest -q tests/test_replay_router.py::test_materialized_custody_event_includes_forensic_block_when_present
python -m pytest -q tests/test_replay_router.py::test_governance_search_filters_quarantine_and_trust_gap_records
python -m pytest -q tests/test_forensic_block_contract.py
python -m pytest -q tests/test_end_to_end_product_verification.py

echo "== Q2 commerce-slice drill matrix =="
# Commerce-shaped drills that bind drill evidence to product_ref / workflow
# join keys via the agent-action-gateway contract. This closes the gap
# called out in docs/development/README.md section 6 item 2.
python -m pytest -q tests/test_rct_commerce_drill_matrix.py

echo "Q2 degraded-edge drill matrix passed."
