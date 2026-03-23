#!/usr/bin/env python3
"""Verify the zero-trust PDP contract against the local SeedCore runtime."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from seedcore.coordinator.core.governance import evaluate_intent
from seedcore.coordinator.core import governance as governance_mod
from seedcore.database import get_async_pg_session_factory


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: dict[str, Any]


TABLES_TO_MONITOR = (
    "tasks",
    "governed_execution_audit",
    "task_outbox",
)


def _api_url(path: str) -> str:
    base = os.getenv("SEEDCORE_API_URL", "http://127.0.0.1:8002").rstrip("/")
    return f"{base}{path}"


def _build_payload(*, active_version: str, intent_id: str, issued_at: datetime, valid_for_seconds: int = 120) -> dict[str, Any]:
    valid_until = issued_at + timedelta(seconds=valid_for_seconds)
    return {
        "task_id": f"task-{intent_id}",
        "type": "action",
        "params": {
            "interaction": {"assigned_agent_id": "agent-1"},
            "resource": {"asset_id": "asset-1"},
            "intent": "transport",
            "governance": {
                "action_intent": {
                    "intent_id": intent_id,
                    "timestamp": issued_at.isoformat(),
                    "valid_until": valid_until.isoformat(),
                    "principal": {
                        "agent_id": "agent-1",
                        "role_profile": "ROBOT_OPERATOR",
                        "session_token": "sess-1",
                    },
                    "action": {
                        "type": "MOVE",
                        "parameters": {},
                        "security_contract": {
                            "hash": "h-runtime-contract",
                            "version": active_version,
                        },
                    },
                    "resource": {
                        "asset_id": "asset-1",
                        "resource_uri": "seedcore://zones/vault-a/assets/asset-1",
                        "target_zone": "vault-a",
                        "provenance_hash": "prov-runtime-contract",
                    },
                }
            },
        },
    }


async def _fetch_table_counts() -> dict[str, int]:
    session_factory = get_async_pg_session_factory()
    counts: dict[str, int] = {}
    async with session_factory() as session:
        for table in TABLES_TO_MONITOR:
            result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
            counts[table] = int(result.scalar_one())
    return counts


def _verify_signature(payload: dict[str, Any], signature: str) -> bool:
    expected = governance_mod._sign_payload(payload)  # noqa: SLF001 - intentional contract verification
    return signature == expected


def _serialize_decision(decision: Any) -> dict[str, Any]:
    return {
        "allowed": bool(decision.allowed),
        "disposition": decision.disposition,
        "deny_code": decision.deny_code,
        "reason": decision.reason,
        "policy_snapshot": decision.policy_snapshot,
        "has_execution_token": decision.execution_token is not None,
        "break_glass_required": bool(decision.break_glass.required),
    }


async def main() -> int:
    results: list[CheckResult] = []

    pkg_status = requests.get(_api_url("/api/v1/pkg/status"), timeout=5).json()
    active_version = str(pkg_status.get("active_version") or "").strip()
    results.append(
        CheckResult(
            "runtime.pkg_active",
            bool(pkg_status.get("available")) and bool(active_version),
            {
                "available": pkg_status.get("available"),
                "active_version": active_version,
                "engine_type": pkg_status.get("engine_type"),
            },
        )
    )

    before_counts = await _fetch_table_counts()

    issued_at = datetime.now(timezone.utc)
    allow_payload = _build_payload(
        active_version=active_version,
        intent_id="intent-runtime-contract-allow",
        issued_at=issued_at,
    )
    deny_payload = _build_payload(
        active_version=active_version,
        intent_id="intent-runtime-contract-deny",
        issued_at=issued_at,
    )
    stale_issued_at = issued_at - timedelta(seconds=2)
    deny_payload["params"]["governance"]["action_intent"]["timestamp"] = stale_issued_at.isoformat()
    deny_payload["params"]["governance"]["action_intent"]["valid_until"] = (stale_issued_at + timedelta(seconds=120)).isoformat()
    os.environ["SEEDCORE_PDP_MAX_INTENT_AGE_MS"] = "500"

    allow_decision = evaluate_intent(allow_payload)
    deny_decision = evaluate_intent(deny_payload)

    token_payload = allow_decision.execution_token.model_dump(mode="json") if allow_decision.execution_token else {}
    token_signature = token_payload.pop("signature", None)
    results.append(
        CheckResult(
            "pdp.single_call_allow_token",
            bool(allow_decision.allowed)
            and allow_decision.execution_token is not None
            and allow_decision.deny_code is None
            and allow_decision.policy_snapshot == active_version
            and bool(token_signature)
            and _verify_signature(token_payload, str(token_signature)),
            {
                **_serialize_decision(allow_decision),
                "token_signature_valid": _verify_signature(token_payload, str(token_signature)) if token_signature else False,
                "token_constraints_keys": sorted((allow_decision.execution_token.constraints or {}).keys()) if allow_decision.execution_token else [],
            },
        )
    )
    results.append(
        CheckResult(
            "pdp.single_call_deny_status",
            (not deny_decision.allowed)
            and deny_decision.execution_token is None
            and bool(deny_decision.deny_code)
            and deny_decision.policy_snapshot == active_version,
            _serialize_decision(deny_decision),
        )
    )

    after_counts = await _fetch_table_counts()
    results.append(
        CheckResult(
            "pdp.no_state_persistence",
            before_counts == after_counts,
            {
                "before": before_counts,
                "after": after_counts,
            },
        )
    )

    failing = [result for result in results if not result.ok]
    for result in results:
        marker = "PASS" if result.ok else "FAIL"
        print(f"[{marker}] {result.name}: {json.dumps(result.detail, sort_keys=True)}")

    if failing:
        print(f"\nZero-trust PDP contract verification failed: {len(failing)} checks failed.", file=sys.stderr)
        return 1

    print("\nZero-trust PDP contract verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
