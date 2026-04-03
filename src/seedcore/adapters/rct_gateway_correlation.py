from __future__ import annotations

import uuid
from typing import Any, Dict, Mapping


def build_rct_gateway_to_replay_correlation(
    *,
    request_id: str,
    gateway_evaluate_response: Mapping[str, Any],
) -> Dict[str, Any]:
    """
    Stable correlation contract for RCT.

    Contract guarantee used by this slice:
    - gateway `request_id` is mapped deterministically to hot-path `intent_id`
      (via the existing Agent Action Gateway mapping).

    This helper returns replay lookup keys that clients can use with:
    - `GET /api/v1/replay?intent_id=...` (works for any string `request_id`)
    - `GET /api/v1/replay?audit_id=...` (requires UUID-shaped `audit_id`)
    """
    req_id = str(request_id).strip()
    if not req_id:
        raise ValueError("request_id must be non-empty")

    governed_receipt = gateway_evaluate_response.get("governed_receipt")
    if not isinstance(governed_receipt, Mapping):
        governed_receipt = {}

    raw_audit_id = str(governed_receipt.get("audit_id") or "").strip()
    audit_id_source = "governed_receipt"
    try:
        audit_id = str(uuid.UUID(raw_audit_id))
    except ValueError:
        # Keep fallback deterministic but UUID-safe so /replay?audit_id does not fail shape validation.
        audit_id = str(uuid.uuid5(uuid.NAMESPACE_URL, req_id))
        audit_id_source = "deterministic_fallback"

    forensic_linkage = gateway_evaluate_response.get("forensic_linkage")
    forensic_linkage = forensic_linkage if isinstance(forensic_linkage, Mapping) else {}
    forensic_block_id = forensic_linkage.get("forensic_block_id")

    replay_status = "ready_for_lookup" if audit_id_source == "governed_receipt" else "pending_replay_record"

    return {
        "request_id": req_id,
        "intent_id": req_id,
        "workflow_join_key": audit_id,
        "audit_id": audit_id,
        "audit_id_source": audit_id_source,
        "forensic_block_id": forensic_block_id,
        "replay_state": {
            "status": replay_status,
            "reason": (
                "governed_receipt_audit_id_present"
                if audit_id_source == "governed_receipt"
                else "governed_receipt_audit_id_missing"
            ),
        },
        "replay_lookup": {
            "intent_id": req_id,
            "audit_id": audit_id,
            "preferred_key": "audit_id" if audit_id_source == "governed_receipt" else "intent_id",
            # Convenience: callers can choose either key.
        },
    }

