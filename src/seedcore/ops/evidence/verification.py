from __future__ import annotations

from typing import Any, Mapping, Optional

from seedcore.models.evidence_bundle import (
    CoSignature,
    EvidenceBundle,
    HALCaptureEnvelope,
    PolicyReceipt,
    SignerMetadata,
    TrustProof,
)
from seedcore.models.edge_telemetry import (
    EDGE_TELEMETRY_ENVELOPE_VERSION,
    SignedEdgeTelemetryRefV0,
)
from seedcore.ops.evidence.policy import (
    canonical_json,
    resolve_public_key_from_registry,
    resolve_hmac_secret_from_registry,
    sha256_hex,
    verify_payload_signature,
)
from seedcore.ops.evidence.signers import (
    SignerRequest,
    build_signer_metadata,
    sign_artifact_request,
)


def _verify_asset_fingerprint_proof(model: EvidenceBundle) -> dict[str, Any]:
    fingerprint = model.asset_fingerprint
    if fingerprint is None:
        return {"verified": True}

    derivation_logic = fingerprint.derivation_logic if isinstance(fingerprint.derivation_logic, dict) else {}
    capture_context = fingerprint.capture_context if isinstance(fingerprint.capture_context, dict) else {}
    modality_map = fingerprint.modality_map if isinstance(fingerprint.modality_map, dict) else {}
    expectations = derivation_logic.get("registry_expectations")
    if not isinstance(expectations, dict) or not expectations:
        expectations = capture_context.get("registry_expectations")
    if not isinstance(expectations, dict) or not expectations:
        return {"verified": True}

    normalized_expectations = {
        str(key).strip(): str(value).strip()
        for key, value in expectations.items()
        if str(key).strip() and value is not None and str(value).strip()
    }
    if not normalized_expectations:
        return {"verified": True}

    missing = sorted(key for key in normalized_expectations.keys() if key not in modality_map)
    mismatched = sorted(
        key for key, expected in normalized_expectations.items() if key in modality_map and str(modality_map.get(key)) != expected
    )
    verified = not missing and not mismatched
    result = {
        "verified": verified,
        "registry_expectations": normalized_expectations,
        "missing_modalities": missing,
        "mismatched_modalities": mismatched,
    }
    if not verified:
        result["error"] = "asset_fingerprint_registry_mismatch"
    return result


def build_signed_artifact(
    *,
    artifact_type: str,
    payload: dict[str, Any],
    endpoint_id: Optional[str] = None,
    trust_level: Optional[str] = None,
    node_id: Optional[str] = None,
    workflow_type: Optional[str] = None,
    disposition: Optional[str] = None,
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
    resolved_disposition = (
        disposition
        if isinstance(disposition, str)
        else (
            payload.get("authz_disposition")
            if isinstance(payload.get("authz_disposition"), str)
            else payload.get("disposition")
            if isinstance(payload.get("disposition"), str)
            else None
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
            disposition=resolved_disposition,
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
    payload = model.model_dump(
        mode="json",
        exclude={"signature", "signer_metadata", "trust_proof"},
        exclude_unset=True,
    )
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
    payload = model.model_dump(
        mode="json",
        exclude={"signature", "signer_metadata", "trust_proof"},
        exclude_unset=True,
    )
    node_id = str(model.node_id) if model.node_id is not None else None
    result = verify_artifact_signature_result(
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
    if result.get("error") is not None:
        return result

    fingerprint_result = _verify_asset_fingerprint_proof(model)
    result["asset_fingerprint_proof"] = fingerprint_result
    if fingerprint_result.get("error") is not None:
        result["verified"] = False
        result["error"] = str(fingerprint_result.get("error"))
        return result

    telemetry_result = _verify_required_signed_edge_telemetry(model)
    result["signed_edge_telemetry"] = telemetry_result
    if telemetry_result.get("error") is not None:
        result["verified"] = False
        result["error"] = str(telemetry_result.get("error"))
        return result

    co_signature_result = _verify_evidence_bundle_co_signatures(model)
    result.update(
        {
            "co_sign_required": bool(model.co_sign_required),
            "co_sign_status": model.co_sign_status,
            "transfer_outcome": model.transfer_outcome,
            "co_sign_binding_hash": model.co_sign_binding_hash,
            "co_signature_count": len(model.co_signatures),
            "co_signatures_verified": bool(co_signature_result.get("verified")),
            "expected_co_signer_refs": [
                str(item.get("principal_ref"))
                for item in model.expected_co_signers
                if isinstance(item, dict) and item.get("principal_ref") is not None
            ],
        }
    )
    if co_signature_result.get("error") is not None:
        result["verified"] = False
        result["error"] = str(co_signature_result.get("error"))
    return result


def _verify_required_signed_edge_telemetry(model: EvidenceBundle) -> dict[str, Any]:
    required = _signed_edge_telemetry_required(model)
    signed_refs = [
        ref
        for ref in model.telemetry_refs
        if isinstance(ref, dict)
        and ref.get("contract_version") == EDGE_TELEMETRY_ENVELOPE_VERSION
    ]
    result = {
        "required": required,
        "signed_ref_count": len(signed_refs),
        "verified": True,
        "error": None,
    }
    if not required:
        return result
    if not signed_refs:
        result.update({"verified": False, "error": "missing_signed_edge_telemetry"})
        return result

    expected_asset = _expected_evidence_asset_ref(model)
    for ref in signed_refs:
        try:
            parsed = SignedEdgeTelemetryRefV0(**dict(ref))
        except Exception:
            result.update({"verified": False, "error": "invalid_signed_edge_telemetry_ref"})
            return result
        if expected_asset and _normalize_asset_ref(parsed.asset_ref) != _normalize_asset_ref(expected_asset):
            result.update({"verified": False, "error": "signed_edge_telemetry_asset_mismatch"})
            return result
    return result


def _signed_edge_telemetry_required(model: EvidenceBundle) -> bool:
    inputs = model.evidence_inputs if isinstance(model.evidence_inputs, dict) else {}
    request_schema = (
        inputs.get("request_schema_bundle")
        if isinstance(inputs.get("request_schema_bundle"), dict)
        else {}
    )
    policy_receipt = (
        inputs.get("policy_receipt")
        if isinstance(inputs.get("policy_receipt"), dict)
        else {}
    )
    containers = [
        inputs,
        request_schema,
        request_schema.get("security_contract")
        if isinstance(request_schema.get("security_contract"), dict)
        else {},
        policy_receipt.get("decision")
        if isinstance(policy_receipt.get("decision"), dict)
        else {},
    ]
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in (
            "require_signed_edge_telemetry",
            "signed_edge_telemetry_required",
            "hardware_anchored_telemetry_required",
        ):
            if bool(container.get(key)):
                return True
        required_evidence = container.get("required_evidence")
        if isinstance(required_evidence, list) and any(
            str(item).strip() == "signed_edge_telemetry" for item in required_evidence
        ):
            return True
    return False


def _expected_evidence_asset_ref(model: EvidenceBundle) -> Optional[str]:
    inputs = model.evidence_inputs if isinstance(model.evidence_inputs, dict) else {}
    policy_receipt = (
        inputs.get("policy_receipt")
        if isinstance(inputs.get("policy_receipt"), dict)
        else {}
    )
    for candidate in (
        policy_receipt.get("asset_ref"),
        model.asset_fingerprint.capture_context.get("asset_id")
        if model.asset_fingerprint is not None
        and isinstance(model.asset_fingerprint.capture_context, dict)
        else None,
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _normalize_asset_ref(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized.startswith("asset:"):
        return normalized.split(":", 1)[1]
    return normalized


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
    payload = model.model_dump(
        mode="json",
        exclude={"signature", "signer_metadata", "trust_proof"},
        exclude_unset=True,
    )
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


def _verify_evidence_bundle_co_signatures(model: EvidenceBundle) -> dict[str, Any]:
    if not model.co_sign_required and not model.co_signatures:
        return {"verified": True, "error": None}
    if not model.co_sign_binding_hash:
        return {"verified": False, "error": "missing_co_sign_binding_hash"}

    payload = {"binding_hash": model.co_sign_binding_hash}
    expected_refs = [
        str(item.get("principal_ref")).strip()
        for item in model.expected_co_signers
        if isinstance(item, dict) and item.get("principal_ref") is not None and str(item.get("principal_ref")).strip()
    ]
    expected_set = set(expected_refs)
    actual_refs: list[str] = []
    for raw in model.co_signatures:
        signature = raw if isinstance(raw, CoSignature) else CoSignature(**dict(raw))
        principal_ref = str(signature.principal_ref).strip()
        if not principal_ref:
            return {"verified": False, "error": "invalid_co_signer_ref"}
        if principal_ref in actual_refs:
            return {"verified": False, "error": "duplicate_co_signer"}
        verification = verify_payload_signature(
            artifact_type="evidence_bundle",
            payload=payload,
            signer_metadata=signature.signer_metadata,
            signature=signature.signature,
            public_key_resolver=_resolve_ed25519_public_key,
            secret_resolver=_resolve_cosigner_hmac_secret,
        )
        if verification.get("error") is not None:
            return {
                "verified": False,
                "error": f"co_sign_signature_invalid:{principal_ref}:{verification['error']}",
            }
        actual_refs.append(principal_ref)

    actual_set = set(actual_refs)
    outcome = str(model.transfer_outcome or "").strip().upper()
    status = str(model.co_sign_status or "").strip().lower()
    if outcome == "EMERGENCY_OVERRIDE" or status == "emergency_override":
        if not actual_refs:
            return {"verified": False, "error": "missing_emergency_override_signature"}
        override_roles = {
            str(item.signer_role or "").strip().upper()
            for item in model.co_signatures
        }
        if "ZONE_ADMINISTRATOR" not in override_roles and "ZONE_ADMIN" not in override_roles:
            return {"verified": False, "error": "missing_zone_admin_override_signature"}
        return {"verified": True, "error": None}

    if model.co_sign_required:
        if len(actual_set) < 2:
            return {"verified": False, "error": "missing_co_signatures"}
        if expected_set and not expected_set.issubset(actual_set):
            return {"verified": False, "error": "co_signer_mismatch"}
    return {"verified": True, "error": None}


def _resolve_cosigner_hmac_secret(metadata: SignerMetadata) -> Optional[str]:
    return resolve_hmac_secret_from_registry(
        metadata,
        registry_env="SEEDCORE_EVIDENCE_CO_SIGNER_SECRETS_JSON",
        candidate_fields=("signer_id", "key_ref", "node_id"),
    ) or resolve_hmac_secret_from_registry(
        metadata,
        registry_env="SEEDCORE_EVIDENCE_SIGNER_SECRETS_JSON",
        candidate_fields=("signer_id", "key_ref", "node_id"),
    )
