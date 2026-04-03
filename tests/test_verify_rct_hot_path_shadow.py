from __future__ import annotations

import importlib.util
from pathlib import Path

from seedcore.models.pdp_hot_path import HotPathEvaluateRequest


_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "host" / "verify_rct_hot_path_shadow.py"
_SPEC = importlib.util.spec_from_file_location("verify_rct_hot_path_shadow", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

CANONICAL_CASES = _MODULE.CANONICAL_CASES
FIXTURE_ROOT = _MODULE.FIXTURE_ROOT
_build_request = _MODULE._build_request
_read_json = _MODULE._read_json


def test_shadow_builder_produces_valid_hot_path_requests() -> None:
    for case_name in CANONICAL_CASES:
        case_dir = FIXTURE_ROOT / case_name
        approval_envelope = _read_json(case_dir / "input.approval_envelope.json")
        persisted_approval = {
            "approval_envelope_id": approval_envelope["approval_envelope_id"],
            "version": approval_envelope.get("version", 1),
            "approval_binding_hash": approval_envelope.get("approval_binding_hash"),
            "envelope": approval_envelope,
        }

        payload = _build_request(case_dir, persisted_approval=persisted_approval)
        request = HotPathEvaluateRequest.model_validate(payload)
        approval_context = request.action_intent.action.parameters["approval_context"]

        assert approval_context["approval_envelope_id"] == approval_envelope["approval_envelope_id"]
        assert request.policy_snapshot_ref == approval_envelope["policy_snapshot_ref"]
        assert "approval_envelope" not in approval_context
        assert "approval_transition" not in approval_context


def test_shadow_builder_can_attach_active_contract_bundles() -> None:
    case_dir = FIXTURE_ROOT / CANONICAL_CASES[0]
    approval_envelope = _read_json(case_dir / "input.approval_envelope.json")
    persisted_approval = {
        "approval_envelope_id": approval_envelope["approval_envelope_id"],
        "version": approval_envelope.get("version", 1),
        "approval_binding_hash": approval_envelope.get("approval_binding_hash"),
        "envelope": approval_envelope,
    }
    payload = _build_request(
        case_dir,
        persisted_approval=persisted_approval,
        active_contract_bundles={
            "request_schema_bundle": {"artifact_type": "request_schema_bundle"},
            "taxonomy_bundle": {"artifact_type": "taxonomy_bundle"},
        },
    )
    request = HotPathEvaluateRequest.model_validate(payload)

    assert request.request_schema_bundle["artifact_type"] == "request_schema_bundle"
    assert request.taxonomy_bundle["artifact_type"] == "taxonomy_bundle"
