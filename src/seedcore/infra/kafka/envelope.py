from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

STREAM_ENVELOPE_SCHEMA_VERSION = "seedcore.stream.envelope.v0"


def build_stream_envelope(
    payload: Mapping[str, Any],
    *,
    producer: str,
    schema_version: str = STREAM_ENVELOPE_SCHEMA_VERSION,
    event_id: str | None = None,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    """
    JSON envelope convention (Phase 1):
    event_id, occurred_at, schema_version, payload, producer.
    """
    ts = occurred_at or datetime.now(timezone.utc)
    return {
        "event_id": event_id or str(uuid4()),
        "occurred_at": ts.isoformat(),
        "schema_version": schema_version,
        "payload": dict(payload),
        "producer": producer,
    }
