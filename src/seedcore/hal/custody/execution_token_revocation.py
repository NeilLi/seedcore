from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from ...database import get_redis_client

EXECUTION_TOKEN_REVOCATION_PREFIX = os.getenv(
    "SEEDCORE_EXECUTION_TOKEN_CRL_PREFIX",
    "seedcore:execution_token:revoked:",
)
EXECUTION_TOKEN_REVOCATION_CUTOFF_KEY = os.getenv(
    "SEEDCORE_EXECUTION_TOKEN_CRL_CUTOFF_KEY",
    "seedcore:execution_token:revoked_before",
)
EXECUTION_TOKEN_CONSUMED_PREFIX = os.getenv(
    "SEEDCORE_EXECUTION_TOKEN_CONSUMED_PREFIX",
    "seedcore:execution_token:consumed:",
)
DEFAULT_EXECUTION_TOKEN_CRL_TTL_SECONDS = 300


def execution_token_crl_ttl_seconds() -> int:
    raw = os.getenv("SEEDCORE_EXECUTION_TOKEN_CRL_TTL_SECONDS", str(DEFAULT_EXECUTION_TOKEN_CRL_TTL_SECONDS)).strip()
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_EXECUTION_TOKEN_CRL_TTL_SECONDS


def get_required_redis_client():
    redis_client = get_redis_client()
    if redis_client is None:
        raise RuntimeError("Redis unavailable for execution token revocation")
    return redis_client


def store_revoked_execution_token(*, token_id: str, ttl_seconds: int) -> bool:
    redis_client = get_required_redis_client()
    key = f"{EXECUTION_TOKEN_REVOCATION_PREFIX}{token_id}"
    return bool(redis_client.setex(key, max(1, ttl_seconds), "1"))


def set_execution_token_revocation_cutoff(issued_before: datetime) -> bool:
    redis_client = get_required_redis_client()
    value = issued_before.astimezone(timezone.utc).isoformat()
    return bool(redis_client.set(EXECUTION_TOKEN_REVOCATION_CUTOFF_KEY, value))


def clear_execution_token_revocation_cutoff() -> bool:
    redis_client = get_required_redis_client()
    return bool(redis_client.delete(EXECUTION_TOKEN_REVOCATION_CUTOFF_KEY))


def parse_optional_iso8601(value: Optional[str]) -> Optional[datetime]:
    if value is None or not value.strip():
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_execution_token_revocation(
    *,
    token_id: str,
    issued_at: datetime,
) -> Optional[str]:
    redis_client = get_redis_client()
    if redis_client is None:
        return None

    if redis_client.exists(f"{EXECUTION_TOKEN_REVOCATION_PREFIX}{token_id}"):
        return "revoked ExecutionToken"
    if redis_client.exists(f"{EXECUTION_TOKEN_CONSUMED_PREFIX}{token_id}"):
        return "replayed ExecutionToken"

    revoked_before = redis_client.get(EXECUTION_TOKEN_REVOCATION_CUTOFF_KEY)
    if isinstance(revoked_before, str) and revoked_before.strip():
        revoked_before_ts = datetime.fromisoformat(revoked_before.replace("Z", "+00:00"))
        if revoked_before_ts.tzinfo is None:
            revoked_before_ts = revoked_before_ts.replace(tzinfo=timezone.utc)
        if issued_at <= revoked_before_ts.astimezone(timezone.utc):
            return "revoked ExecutionToken"
    return None
