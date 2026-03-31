from __future__ import annotations

import json
from pathlib import Path

from seedcore.ops.evidence.owner_context import owner_context_hash


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_golden_cases() -> list[dict]:
    payload = json.loads(
        (REPO_ROOT / "tests" / "fixtures" / "owner_context_hash" / "golden.json").read_text()
    )
    return list(payload.get("cases") or [])


def test_owner_context_hash_matches_golden_vectors() -> None:
    for case in _load_golden_cases():
        computed = owner_context_hash(case["owner_context_ref"])
        assert computed == case["expected_hash"], case["name"]
