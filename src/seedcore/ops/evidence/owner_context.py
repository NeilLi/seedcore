from __future__ import annotations

from typing import Any, Mapping, Optional

from seedcore.ops.evidence.policy import canonical_json, sha256_hex


def owner_context_hash(owner_context_ref: Mapping[str, Any] | None) -> Optional[str]:
    if not owner_context_ref:
        return None
    return f"sha256:{sha256_hex(canonical_json(dict(owner_context_ref)))}"
