from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

from seedcore.models.mutation_receipt import MutationReceipt
from seedcore.ops.evidence.policy import canonical_json, sha256_hex
from seedcore.ops.evidence.verification import (
    build_signed_artifact,
    verify_artifact_signature_result,
)


class MutationReceiptService:
    def build_signed_receipt(
        self,
        *,
        receipt_kind: str,
        intent_id: str,
        token_id: str,
        actor_ref: Optional[str],
        target_ref: Optional[str],
        mutation_payload: Mapping[str, Any],
        snapshot_id: Optional[int] = None,
        policy_receipt_id: Optional[str] = None,
        receipt_id: Optional[str] = None,
        executed_at: Optional[str] = None,
        previous_receipt_hash: Optional[str] = None,
        previous_receipt_counter: Optional[int] = None,
    ) -> Dict[str, Any]:
        if not str(intent_id or "").strip():
            raise ValueError("intent_id is required")
        if not str(token_id or "").strip():
            raise ValueError("token_id is required")
        kind = str(receipt_kind or "").strip()
        if not kind:
            raise ValueError("receipt_kind is required")

        payload_hash = sha256_hex(canonical_json(dict(mutation_payload or {})))
        counter = int(previous_receipt_counter or 0) + 1
        payload = {
            "receipt_id": str(receipt_id or uuid.uuid4()),
            "receipt_kind": kind,
            "intent_id": str(intent_id),
            "token_id": str(token_id),
            "actor_ref": str(actor_ref) if actor_ref is not None else None,
            "target_ref": str(target_ref) if target_ref is not None else None,
            "payload_hash": payload_hash,
            "executed_at": executed_at or datetime.now(timezone.utc).isoformat(),
            "receipt_counter": counter,
            "previous_receipt_hash": str(previous_receipt_hash) if previous_receipt_hash else None,
            "snapshot_id": int(snapshot_id) if snapshot_id is not None else None,
            "policy_receipt_id": str(policy_receipt_id) if policy_receipt_id is not None else None,
        }
        _signed_payload_hash, signer_metadata, signature, _trust_proof = build_signed_artifact(
            artifact_type="mutation_receipt",
            payload=dict(payload),
            node_id=target_ref,
            endpoint_id=target_ref,
            trust_level="baseline",
            workflow_type=kind,
            disposition=None,
            receipt_nonce=payload["receipt_id"],
            previous_receipt_hash=previous_receipt_hash,
            previous_receipt_counter=previous_receipt_counter,
            transparency_enabled=False,
        )
        return MutationReceipt(
            **payload,
            signer_metadata=signer_metadata,
            signature=signature,
        ).model_dump(mode="json")

    def verify_signed_receipt(
        self,
        receipt: Mapping[str, Any] | MutationReceipt,
    ) -> Dict[str, Any]:
        try:
            model = receipt if isinstance(receipt, MutationReceipt) else MutationReceipt(**dict(receipt))
        except Exception:
            return {"artifact_type": "mutation_receipt", "verified": False, "error": "invalid_mutation_receipt"}
        payload = model.model_dump(
            mode="json",
            exclude={"signature", "signer_metadata"},
        )
        return verify_artifact_signature_result(
            artifact_type="mutation_receipt",
            payload=payload,
            signer_metadata=model.signer_metadata,
            signature=model.signature,
            endpoint_id=model.target_ref,
            trust_level="baseline",
            attested=False,
            trust_proof=None,
        )


mutation_receipt_service = MutationReceiptService()
