from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

from seedcore.models.edge_trust import (
    EDGE_TRUST_ENROLLMENT_VERSION,
    EdgeTrustEnrollmentBundle,
)
from seedcore.ops.evidence.edge_trust_adapter import (
    FixtureEdgeTrustAdapter,
    validate_edge_trust_telemetry_refs,
)
from seedcore.ops.evidence.verification import (
    build_signed_artifact,
    verify_evidence_bundle_result,
)

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "edge_trust" / "enrolled_devices.json"


def _fixture() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _telemetry_ref(**overrides: str) -> dict:
    ref = {
        "contract_version": "seedcore.edge_telemetry_envelope.v0",
        "telemetry_id": "tel-demo-001",
        "asset_ref": "asset:lot-8841",
        "edge_node_ref": "edge:handoff-bay-3",
        "observed_at": "2026-04-02T12:00:00Z",
        "sensor_kind": "motor_torque",
        "payload_sha256": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        "signer_key_ref": "software_dev_key:edge-signing-demo",
    }
    ref.update(overrides)
    return ref


def _signed_evidence_bundle(
    *,
    enrollment: dict | None = None,
    edge_policy: dict | None = None,
    telemetry_refs: list[dict] | None = None,
) -> dict:
    payload = {
        "evidence_bundle_id": "evidence-edge-trust-1",
        "task_id": "task-edge-trust-1",
        "intent_id": "intent-edge-trust-1",
        "execution_token_id": "token-edge-trust-1",
        "policy_receipt_id": "policy-receipt-edge-trust-1",
        "evidence_inputs": {
            "request_schema_bundle": {
                "security_contract": {
                    "required_evidence": ["signed_edge_telemetry"],
                }
            },
            "policy_receipt": {
                "policy_receipt_id": "policy-receipt-edge-trust-1",
                "asset_ref": "asset:lot-8841",
            },
            "edge_trust_enrollment": enrollment if enrollment is not None else _fixture(),
            "edge_trust_policy": edge_policy
            if edge_policy is not None
            else {
                "expected_zone_ref": "handoff_bay_3",
                "required_trust_anchor_types": ["software_dev_key"],
                "reference_time": "2026-04-02T12:00:05Z",
                "max_age_seconds": 10,
            },
        },
        "telemetry_refs": telemetry_refs if telemetry_refs is not None else [_telemetry_ref()],
        "media_refs": [],
        "created_at": "2026-04-02T12:00:05Z",
    }
    _, signer_metadata, signature, trust_proof = build_signed_artifact(
        artifact_type="evidence_bundle",
        payload=payload,
    )
    signed = {
        **payload,
        "signer_metadata": signer_metadata.model_dump(mode="json"),
        "signature": signature,
    }
    if trust_proof is not None:
        signed["trust_proof"] = trust_proof.model_dump(mode="json")
    return signed


def test_software_dev_key_enrollment_fixture_round_trips() -> None:
    fixture = EdgeTrustEnrollmentBundle.model_validate(_fixture())

    assert fixture.contract_version == EDGE_TRUST_ENROLLMENT_VERSION
    assert fixture.devices[0].device_profile == "simulator"
    assert fixture.signers[0].trust_anchor_type == "software_dev_key"
    assert fixture.metadata["production_attestation"] is False
    assert {device.status for device in fixture.devices} == {"active", "quarantined"}
    assert any(signer.status == "revoked" for signer in fixture.signers)


def test_fixture_edge_trust_adapter_lookup_methods() -> None:
    adapter = FixtureEdgeTrustAdapter(_fixture())

    assert adapter.get_device("edge:handoff-bay-3").device_id == "device:sim-handoff-bay-3"
    assert adapter.get_device_by_id("device:trusted-vault-a").edge_node_ref == "edge:trusted-vault-a"
    assert adapter.get_signer("software_dev_key:edge-signing-demo").trust_anchor_type == "software_dev_key"


def test_adapter_accepts_software_dev_key_fixture_profile() -> None:
    result = validate_edge_trust_telemetry_refs(
        telemetry_refs=[_telemetry_ref()],
        enrollment=_fixture(),
        expected_asset_ref="asset:lot-8841",
        expected_zone_ref="handoff_bay_3",
        required_trust_anchor_types=["software_dev_key"],
        reference_time="2026-04-02T12:00:05Z",
        max_age_seconds=10,
    )

    assert result["verified"] is True
    assert result["device_ids"] == ["device:sim-handoff-bay-3"]
    assert result["signer_key_refs"] == ["software_dev_key:edge-signing-demo"]
    assert result["trust_anchor_types"] == ["software_dev_key"]


def test_adapter_rejects_software_dev_key_when_hardware_anchor_required() -> None:
    result = validate_edge_trust_telemetry_refs(
        telemetry_refs=[_telemetry_ref()],
        enrollment=_fixture(),
        expected_asset_ref="asset:lot-8841",
        expected_zone_ref="handoff_bay_3",
        required_trust_anchor_types=["tpm", "kms", "tee"],
    )

    assert result["verified"] is False
    assert result["error"] == "telemetry_trust_anchor_insufficient"


def test_adapter_rejects_simulator_device_profile_in_trusted_profile() -> None:
    result = validate_edge_trust_telemetry_refs(
        telemetry_refs=[_telemetry_ref()],
        enrollment=_fixture(),
        expected_asset_ref="asset:lot-8841",
        expected_zone_ref="handoff_bay_3",
        required_device_profiles=["trusted_edge"],
    )

    assert result["verified"] is False
    assert result["error"] == "telemetry_device_profile_mismatch"


def test_adapter_rejects_untrusted_sensor_kind() -> None:
    result = validate_edge_trust_telemetry_refs(
        telemetry_refs=[_telemetry_ref(sensor_kind="temperature")],
        enrollment=_fixture(),
        expected_asset_ref="asset:lot-8841",
    )

    assert result["verified"] is False
    assert result["error"] == "telemetry_evidence_kind_mismatch"


def test_adapter_fails_closed_for_wrong_zone_stale_and_replay() -> None:
    wrong_zone = validate_edge_trust_telemetry_refs(
        telemetry_refs=[_telemetry_ref()],
        enrollment=_fixture(),
        expected_asset_ref="asset:lot-8841",
        expected_zone_ref="handoff_bay_9",
        required_trust_anchor_types=["software_dev_key"],
    )
    stale = validate_edge_trust_telemetry_refs(
        telemetry_refs=[_telemetry_ref()],
        enrollment=_fixture(),
        expected_asset_ref="asset:lot-8841",
        reference_time="2026-04-02T12:05:00Z",
        max_age_seconds=10,
    )
    replayed = validate_edge_trust_telemetry_refs(
        telemetry_refs=[_telemetry_ref()],
        enrollment=_fixture(),
        expected_asset_ref="asset:lot-8841",
        replayed_payload_hashes=[_telemetry_ref()["payload_sha256"]],
    )

    assert wrong_zone["error"] == "telemetry_scope_mismatch"
    assert stale["error"] == "telemetry_too_stale"
    assert replayed["error"] == "telemetry_replay_detected"


def test_evidence_verifier_consumes_edge_trust_enrollment_fixture() -> None:
    verification = verify_evidence_bundle_result(_signed_evidence_bundle())

    assert verification["verified"] is True
    assert verification["signed_edge_telemetry"]["edge_trust"]["verified"] is True
    assert verification["signed_edge_telemetry"]["edge_trust"]["trust_anchor_types"] == ["software_dev_key"]


def test_evidence_verifier_fails_closed_for_revoked_signer() -> None:
    enrollment = copy.deepcopy(_fixture())
    enrollment["signers"][0]["status"] = "revoked"
    verification = verify_evidence_bundle_result(
        _signed_evidence_bundle(enrollment=enrollment)
    )

    assert verification["verified"] is False
    assert verification["error"] == "telemetry_signer_revoked"


def test_evidence_verifier_fails_closed_for_quarantined_device() -> None:
    verification = verify_evidence_bundle_result(
        _signed_evidence_bundle(
            telemetry_refs=[
                _telemetry_ref(
                    telemetry_id="tel-prototype-001",
                    edge_node_ref="edge:prototype-quarantined-01",
                    signer_key_ref="kms:edge:prototype-quarantined-01",
                )
            ],
            edge_policy={
                "expected_zone_ref": "handoff_bay_3",
                "required_trust_anchor_types": ["kms"],
            },
        )
    )

    assert verification["verified"] is False
    assert verification["error"] == "telemetry_device_quarantined"
