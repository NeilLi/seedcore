#!/usr/bin/env python3
"""Verify delegated-intent ingress cannot bypass the agent-actions runtime boundary."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from seedcore.infra.kafka.delegated_intent import (  # noqa: E402
    DelegatedIntentPayload,
    build_delegated_intent_envelope,
)
from seedcore.infra.kafka.intent_ingress import process_delegated_intent_event  # noqa: E402


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: dict[str, Any]


class RecordingTransport(httpx.AsyncBaseTransport):
    """Record request paths while forwarding to real HTTP transport."""

    def __init__(self) -> None:
        self.paths: list[str] = []
        self._inner = httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def _gateway_request(*, request_id: str, idempotency_key: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "contract_version": "seedcore.agent_action_gateway.v1",
        "request_id": request_id,
        "requested_at": now.isoformat(),
        "idempotency_key": idempotency_key,
        "policy_snapshot_ref": "snapshot:pkg-delegated-local-v1",
        "principal": {
            "agent_id": "agent:openai-assistant-01",
            "role_profile": "TRANSFER_COORDINATOR",
            "session_token": "session-local-123",
            "owner_id": "did:seedcore:owner:abc",
            "delegation_ref": "delegation:deleg-local-001",
            "hardware_fingerprint": {
                "fingerprint_id": "hw-fp-local-001",
                "public_key_fingerprint": "pk-fp-local-001",
            },
        },
        "workflow": {
            "type": "restricted_custody_transfer",
            "action_type": "TRANSFER_CUSTODY",
            "valid_until": (now + timedelta(minutes=5)).isoformat(),
        },
        "asset": {
            "asset_id": "asset:lot-local-8841",
            "product_ref": "product:sku-local-8841",
            "from_custodian_ref": "principal:facility_mgr_001",
            "to_custodian_ref": "principal:outbound_mgr_002",
            "from_zone": "vault_a",
            "to_zone": "handoff_bay_3",
            "provenance_hash": "sha256:asset-proof-local-8841",
            "declared_value_usd": 1200.0,
        },
        "approval": {
            "approval_envelope_id": "approval-transfer-local-001",
        },
        "authority_scope": {
            "scope_id": "scope-transfer-local-001",
            "asset_ref": "asset:lot-local-8841",
            "product_ref": "product:sku-local-8841",
            "facility_ref": "facility:bangkok-01",
            "expected_from_zone": "vault_a",
            "expected_to_zone": "handoff_bay_3",
        },
        "telemetry": {
            "observed_at": now.isoformat(),
            "freshness_seconds": 5,
            "max_allowed_age_seconds": 60,
            "current_zone": "vault_a",
            "evidence_refs": ["evidence:telemetry-local-001"],
        },
        "security_contract": {
            "hash": "sha256:security-contract-local-001",
            "version": "rules@transfer-v1",
        },
        "options": {
            "debug": False,
            "no_execute": True,
        },
    }


def _delegated_payload(*, request_id: str, idempotency_key: str) -> dict[str, Any]:
    return {
        "stream": "intent",
        "payload_schema_version": "seedcore.intent.delegated.v0",
        "request_id": request_id,
        "workflow_id": "wf-kafka-delegated-local-001",
        "correlation_id": "corr-kafka-delegated-local-001",
        "assistant_namespace": "openai-agents",
        "owner_context_preflight": {
            "owner_id": "did:seedcore:owner:abc",
            "assistant_id": "agent:openai-assistant-01",
            "delegation_id": "deleg-local-001",
            "declared_value_usd": 1200.0,
            "required_modalities": ["telemetry"],
            "available_modalities": ["telemetry"],
            "observed_provenance_level": "verified",
            "risk_score": 0.1,
        },
        "gateway_request": _gateway_request(request_id=request_id, idempotency_key=idempotency_key),
    }


async def _run_live_ingress_probe(api_base: str) -> tuple[dict[str, Any], list[str]]:
    os.environ["SEEDCORE_API"] = api_base.rstrip("/")
    os.environ["SEEDCORE_KAFKA_INTENT_INGRESS_PREFLIGHT_REQUIRED"] = "0"
    os.environ["SEEDCORE_KAFKA_INTENT_INGRESS_NO_EXECUTE"] = "1"

    request_id = f"req-kafka-delegated-local-{uuid.uuid4().hex[:12]}"
    idempotency_key = f"idem-kafka-delegated-local-{uuid.uuid4().hex[:12]}"
    payload = DelegatedIntentPayload.model_validate(
        _delegated_payload(request_id=request_id, idempotency_key=idempotency_key)
    )
    event = build_delegated_intent_envelope(payload, producer="seedcore-ingress-boundary-check")

    transport = RecordingTransport()
    async with httpx.AsyncClient(transport=transport, timeout=15.0) as client:
        result = await process_delegated_intent_event(event, http_client=client)
    return result, transport.paths


def _contains_only_expected_paths(paths: list[str]) -> bool:
    expected_paths = {
        "/api/v1/owner-context/preflight",
        "/api/v1/agent-actions/evaluate",
    }
    return set(paths).issubset(expected_paths) and "/api/v1/agent-actions/evaluate" in paths


def _legacy_bypass_detected(paths: list[str]) -> bool:
    return any(path == "/api/v1/intents/submit-signed" for path in paths)


def _source_anchor_present() -> bool:
    target = PROJECT_ROOT / "src/seedcore/infra/kafka/intent_ingress.py"
    content = target.read_text(encoding="utf-8")
    return re.search(r"/api/v1/agent-actions/evaluate", content) is not None


def _source_legacy_bypass_absent() -> bool:
    target = PROJECT_ROOT / "src/seedcore/infra/kafka/intent_ingress.py"
    content = target.read_text(encoding="utf-8")
    return re.search(r"/api/v1/intents/submit-signed", content) is None


async def _main_async() -> int:
    api_base = os.getenv("SEEDCORE_API_URL", "http://127.0.0.1:8002").rstrip("/")
    checks: list[CheckResult] = []

    health_ok = False
    health_payload: dict[str, Any] = {}
    try:
        response = httpx.get(f"{api_base}/health", timeout=5.0)
        health_payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        health_ok = response.status_code == 200
    except Exception as exc:  # noqa: BLE001
        health_payload = {"error": type(exc).__name__}

    checks.append(
        CheckResult(
            "ingress.runtime_health",
            health_ok,
            {"api_base": api_base, "body": health_payload},
        )
    )

    checks.append(
        CheckResult(
            "ingress.source_anchor_agent_actions",
            _source_anchor_present(),
            {"file": "src/seedcore/infra/kafka/intent_ingress.py"},
        )
    )
    checks.append(
        CheckResult(
            "ingress.source_has_no_legacy_signed_intent_bypass",
            _source_legacy_bypass_absent(),
            {"file": "src/seedcore/infra/kafka/intent_ingress.py"},
        )
    )

    if health_ok:
        try:
            result, paths = await _run_live_ingress_probe(api_base)
            checks.append(
                CheckResult(
                    "ingress.live_calls_only_expected_paths",
                    _contains_only_expected_paths(paths),
                    {"paths": paths},
                )
            )
            checks.append(
                CheckResult(
                    "ingress.live_no_legacy_bypass_path",
                    not _legacy_bypass_detected(paths),
                    {"paths": paths},
                )
            )
            checks.append(
                CheckResult(
                    "ingress.live_result_has_evaluation_status",
                    str(result.get("status") or "").strip().lower() in {"evaluated", "rejected_preflight"},
                    {"result_status": result.get("status"), "request_id": result.get("request_id")},
                )
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(
                CheckResult(
                    "ingress.live_probe_execution",
                    False,
                    {"error": type(exc).__name__, "message": str(exc)},
                )
            )

    failures = [item for item in checks if not item.ok]
    for item in checks:
        marker = "PASS" if item.ok else "FAIL"
        print(f"[{marker}] {item.name}: {json.dumps(item.detail, sort_keys=True)}")

    if failures:
        print(
            f"\nKafka ingress non-bypass verification failed: {len(failures)} checks failed.",
            file=sys.stderr,
        )
        return 1

    print("\nKafka ingress non-bypass verification passed.")
    return 0


def main() -> int:
    return asyncio.run(_main_async())


if __name__ == "__main__":
    raise SystemExit(main())
