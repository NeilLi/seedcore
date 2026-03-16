"""Execution token primitive for simulator governance checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class ExecutionToken:
    """Simple governance token with status and optional expiry."""

    id: str
    status: str = "active"
    valid_until: datetime | None = None

    def is_valid(self) -> bool:
        if self.status != "active":
            return False
        if self.valid_until is None:
            return True
        return datetime.now(timezone.utc) <= self.valid_until.astimezone(timezone.utc)
