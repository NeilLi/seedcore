"""Unit tests for Phase-3 RCT publish-time validation helpers."""

from unittest.mock import AsyncMock

import pytest

from seedcore.ops.pkg.authz_graph.compiler import TRANSFER_TRUST_GAP_TAXONOMY
from seedcore.ops.pkg.rct_publish_validation import (
    gather_rct_publish_validation_errors,
    validate_decision_graph_snapshot_for_publish,
    validate_transition_requirement_entry,
)


def _minimal_transition_row() -> dict:
    return {
        "subject_ref": "principal:alice",
        "resource_ref": "asset:box-1",
        "operation": "TRANSFER_CUSTODY",
        "effect": "allow",
        "zone_refs": [],
        "network_refs": [],
        "custody_point_refs": ["cp-warehouse"],
        "workflow_stage_refs": [],
        "resource_state_hash": None,
        "requires_break_glass": False,
        "bypass_deny": False,
        "required_current_custodian": "cust-a",
        "required_transferable_state": "sealed",
        "max_telemetry_age_seconds": 120,
        "max_inspection_age_seconds": None,
        "require_attestation": False,
        "require_seal": False,
        "require_approved_source_registration": True,
        "allow_quarantine": True,
        "valid_from": None,
        "valid_to": None,
        "provenance_source": "pkg_rule:test",
    }


def test_validate_transition_requirement_entry_ok():
    errs = validate_transition_requirement_entry(
        _minimal_transition_row(), subject_key="s", index=0
    )
    assert errs == []


def test_validate_transition_requirement_entry_bad_effect():
    row = dict(_minimal_transition_row())
    row["effect"] = "nope"
    errs = validate_transition_requirement_entry(row, subject_key="s", index=0)
    assert any("invalid_effect" in e for e in errs)


def test_validate_decision_graph_ok():
    dgs = {
        "hot_path_workflow": "restricted_custody_transfer",
        "trust_gap_taxonomy": [TRANSFER_TRUST_GAP_TAXONOMY[0]],
        "transition_requirements": {"principal:alice": [_minimal_transition_row()]},
    }
    errs = validate_decision_graph_snapshot_for_publish(dgs)
    assert errs == []


def test_validate_decision_graph_rejects_unknown_trust_gap():
    dgs = {
        "hot_path_workflow": "restricted_custody_transfer",
        "trust_gap_taxonomy": ["not_a_canonical_code"],
        "transition_requirements": {"s": [_minimal_transition_row()]},
    }
    errs = validate_decision_graph_snapshot_for_publish(dgs)
    assert any("unknown_trust_gap_code" in e for e in errs)


@pytest.mark.asyncio
async def test_gather_publish_errors_requires_manifest_taxonomy_and_ready():
    class _Dgs:
        def to_dict(self):
            return {
                "hot_path_workflow": "restricted_custody_transfer",
                "trust_gap_taxonomy": [TRANSFER_TRUST_GAP_TAXONOMY[0]],
                "transition_requirements": {"s": [_minimal_transition_row()]},
            }

    class _Compiled:
        restricted_transfer_ready = True
        decision_graph_snapshot = _Dgs()

    client = AsyncMock()
    client.get_snapshot_manifest = AsyncMock(return_value=None)
    client.get_taxonomy_bundle = AsyncMock(
        return_value={"reason_codes": [], "trust_gap_codes": [], "obligation_codes": []}
    )
    errs = await gather_rct_publish_validation_errors(
        client, snapshot_id=1, compiled=_Compiled()
    )
    assert "pkg_snapshot_manifest_row_missing" in errs
    assert "taxonomy_reason_codes_empty" in errs


@pytest.mark.asyncio
async def test_gather_publish_errors_passes_when_complete():
    class _Dgs:
        def to_dict(self):
            return {
                "hot_path_workflow": "restricted_custody_transfer",
                "trust_gap_taxonomy": [TRANSFER_TRUST_GAP_TAXONOMY[0]],
                "transition_requirements": {"s": [_minimal_transition_row()]},
            }

    class _Compiled:
        restricted_transfer_ready = True
        decision_graph_snapshot = _Dgs()

    client = AsyncMock()
    client.get_snapshot_manifest = AsyncMock(return_value={"snapshot_id": 1})
    client.get_taxonomy_bundle = AsyncMock(
        return_value={
            "reason_codes": [{"code": "r1"}],
            "trust_gap_codes": [{"code": "t1"}],
            "obligation_codes": [{"code": "o1"}],
        }
    )
    errs = await gather_rct_publish_validation_errors(
        client, snapshot_id=1, compiled=_Compiled()
    )
    assert errs == []
