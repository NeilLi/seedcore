from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field  # pyright: ignore[reportMissingImports]


class ExecutionReceipt(BaseModel):
    receipt_id: str
    proof_type: str = "hmac_sha256"
    signature: str
    payload_hash: str
    actuator_endpoint: Optional[str] = None
    actuator_result_hash: Optional[str] = None


class EvidenceBundle(BaseModel):
    intent_ref: str
    executed_at: str
    telemetry_snapshot: Dict[str, Any] = Field(default_factory=dict)
    execution_receipt: ExecutionReceipt

