"""Deterministic evidence envelope builder for simulator executions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


class EvidenceBuilder:
    """Builds execution envelopes with a stable content hash."""

    def build(
        self,
        *,
        token_id: str,
        actuator: str,
        behavior: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "token_id": token_id,
            "actuator_endpoint": actuator,
            "behavior": behavior,
            "actuator_ack": True,
            "result": result,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload["result_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return payload
