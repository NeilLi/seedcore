from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .evidence_bundle import SignerMetadata


class MutationReceipt(BaseModel):
    receipt_id: str
    receipt_kind: str
    intent_id: str
    token_id: str
    actor_ref: Optional[str] = None
    target_ref: Optional[str] = None
    payload_hash: str
    executed_at: str
    receipt_counter: int = 1
    previous_receipt_hash: Optional[str] = None
    signature: str
    signer_metadata: SignerMetadata
    snapshot_id: Optional[int] = None
    policy_receipt_id: Optional[str] = None
