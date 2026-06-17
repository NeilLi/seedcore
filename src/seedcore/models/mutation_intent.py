from __future__ import annotations

import base64
from datetime import datetime
from typing import List
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MutationIntent(BaseModel):
    """Envelope modeling changes to the governance / policy infrastructure itself."""

    model_config = ConfigDict(extra="forbid")

    mutation_id: UUID
    proposing_agent_id: str
    target_graph_version: str
    delta_payload_sha256: str  # Hash of the proposed graph/policy change
    rationale_inference_hash: str  # Link to the agent's diagnostic trace
    timestamp: datetime
    signer_chain: List[str] = Field(default_factory=list)

    @field_validator(
        "proposing_agent_id",
        "target_graph_version",
        "delta_payload_sha256",
        "rationale_inference_hash",
    )
    @classmethod
    def _non_empty_string(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized


class CoSignedPromotionReceipt(BaseModel):
    """Evidence-bound receipt for administrative or hardware co-signing."""

    model_config = ConfigDict(extra="forbid")

    mutation_id: UUID
    target_graph_version: str
    target_graph_snapshot_hash: str
    approver_admin_id: str
    approver_signer_key_ref: str
    signature_b64: str
    timestamp: datetime

    @field_validator(
        "target_graph_version",
        "target_graph_snapshot_hash",
        "approver_admin_id",
        "approver_signer_key_ref",
        "signature_b64",
    )
    @classmethod
    def _non_empty_string(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("signature_b64")
    @classmethod
    def _signature_is_base64_material(cls, value: str) -> str:
        try:
            decoded = base64.b64decode(value.encode("ascii"), validate=True)
        except Exception as exc:
            raise ValueError("signature_b64 must contain valid base64 material") from exc
        if len(decoded) < 32:
            raise ValueError("signature_b64 must decode to at least 32 bytes")
        return value
