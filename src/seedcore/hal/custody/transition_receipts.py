from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from seedcore.models.evidence_bundle import SignerMetadata, TransitionReceipt, TrustProof
from seedcore.ops.evidence.policy import (
    canonical_json,
    resolve_public_key_from_registry,
    sha256_hex,
    verify_payload_signature,
)
from seedcore.ops.evidence.signers import (
    ECDSA_P256_SCHEME,
    RESTRICTED_CUSTODY_TRANSFER_WORKFLOW_TYPES,
)
from seedcore.ops.evidence.verification import build_signed_artifact

logger = logging.getLogger(__name__)


def build_transition_receipt(
    *,
    intent_id: str,
    token_id: str,
    actuator_endpoint: str,
    hardware_uuid: str,
    actuator_result_hash: str,
    target_zone: Optional[str] = None,
    from_zone: Optional[str] = None,
    to_zone: Optional[str] = None,
    executed_at: Optional[str] = None,
    receipt_nonce: Optional[str] = None,
    workflow_type: Optional[str] = None,
    previous_receipt_hash: Optional[str] = None,
    previous_receipt_counter: Optional[int] = None,
) -> Dict[str, Any]:
    payload = {
        "transition_receipt_id": str(uuid.uuid4()),
        "intent_id": str(intent_id),
        "execution_token_id": str(token_id),
        "endpoint_id": str(actuator_endpoint),
        "workflow_type": str(workflow_type) if workflow_type is not None else None,
        "hardware_uuid": str(hardware_uuid),
        "actuator_result_hash": str(actuator_result_hash),
        "target_zone": str(target_zone) if target_zone is not None else None,
        "from_zone": str(from_zone) if from_zone is not None else None,
        "to_zone": str(to_zone) if to_zone is not None else None,
        "executed_at": executed_at or datetime.now(timezone.utc).isoformat(),
        "receipt_nonce": receipt_nonce or str(uuid.uuid4()),
    }
    payload_hash, signer_metadata, signature, trust_proof = build_signed_artifact(
        artifact_type="transition_receipt",
        payload=dict(payload),
        endpoint_id=actuator_endpoint,
        trust_level=(
            "attested"
            if is_attestable_transition_endpoint(actuator_endpoint)
            else "baseline"
        ),
        node_id=actuator_endpoint,
        workflow_type=workflow_type,
        receipt_nonce=payload["receipt_nonce"],
        previous_receipt_hash=previous_receipt_hash,
        previous_receipt_counter=previous_receipt_counter,
        transparency_enabled=bool(
            str(workflow_type or "").strip().lower() in RESTRICTED_CUSTODY_TRANSFER_WORKFLOW_TYPES
        ),
    )
    return TransitionReceipt(
        **payload,
        payload_hash=payload_hash,
        signer_metadata=signer_metadata,
        signature=signature,
        trust_proof=trust_proof,
    ).model_dump(mode="json")


def verify_transition_receipt(
    receipt: Dict[str, Any],
    *,
    expected_intent_id: Optional[str] = None,
    expected_token_id: Optional[str] = None,
    expected_endpoint_id: Optional[str] = None,
    expected_previous_receipt_hash: Optional[str] = None,
    expected_min_receipt_counter: Optional[int] = None,
) -> Optional[str]:
    return verify_transition_receipt_result(
        receipt,
        expected_intent_id=expected_intent_id,
        expected_token_id=expected_token_id,
        expected_endpoint_id=expected_endpoint_id,
        expected_previous_receipt_hash=expected_previous_receipt_hash,
        expected_min_receipt_counter=expected_min_receipt_counter,
    ).get("error")


def verify_transition_receipt_result(
    receipt: Dict[str, Any],
    *,
    expected_intent_id: Optional[str] = None,
    expected_token_id: Optional[str] = None,
    expected_endpoint_id: Optional[str] = None,
    expected_previous_receipt_hash: Optional[str] = None,
    expected_min_receipt_counter: Optional[int] = None,
) -> Dict[str, Any]:
    try:
        model = TransitionReceipt(**dict(receipt))
    except Exception:
        return {
            "artifact_type": "transition_receipt",
            "verified": False,
            "error": "invalid_receipt",
            "policy": {},
        }

    payload = model.model_dump(
        mode="json",
        exclude={"payload_hash", "signer_metadata", "signature", "trust_proof"},
    )
    expected_hash = sha256_hex(canonical_json(payload))
    if model.payload_hash != expected_hash:
        return {
            "artifact_type": "transition_receipt",
            "verified": False,
            "error": "payload_hash_mismatch",
            "policy": {},
        }

    verification = verify_payload_signature(
        artifact_type="transition_receipt",
        payload=payload,
        signer_metadata=model.signer_metadata,
        signature=model.signature,
        endpoint_id=model.endpoint_id,
        trust_level=(
            "attested"
            if is_attestable_transition_endpoint(model.endpoint_id)
            else "baseline"
        ),
        attested=is_attestable_transition_endpoint(model.endpoint_id),
        public_key_resolver=_resolve_public_key,
        secret_resolver=lambda _metadata: os.getenv(
            "SEEDCORE_HAL_RECEIPT_SIGNING_SECRET",
            os.getenv("SEEDCORE_EVIDENCE_SIGNING_SECRET", "seedcore-dev-evidence-secret"),
        ),
    )
    if verification.get("error") is not None:
        return verification

    trust_proof = model.trust_proof
    if _requires_restricted_receipt_hardening(model):
        trust_error = _verify_restricted_trust_proof(
            model,
            expected_previous_receipt_hash=expected_previous_receipt_hash,
            expected_min_receipt_counter=expected_min_receipt_counter,
        )
        if trust_error is not None:
            verification["verified"] = False
            verification["error"] = trust_error
            return verification
    elif trust_proof is not None:
        verification["trust_anchor_type"] = trust_proof.trust_anchor_type
        verification["replay"] = trust_proof.replay.model_dump(mode="json") if trust_proof.replay is not None else {}

    if expected_intent_id is not None and model.intent_id != str(expected_intent_id):
        verification["verified"] = False
        verification["error"] = "intent_id_mismatch"
        return verification
    if expected_token_id is not None and model.execution_token_id != str(expected_token_id):
        verification["verified"] = False
        verification["error"] = "token_id_mismatch"
        return verification
    if expected_endpoint_id is not None and model.endpoint_id != str(expected_endpoint_id):
        verification["verified"] = False
        verification["error"] = "endpoint_id_mismatch"
        return verification

    try:
        datetime.fromisoformat(model.executed_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        verification["verified"] = False
        verification["error"] = "invalid_executed_at"
        return verification

    if not model.receipt_nonce.strip():
        verification["verified"] = False
        verification["error"] = "missing_receipt_nonce"
        return verification
    return verification


def is_attestable_transition_endpoint(endpoint_id: Optional[str]) -> bool:
    if not isinstance(endpoint_id, str):
        return False
    normalized = endpoint_id.strip().lower()
    return normalized.startswith("hal://") or normalized.startswith("robot_sim://")


def _resolve_public_key(metadata: SignerMetadata):
    return resolve_public_key_from_registry(
        metadata,
        registry_env="SEEDCORE_HAL_RECEIPT_PUBLIC_KEYS_JSON",
        candidate_fields=("node_id", "signer_id", "key_ref"),
    )


def _requires_restricted_receipt_hardening(model: TransitionReceipt) -> bool:
    if not is_attestable_transition_endpoint(model.endpoint_id):
        return False
    workflow_type = str(model.workflow_type or "").strip().lower()
    return workflow_type in RESTRICTED_CUSTODY_TRANSFER_WORKFLOW_TYPES


def _verify_restricted_trust_proof(
    model: TransitionReceipt,
    *,
    expected_previous_receipt_hash: Optional[str],
    expected_min_receipt_counter: Optional[int],
) -> Optional[str]:
    proof = model.trust_proof
    if proof is None:
        return "missing_trust_proof"
    if proof.signer_profile != "receipt":
        return "invalid_signer_profile"
    if proof.key_algorithm != ECDSA_P256_SCHEME:
        return "invalid_key_algorithm"
    required_anchor = _required_restricted_trust_anchor(model.endpoint_id)
    if proof.trust_anchor_type not in {"tpm2", "kms", "vtpm"}:
        return "invalid_trust_anchor"
    if required_anchor is not None and proof.trust_anchor_type != required_anchor:
        return "invalid_trust_anchor"
    provider_mode = (
        proof.key_binding.metadata.get("provider_mode")
        if proof.key_binding is not None and isinstance(proof.key_binding.metadata, dict)
        else None
    )
    if (
        proof.trust_anchor_type == "tpm2"
        and provider_mode == "software_fallback"
        and not _env_flag("SEEDCORE_TPM2_ALLOW_SOFTWARE_FALLBACK", default=False)
    ):
        return "software_fallback_not_allowed"
    if proof.replay is None:
        return "missing_replay_proof"
    if proof.replay.receipt_nonce != model.receipt_nonce:
        return "receipt_nonce_mismatch"
    if proof.replay.receipt_counter is None:
        return "missing_receipt_counter"
    if (
        expected_min_receipt_counter is not None
        and int(proof.replay.receipt_counter) <= int(expected_min_receipt_counter)
    ):
        return "receipt_counter_replayed"
    if expected_previous_receipt_hash is not None and proof.replay.previous_receipt_hash != str(expected_previous_receipt_hash):
        return "previous_receipt_hash_mismatch"
    if _is_revoked(model.endpoint_id, proof):
        return "revoked_signer"
    transparency = proof.transparency
    if transparency is not None and transparency.status not in {"not_configured", "anchored"}:
        return "invalid_transparency_status"
    return None


def _is_revoked(endpoint_id: str, proof: TrustProof) -> bool:
    revoked_keys = _load_string_set("SEEDCORE_TRUST_REVOKED_KEY_REFS_JSON")
    revoked_nodes = _load_string_set("SEEDCORE_TRUST_REVOKED_NODE_IDS_JSON")
    revoked_ids = _load_string_set("SEEDCORE_TRUST_REVOKED_REVOCATION_IDS_JSON")
    if proof.key_ref in revoked_keys:
        return True
    if endpoint_id in revoked_nodes:
        return True
    if proof.revocation_id and proof.revocation_id in revoked_ids:
        return True
    cutoffs = _load_json_object("SEEDCORE_TRUST_REVOKED_BEFORE_JSON")
    if proof.revocation_id and proof.revocation_id in cutoffs:
        cutoff = cutoffs.get(proof.revocation_id)
        if isinstance(cutoff, int) and proof.replay is not None and proof.replay.receipt_counter is not None:
            return int(proof.replay.receipt_counter) <= cutoff
    return False


def _required_restricted_trust_anchor(endpoint_id: str) -> Optional[str]:
    normalized = endpoint_id.strip().lower()
    if normalized.startswith("hal://"):
        configured = os.getenv("SEEDCORE_RECEIPT_REQUIRED_TRUST_ANCHOR", "tpm2").strip().lower()
        return configured or "tpm2"
    if normalized.startswith("robot_sim://"):
        configured = os.getenv("SEEDCORE_RECEIPT_REQUIRED_TRUST_ANCHOR", "kms").strip().lower()
        return configured or "kms"
    return None


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name, "true" if default else "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _load_string_set(name: str) -> set[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return set()
    try:
        data = json.loads(raw)
    except Exception:
        return set()
    if not isinstance(data, list):
        return set()
    return {str(item).strip() for item in data if str(item).strip()}


def _load_json_object(name: str) -> dict[str, Any]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}
