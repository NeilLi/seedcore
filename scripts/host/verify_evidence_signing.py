#!/usr/bin/env python3
"""Verify evidence completeness, signer selection, receipt chains, and fingerprints."""

from __future__ import annotations

import base64
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
TESTS_ROOT = PROJECT_ROOT / "tests"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from seedcore.ops.evidence.builder import attach_evidence_bundle
from seedcore.ops.evidence.verification import (
    build_signed_artifact,
    verify_evidence_bundle_result,
    verify_policy_receipt_result,
)
from seedcore.services.replay_service import ReplayService
from seedcore.hal.custody.transition_receipts import verify_transition_receipt_result
from test_replay_router import _build_audit_record


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: dict[str, Any]


def _task_dict() -> dict[str, Any]:
    return {
        "task_id": "task-runtime-evidence-signing",
        "type": "action",
        "params": {
            "multimodal": {
                "detections": [{"label": "sealed_box", "confidence": 0.93}],
                "gps": {"lat": 13.123, "lon": 100.987},
            },
            "governance": {
                "node_id": "robot_sim://pybullet_r2d2_01",
                "action_intent": {
                    "intent_id": "intent-runtime-evidence-signing",
                    "resource": {
                        "asset_id": "asset-runtime-evidence-signing",
                        "provenance_hash": "prov-runtime-evidence-signing",
                        "target_zone": "vault_alpha",
                    },
                },
                "execution_token": {
                    "token_id": "token-runtime-evidence-signing",
                    "constraints": {"endpoint_id": "robot_sim://pybullet_r2d2_01"},
                },
                "policy_decision": {"allowed": True, "reason": "zone_match"},
            },
        },
    }


def main() -> int:
    results: list[CheckResult] = []

    bundle = attach_evidence_bundle(
        task_dict=_task_dict(),
        envelope={
            "payload": {"results": []},
            "meta": {"exec": {"finished_at": "2026-03-24T10:30:30+00:00"}},
        },
        organ_id="actuation_organ",
        agent_id="agent-1",
    )["meta"]["evidence_bundle"]
    results.append(
        CheckResult(
            "evidence.completeness",
            bool(bundle.get("policy_receipt_id"))
            and bool(bundle.get("asset_fingerprint"))
            and bool(bundle.get("telemetry_refs"))
            and isinstance(bundle.get("evidence_inputs", {}).get("execution_summary"), dict),
            {
                "has_policy_receipt_id": bool(bundle.get("policy_receipt_id")),
                "has_asset_fingerprint": bool(bundle.get("asset_fingerprint")),
                "telemetry_ref_count": len(bundle.get("telemetry_refs") or []),
                "transition_receipt_count": len(bundle.get("transition_receipt_ids") or []),
            },
        )
    )

    payload = {"artifact_id": "signer-runtime", "status": "ok"}
    _, hmac_metadata, _ = build_signed_artifact(
        artifact_type="evidence_bundle",
        payload=payload,
    )

    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    previous_mode = os.environ.get("SEEDCORE_EVIDENCE_BUNDLE_SIGNER_MODE")
    previous_priv = os.environ.get("SEEDCORE_EVIDENCE_ED25519_PRIVATE_KEY_B64")
    previous_pub = os.environ.get("SEEDCORE_EVIDENCE_PUBLIC_KEYS_JSON")
    previous_key = os.environ.get("SEEDCORE_EVIDENCE_ED25519_KEY_ID")
    try:
        os.environ["SEEDCORE_EVIDENCE_BUNDLE_SIGNER_MODE"] = "ed25519"
        os.environ["SEEDCORE_EVIDENCE_ED25519_PRIVATE_KEY_B64"] = base64.b64encode(private_bytes).decode("ascii")
        os.environ["SEEDCORE_EVIDENCE_PUBLIC_KEYS_JSON"] = json.dumps(
            {"evidence-ed25519-runtime": {"public_key": base64.b64encode(public_bytes).decode("ascii")}}
        )
        os.environ["SEEDCORE_EVIDENCE_ED25519_KEY_ID"] = "evidence-ed25519-runtime"
        _, ed_metadata, _ = build_signed_artifact(
            artifact_type="evidence_bundle",
            payload=payload,
            endpoint_id="robot_sim://pybullet_r2d2_01",
            trust_level="attested",
            node_id="robot_sim://pybullet_r2d2_01",
        )
    finally:
        if previous_mode is None:
            os.environ.pop("SEEDCORE_EVIDENCE_BUNDLE_SIGNER_MODE", None)
        else:
            os.environ["SEEDCORE_EVIDENCE_BUNDLE_SIGNER_MODE"] = previous_mode
        if previous_priv is None:
            os.environ.pop("SEEDCORE_EVIDENCE_ED25519_PRIVATE_KEY_B64", None)
        else:
            os.environ["SEEDCORE_EVIDENCE_ED25519_PRIVATE_KEY_B64"] = previous_priv
        if previous_pub is None:
            os.environ.pop("SEEDCORE_EVIDENCE_PUBLIC_KEYS_JSON", None)
        else:
            os.environ["SEEDCORE_EVIDENCE_PUBLIC_KEYS_JSON"] = previous_pub
        if previous_key is None:
            os.environ.pop("SEEDCORE_EVIDENCE_ED25519_KEY_ID", None)
        else:
            os.environ["SEEDCORE_EVIDENCE_ED25519_KEY_ID"] = previous_key
    results.append(
        CheckResult(
            "evidence.signer_abstraction",
            hmac_metadata.signing_scheme == "hmac_sha256" and ed_metadata.signing_scheme == "ed25519",
            {
                "hmac_scheme": hmac_metadata.signing_scheme,
                "ed25519_scheme": ed_metadata.signing_scheme,
                "ed25519_key_ref": ed_metadata.key_ref,
            },
        )
    )

    record = _build_audit_record(
        task_id="task-runtime-signer-chain",
        intent_id="intent-runtime-signer-chain",
        asset_id="asset-runtime-signer-chain",
    )
    replay_service = ReplayService()
    transition_receipts = record["evidence_bundle"]["evidence_inputs"]["transition_receipts"]
    signer_chain = replay_service._build_signer_chain(  # noqa: SLF001 - verifier target
        policy_receipt=record["policy_receipt"],
        evidence_bundle=record["evidence_bundle"],
        transition_receipts=transition_receipts,
    )
    verified = replay_service._build_verification_status(  # noqa: SLF001 - verifier target
        policy_receipt=record["policy_receipt"],
        evidence_bundle=record["evidence_bundle"],
        transition_receipts=transition_receipts,
    )
    tampered = dict(transition_receipts[0])
    tampered["payload_hash"] = "broken-hash"
    tampered_result = verify_transition_receipt_result(tampered)
    results.append(
        CheckResult(
            "evidence.receipt_chains_validate",
            verified.verified is True
            and [item["artifact_type"] for item in signer_chain] == ["policy_receipt", "evidence_bundle", "transition_receipt"]
            and tampered_result["verified"] is False
            and tampered_result["error"] == "payload_hash_mismatch",
            {
                "chain_types": [item["artifact_type"] for item in signer_chain],
                "verified": verified.verified,
                "tamper_error": tampered_result["error"],
            },
        )
    )

    fingerprint = bundle["asset_fingerprint"]
    replay_like = type("ReplayLike", (), {"evidence_bundle": {"asset_fingerprint": fingerprint}})()
    summary = replay_service._build_fingerprint_summary(replay_like)  # noqa: SLF001 - verifier target
    results.append(
        CheckResult(
            "evidence.fingerprints_preserve_metadata",
            fingerprint["capture_context"]["target_zone"] == "vault_alpha"
            and fingerprint["hardware_witness"]["node_id"] == "robot_sim://pybullet_r2d2_01"
            and summary["fingerprint_hash"] == fingerprint["fingerprint_hash"],
            {
                "capture_context": fingerprint["capture_context"],
                "hardware_witness": fingerprint["hardware_witness"],
                "summary_modalities": summary["modalities"],
            },
        )
    )

    results.append(
        CheckResult(
            "evidence.signed_artifacts_verify",
            verify_policy_receipt_result(record["policy_receipt"])["verified"] is True
            and verify_evidence_bundle_result(record["evidence_bundle"])["verified"] is True,
            {
                "policy_verified": verify_policy_receipt_result(record["policy_receipt"])["verified"],
                "bundle_verified": verify_evidence_bundle_result(record["evidence_bundle"])["verified"],
            },
        )
    )

    failing = [result for result in results if not result.ok]
    for result in results:
        marker = "PASS" if result.ok else "FAIL"
        print(f"[{marker}] {result.name}: {json.dumps(result.detail, sort_keys=True)}")

    if failing:
        print(f"\nEvidence and signing verification failed: {len(failing)} checks failed.", file=sys.stderr)
        return 1

    print("\nEvidence and signing verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
