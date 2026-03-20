from __future__ import annotations

from typing import Any, Mapping, Optional

from seedcore.models.evidence_bundle import EvidenceBundle, HALCaptureEnvelope, PolicyReceipt, SignerMetadata
from seedcore.ops.evidence.policy import (
    canonical_json,
    resolve_public_key_from_registry,
    sha256_hex,
    verify_payload_signature,
)
from seedcore.ops.evidence.signers import build_signer_metadata, resolve_artifact_signer


def build_signed_artifact(
    *,
    artifact_type: str,
    payload: dict[str, Any],
    endpoint_id: Optional[str] = None,
    trust_level: Optional[str] = None,
    node_id: Optional[str] = None,
) -> tuple[str, SignerMetadata, str]:
    signer = resolve_artifact_signer(
        artifact_type=artifact_type,
        endpoint_id=endpoint_id,
        trust_level=trust_level,
        node_id=node_id,
    )
    payload_hash = sha256_hex(canonical_json(payload))
    signing_result = signer.sign(payload_hash)
    signer_metadata = build_signer_metadata(
        signing_result=signing_result,
        node_id=node_id,
    )
    return payload_hash, signer_metadata, signing_result.signature


def verify_artifact_signature(
    *,
    artifact_type: str = "evidence_bundle",
    payload: Mapping[str, Any],
    signer_metadata: Mapping[str, Any] | SignerMetadata,
    signature: str,
    endpoint_id: Optional[str] = None,
    trust_level: Optional[str] = None,
    attested: Optional[bool] = None,
) -> Optional[str]:
    result = verify_artifact_signature_result(
        artifact_type=artifact_type,
        payload=payload,
        signer_metadata=signer_metadata,
        signature=signature,
        endpoint_id=endpoint_id,
        trust_level=trust_level,
        attested=attested,
    )
    return result.get("error")


def verify_artifact_signature_result(
    *,
    artifact_type: str,
    payload: Mapping[str, Any],
    signer_metadata: Mapping[str, Any] | SignerMetadata,
    signature: str,
    endpoint_id: Optional[str] = None,
    trust_level: Optional[str] = None,
    attested: Optional[bool] = None,
) -> dict[str, Any]:
    return verify_payload_signature(
        artifact_type=artifact_type,
        payload=payload,
        signer_metadata=signer_metadata,
        signature=signature,
        endpoint_id=endpoint_id,
        trust_level=trust_level,
        attested=attested,
        public_key_resolver=_resolve_ed25519_public_key,
    )


def verify_policy_receipt(receipt: Mapping[str, Any] | PolicyReceipt) -> Optional[str]:
    return verify_policy_receipt_result(receipt).get("error")


def verify_policy_receipt_result(receipt: Mapping[str, Any] | PolicyReceipt) -> dict[str, Any]:
    try:
        model = receipt if isinstance(receipt, PolicyReceipt) else PolicyReceipt(**dict(receipt))
    except Exception:
        return {
            "artifact_type": "policy_receipt",
            "verified": False,
            "error": "invalid_policy_receipt",
            "policy": {},
        }
    payload = model.model_dump(mode="json", exclude={"signature", "signer_metadata"})
    return verify_artifact_signature_result(
        artifact_type="policy_receipt",
        payload=payload,
        signer_metadata=model.signer_metadata,
        signature=model.signature,
    )


def verify_evidence_bundle(bundle: Mapping[str, Any] | EvidenceBundle) -> Optional[str]:
    return verify_evidence_bundle_result(bundle).get("error")


def verify_evidence_bundle_result(bundle: Mapping[str, Any] | EvidenceBundle) -> dict[str, Any]:
    try:
        model = bundle if isinstance(bundle, EvidenceBundle) else EvidenceBundle(**dict(bundle))
    except Exception:
        return {
            "artifact_type": "evidence_bundle",
            "verified": False,
            "error": "invalid_evidence_bundle",
            "policy": {},
        }
    payload = model.model_dump(mode="json", exclude={"signature", "signer_metadata"})
    node_id = str(model.node_id) if model.node_id is not None else None
    return verify_artifact_signature_result(
        artifact_type="evidence_bundle",
        payload=payload,
        signer_metadata=model.signer_metadata,
        signature=model.signature,
        endpoint_id=node_id,
        trust_level=(
            "attested"
            if model.signer_metadata.attestation_level == "attested"
            else "baseline"
        ),
        attested=model.signer_metadata.attestation_level == "attested",
    )


def verify_hal_capture_envelope(envelope: Mapping[str, Any] | HALCaptureEnvelope) -> Optional[str]:
    return verify_hal_capture_envelope_result(envelope).get("error")


def verify_hal_capture_envelope_result(envelope: Mapping[str, Any] | HALCaptureEnvelope) -> dict[str, Any]:
    try:
        model = envelope if isinstance(envelope, HALCaptureEnvelope) else HALCaptureEnvelope(**dict(envelope))
    except Exception:
        return {
            "artifact_type": "hal_capture",
            "verified": False,
            "error": "invalid_hal_capture_envelope",
            "policy": {},
        }
    payload = model.model_dump(mode="json", exclude={"signature", "signer_metadata"})
    return verify_artifact_signature_result(
        artifact_type="hal_capture",
        payload=payload,
        signer_metadata=model.signer_metadata,
        signature=model.signature,
        endpoint_id=model.node_id,
        trust_level="attested",
        attested=True,
    )


def _resolve_ed25519_public_key(metadata: SignerMetadata):
    return resolve_public_key_from_registry(
        metadata,
        registry_env="SEEDCORE_EVIDENCE_PUBLIC_KEYS_JSON",
        candidate_fields=("key_ref", "signer_id", "node_id"),
    )
