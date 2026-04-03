#!/usr/bin/env python3
"""
Verify a custody / RCT audit record satisfies Phase-4 strict triple-hash replay rules.

Reads JSON from stdin (one audit record with policy_receipt + evidence_bundle +
policy_decision). Set SEEDCORE_RCT_REPLAY_STRICT_TRIPLE_HASH=1 in the environment
(or this script sets it) before evaluating.

Exit codes: 0 verified, 2 failed, 1 usage error.
"""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    os.environ.setdefault("SEEDCORE_RCT_REPLAY_STRICT_TRIPLE_HASH", "1")
    from seedcore.ops.evidence.rct_replay_verification import evaluate_strict_rct_replay_triple_hash

    raw = sys.stdin.read()
    if not raw.strip():
        print("Usage: cat record.json | python scripts/host/verify_rct_replay_strict.py", file=sys.stderr)
        return 1
    try:
        record = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"invalid_json:{exc}", file=sys.stderr)
        return 1
    if not isinstance(record, dict):
        print("record_must_be_object", file=sys.stderr)
        return 1
    pr = record.get("policy_receipt") if isinstance(record.get("policy_receipt"), dict) else {}
    eb = record.get("evidence_bundle") if isinstance(record.get("evidence_bundle"), dict) else {}
    result = evaluate_strict_rct_replay_triple_hash(
        record=record,
        policy_receipt=pr,
        evidence_bundle=eb,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
