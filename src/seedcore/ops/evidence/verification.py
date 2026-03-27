from __future__ import annotations

from typing import Any, Mapping, Optional

from seedcore.models.evidence_bundle import (
    EvidenceBundle,
    HALCaptureEnvelope,
    PolicyReceipt,
    SignerMetadata,
    TrustProof,
)
from seedcore.ops.evidence.policy import (
    canonical_json,
    resolve_public_key_from_registry,
    sha256_hex,
    verify_payload_signature,
)
from seedcore.ops.evidence.signers import (
    SignerRequest,
    build_signer_metadata,
    sign_artifact_request,
)


def build_signed_artifact(
    *,
    artifact_type: str,
    payload: dict[str, Any],
    endpoint_id: Optional[str] = None,
    trust_level: Optional[str] = None,
    node_id: Optional[str] = None,
    workflow_type: Optional[str] = None,
    receipt_nonce: Optional[str] = None,
    previous_receipt_hash: Optional[str] = None,
    previous_receipt_counter: Optional[int] = None,
    transparency_enabled: Optional[bool] = None,
) -> tuple[str, SignerMetadata, str, Optional[TrustProof]]:
    resolved_workflow_type = (
        workflow_type
        if isinstance(workflow_type, str)
        else (
            payload.get("workflow_type")
            if isinstance(payload.get("workflow_type"), str)
            else None
        )
    )
    resolved_receipt_nonce = (
        receipt_nonce
        if isinstance(receipt_nonce, str)
        else (
            payload.get("receipt_nonce")
            if isinstance(payload.get("receipt_nonce"), str)
            else None
        )
    )
    resolved_previous_receipt_hash = (
        previous_receipt_hash
        if isinstance(previous_receipt_hash, str)
        else (
            payload.get("previous_receipt_hash")
            if isinstance(payload.get("previous_receipt_hash"), str)
            else None
        )
    )
    resolved_previous_receipt_counter = (
        int(previous_receipt_counter)
        if previous_receipt_counter is not None
        else (
            int(payload.get("previous_receipt_counter"))
            if payload.get("previous_receipt_counter") is not None
            else None
        )
    )
    resolved_transparency_enabled = (
        bool(transparency_enabled)
        if transparency_enabled is not None
        else bool(
            artifact_type == "transition_receipt"
            and str(resolved_workflow_type or "").strip().lower()
            in {"custody_transfer", "restricted_custody_transfer"}
        )
    )
    payload_hash = sha256_hex(canonical_json(payload))
    signing_result = sign_artifact_request(
        SignerRequest(
            artifact_type=artifact_type,
            signer_profile="receipt" if artifact_type == "transition_receipt" else ("pdp" if artifact_type == "policy_receipt" else "execution"),
            payload_hash=payload_hash,
            endpoint_id=endpoint_id,
            node_id=node_id,
            trust_level=trust_level,
            workflow_type=resolved_workflow_type,
            receipt_nonce=resolved_receipt_nonce,
            previous_receipt_hash=resolved_previous_receipt_hash,
            previous_receipt_counter=resolved_previous_receipt_counter,
            transparency_enabled=resolved_transparency_enabled,
        )
    )
    signer_metadata = build_signer_metadata(
        signing_result=signing_result,
        node_id=node_id,
    )
    return payload_hash, signer_metadata, signing_result.signature, signing_result.trust_proof


def verify_artifact_signature(
    *,
    artifact_type: str = "evidence_bundle",
    payload: Mapping[str, Any],
    signer_metadata: Mapping[str, Any] | SignerMetadata,
    signature: str,
    endpoint_id: Optional[str] = None,
    trust_level: Optional[str] = None,
    attested: Optional[bool] = None,
    trust_proof: Mapping[str, Any] | TrustProof | None = None,
) -> Optional[str]:
    result = verify_artifact_signature_result(
        artifact_type=artifact_type,
        payload=payload,
        signer_metadata=signer_metadata,
        signature=signature,
        endpoint_id=endpoint_id,
        trust_level=trust_level,
        attested=attested,
        trust_proof=trust_proof,
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
    trust_proof: Mapping[str, Any] | TrustProof | None = None,
) -> dict[str, Any]:
    result = verify_payload_signature(
        artifact_type=artifact_type,
        payload=payload,
        signer_metadata=signer_metadata,
        signature=signature,
        endpoint_id=endpoint_id,
        trust_level=trust_level,
        attested=attested,
        public_key_resolver=_resolve_ed25519_public_key,
    )
    if result.get("error") is not None:
        return result
    if trust_proof is not None:
        proof = trust_proof if isinstance(trust_proof, TrustProof) else TrustProof(**dict(trust_proof))
        result["trust_proof"] = proof.model_dump(mode="json")
        result["trust_anchor_type"] = proof.trust_anchor_type
        result["key_algorithm"] = proof.key_algorithm
    return result


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
    payload = model.model_dump(mode="json", exclude={"signature", "signer_metadata", "trust_proof"})
    return verify_artifact_signature_result(
        artifact_type="policy_receipt",
        payload=payload,
        signer_metadata=model.signer_metadata,
        signature=model.signature,
        trust_proof=model.trust_proof,
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
    payload = model.model_dump(mode="json", exclude={"signature", "signer_metadata", "trust_proof"})
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
        trust_proof=model.trust_proof,
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
    payload = model.model_dump(mode="json", exclude={"signature", "signer_metadata", "trust_proof"})
    return verify_artifact_signature_result(
        artifact_type="hal_capture",
        payload=payload,
        signer_metadata=model.signer_metadata,
        signature=model.signature,
        endpoint_id=model.node_id,
        trust_level="attested",
        attested=True,
        trust_proof=model.trust_proof,
    )


def _resolve_ed25519_public_key(metadata: SignerMetadata):
    return resolve_public_key_from_registry(
        metadata,
        registry_env="SEEDCORE_EVIDENCE_PUBLIC_KEYS_JSON",
        candidate_fields=("key_ref", "signer_id", "node_id"),
    )
