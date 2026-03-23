#!/usr/bin/env python3
"""Seed governed task records and verify governance/replay surfaces live."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from seedcore.coordinator.dao import GovernedExecutionAuditDAO
from seedcore.database import get_async_pg_session_factory
from seedcore.hal.custody.transition_receipts import build_transition_receipt
from seedcore.models.task import Task, TaskStatus
from seedcore.ops.evidence.verification import build_signed_artifact

COMMIT_TARGETS = [
    "2d4b1b7ab0c531418d5d13e8ba9222bed9ef6b6b",
    "6b60584660cc9555c89486ecfa486a4041163e5e",
    "cdc829f6c3ac787cec6d1a920d2a5c05c1f81db1",
    "eea86719d686946da9c1065fa9c61638cccc8441",
    "6528f938cb57aec60742890916e589d335f36bb4",
    "afe098af3661be92c898e87b09d7e2ee39b8615f",
]

CASES = [
    {
        "slug": "trust-gap-quarantine",
        "type": "query",
        "domain": "governance",
        "description": "Inspect governance trust gaps for stale telemetry quarantine case",
        "asset_id": "asset-trust-gap-1",
        "disposition": "quarantine",
        "reason": "trust_gap_quarantine",
        "trust_gap_codes": ["stale_telemetry"],
    },
    {
        "slug": "trust-gap-summary",
        "type": "query",
        "domain": "governance",
        "description": "Summarize governance trust gaps for custody lineage issues",
        "asset_id": "asset-trust-gap-2",
        "disposition": "quarantine",
        "reason": "trust_gap_quarantine",
        "trust_gap_codes": ["missing_lineage"],
    },
    {
        "slug": "authz-deny",
        "type": "action",
        "domain": "authz",
        "description": "Verify deny path with authz transition receipt persisted to audit trail",
        "asset_id": "asset-deny-1",
        "disposition": "deny",
        "reason": "custody_proof_missing",
        "trust_gap_codes": ["custody_proof_missing"],
    },
    {
        "slug": "authz-allow",
        "type": "action",
        "domain": "authz",
        "description": "Verify allow path with authz graph transition metadata in replay",
        "asset_id": "asset-allow-1",
        "disposition": "allow",
        "reason": "allow_move",
        "trust_gap_codes": [],
    },
]


@dataclass
class SeededCase:
    slug: str
    task_id: str
    audit_id: str
    disposition: str
    trust_gap_codes: list[str]


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: dict[str, Any]


def _url(base_env: str, default: str, path: str) -> str:
    return f"{os.getenv(base_env, default).rstrip('/')}{path}"


def _build_policy_receipt(
    *,
    task_id: str,
    intent_id: str,
    asset_id: str | None,
    disposition: str,
    trust_gap_codes: list[str],
) -> dict[str, Any]:
    payload = {
        "policy_receipt_id": f"policy-{intent_id}",
        "policy_decision_id": f"decision-{intent_id}",
        "task_id": task_id,
        "intent_id": intent_id,
        "policy_version": "pkg@2026-03-23",
        "decision": {"allowed": disposition != "deny", "disposition": disposition},
        "evaluated_rules": ["zone_match", "custody_chain_check"],
        "subject_ref": "agent:test",
        "asset_ref": asset_id,
        "authz_disposition": disposition,
        "governed_receipt_hash": f"receipt-{intent_id}",
        "trust_gap_codes": trust_gap_codes,
        "timestamp": "2026-03-23T07:00:00+00:00",
    }
    _, signer_metadata, signature = build_signed_artifact(
        artifact_type="policy_receipt",
        payload=payload,
    )
    return {
        **payload,
        "signer_metadata": signer_metadata.model_dump(mode="json"),
        "signature": signature,
    }


def _build_evidence_bundle(
    *,
    task_id: str,
    intent_id: str,
    token_id: str,
    transition_receipts: list[dict[str, Any]],
    asset_id: str | None,
) -> dict[str, Any]:
    payload = {
        "evidence_bundle_id": f"bundle-{intent_id}",
        "task_id": task_id,
        "intent_id": intent_id,
        "intent_ref": None,
        "execution_token_id": token_id,
        "policy_receipt_id": f"policy-{intent_id}",
        "transition_receipt_ids": [item["transition_receipt_id"] for item in transition_receipts],
        "asset_fingerprint": {
            "fingerprint_id": f"fingerprint-{intent_id}",
            "fingerprint_hash": f"hash-{intent_id}",
            "modality_map": {"visual_hash": f"visual-{intent_id}"},
            "derivation_logic": {"algorithm": "sha256"},
            "capture_context": {"asset_id": asset_id} if asset_id else {},
            "hardware_witness": {"node_id": "robot_sim://unit-1"},
            "captured_at": "2026-03-23T07:03:00+00:00",
        },
        "evidence_inputs": {
            "execution_summary": {
                "intent_id": intent_id,
                "task_id": task_id,
                "execution_token_id": token_id,
                "executed_at": "2026-03-23T07:02:00+00:00",
                "actuator_endpoint": "robot_sim://unit-1",
                "actuator_result_hash": "actuator-hash",
                "transition_receipt_ids": [item["transition_receipt_id"] for item in transition_receipts],
                "node_id": "robot_sim://unit-1",
            },
            "transition_receipts": transition_receipts,
        },
        "telemetry_refs": [
            {
                "kind": "telemetry_snapshot",
                "inline": {
                    "zone_checks": {"target_zone": "vault-a", "current_zone": "staging-a"},
                    "vision": [{"label": "sealed_box"}],
                },
            }
        ],
        "media_refs": [{"kind": "image", "uri": "s3://bucket/proof.jpg", "sha256": "media-sha"}],
        "node_id": "robot_sim://unit-1",
        "created_at": "2026-03-23T07:03:00+00:00",
    }
    _, signer_metadata, signature = build_signed_artifact(
        artifact_type="evidence_bundle",
        payload=payload,
        endpoint_id="robot_sim://unit-1",
        trust_level="attested",
        node_id="robot_sim://unit-1",
    )
    return {
        **payload,
        "signer_metadata": signer_metadata.model_dump(mode="json"),
        "signature": signature,
    }


def _build_audit_record(
    *,
    task_id: str,
    intent_id: str,
    asset_id: str | None,
    disposition: str,
    reason: str,
    trust_gap_codes: list[str],
) -> dict[str, Any]:
    token_id = f"token-{intent_id}"
    transition_receipt = build_transition_receipt(
        intent_id=intent_id,
        token_id=token_id,
        actuator_endpoint="robot_sim://unit-1",
        hardware_uuid="robot-1",
        actuator_result_hash="actuator-hash",
        from_zone="staging-a",
        to_zone="vault-a",
        target_zone="vault-a",
        executed_at="2026-03-23T07:01:00+00:00",
        receipt_nonce=f"nonce-{intent_id}",
    )
    return {
        "task_id": task_id,
        "record_type": "execution_receipt",
        "intent_id": intent_id,
        "token_id": token_id,
        "policy_snapshot": "pkg@2026-03-23",
        "policy_decision": {
            "allowed": disposition != "deny",
            "disposition": disposition,
            "authz_graph": {
                "mode": "transition_evaluation",
                "disposition": disposition,
                "reason": reason,
                "asset_ref": asset_id,
                "resource_ref": f"seedcore://zones/vault-a/assets/{asset_id}" if asset_id else None,
                "current_custodian": "principal:agent:test",
                "restricted_token_recommended": disposition == "quarantine",
                "trust_gaps": [
                    {"code": code, "message": f"Gap detected: {code}", "details": {}}
                    for code in trust_gap_codes
                ],
            },
            "governed_receipt": {
                "decision_hash": f"receipt-{intent_id}",
                "disposition": disposition,
                "snapshot_ref": "authz_graph@snapshot:1",
                "snapshot_id": "snapshot:1",
                "snapshot_version": "snapshot:1",
                "principal_ref": "principal:agent:test",
                "operation": "MOVE",
                "asset_ref": asset_id,
                "resource_ref": f"seedcore://zones/vault-a/assets/{asset_id}" if asset_id else None,
                "twin_ref": f"asset:{asset_id}" if asset_id else None,
                "reason": reason,
                "generated_at": "2026-03-23T07:00:00+00:00",
                "custody_proof": ["custody:handoff-1", "custody:handoff-2"],
                "evidence_refs": ["telemetry:temp-1"],
                "trust_gap_codes": trust_gap_codes,
                "provenance_sources": ["tracking_event:telemetry-1"],
                "advisory": {"evidence_quality_score": 0.73},
            },
        },
        "action_intent": {"intent_id": intent_id, "resource": {"asset_id": asset_id} if asset_id else {}},
        "policy_case": {},
        "policy_receipt": _build_policy_receipt(
            task_id=task_id,
            intent_id=intent_id,
            asset_id=asset_id,
            disposition=disposition,
            trust_gap_codes=trust_gap_codes,
        ),
        "evidence_bundle": _build_evidence_bundle(
            task_id=task_id,
            intent_id=intent_id,
            token_id=token_id,
            transition_receipts=[transition_receipt],
            asset_id=asset_id,
        ),
        "actor_agent_id": "agent:test",
        "actor_organ_id": "organ:test",
    }


async def _seed_cases() -> list[SeededCase]:
    session_factory = get_async_pg_session_factory()
    dao = GovernedExecutionAuditDAO()
    seeded: list[SeededCase] = []
    async with session_factory() as session:
        for case in CASES:
            task = Task(
                id=uuid.uuid4(),
                type=case["type"],
                domain=case["domain"],
                description=case["description"],
                params={
                    "routing": {"priority": "normal"},
                    "verification_case": case["slug"],
                    "commit_targets": COMMIT_TARGETS,
                },
                status=TaskStatus.COMPLETED,
                attempts=1,
                snapshot_id=1,
                result={
                    "status": "ok",
                    "verification_case": case["slug"],
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            session.add(task)
            await session.flush()
            intent_id = f"intent-{case['slug']}-{str(task.id)[:8]}"
            record = _build_audit_record(
                task_id=str(task.id),
                intent_id=intent_id,
                asset_id=case["asset_id"],
                disposition=case["disposition"],
                reason=case["reason"],
                trust_gap_codes=list(case["trust_gap_codes"]),
            )
            appended = await dao.append_record(
                session,
                task_id=record["task_id"],
                record_type=record["record_type"],
                intent_id=record["intent_id"],
                token_id=record["token_id"],
                policy_snapshot=record["policy_snapshot"],
                policy_decision=record["policy_decision"],
                action_intent=record["action_intent"],
                policy_case=record["policy_case"],
                policy_receipt=record["policy_receipt"],
                evidence_bundle=record["evidence_bundle"],
                actor_agent_id=record["actor_agent_id"],
                actor_organ_id=record["actor_organ_id"],
            )
            seeded.append(
                SeededCase(
                    slug=case["slug"],
                    task_id=str(task.id),
                    audit_id=appended["entry_id"],
                    disposition=case["disposition"],
                    trust_gap_codes=list(case["trust_gap_codes"]),
                )
            )
        await session.commit()
    return seeded


def _get_json(url: str, *, params: dict[str, Any] | None = None, timeout: float = 10.0) -> dict[str, Any]:
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _find_case(seeded: list[SeededCase], slug: str) -> SeededCase:
    for case in seeded:
        if case.slug == slug:
            return case
    raise KeyError(f"Missing seeded case for slug={slug}")


def _check(name: str, ok: bool, detail: dict[str, Any]) -> CheckResult:
    return CheckResult(name=name, ok=ok, detail=detail)


def _run_checks(seeded: list[SeededCase]) -> list[CheckResult]:
    base = os.getenv("SEEDCORE_API_URL", "http://127.0.0.1:8002").rstrip("/")
    quarantine_case = _find_case(seeded, "trust-gap-quarantine")
    deny_case = _find_case(seeded, "authz-deny")

    search_stale = _get_json(
        f"{base}/api/v1/governance/search",
        params={"disposition": "quarantine", "trust_gap_code": "stale_telemetry", "current_only": "true"},
    )
    search_quarantine = _get_json(
        f"{base}/api/v1/governance/search",
        params={"disposition": "quarantine", "current_only": "true"},
    )
    task_governance = _get_json(f"{base}/api/v1/tasks/{quarantine_case.task_id}/governance")
    task_deny_governance = _get_json(f"{base}/api/v1/tasks/{deny_case.task_id}/governance")
    replay_artifacts = _get_json(
        f"{base}/api/v1/replay/artifacts",
        params={"audit_id": quarantine_case.audit_id, "projection": "internal"},
    )
    custody_event = _get_json(
        f"{base}/api/v1/governance/materialized-custody-event",
        params={"audit_id": quarantine_case.audit_id},
    )

    checks = [
        _check(
            "governance.search_stale",
            search_stale.get("total") == 1
            and search_stale.get("items", [{}])[0].get("task_id") == quarantine_case.task_id
            and search_stale.get("facets", {}).get("trust_gap_codes") == [{"value": "stale_telemetry", "count": 1}],
            {
                "total": search_stale.get("total"),
                "facets": search_stale.get("facets"),
                "first_summary": search_stale.get("items", [{}])[0].get("authz_transition_summary"),
            },
        ),
        _check(
            "governance.search_quarantine",
            search_quarantine.get("total") >= 2
            and {"value": "missing_lineage", "count": 1} in search_quarantine.get("facets", {}).get("trust_gap_codes", [])
            and {"value": "stale_telemetry", "count": 1} in search_quarantine.get("facets", {}).get("trust_gap_codes", []),
            {
                "total": search_quarantine.get("total"),
                "facets": search_quarantine.get("facets"),
            },
        ),
        _check(
            "tasks.quarantine_governance",
            task_governance.get("latest", {}).get("authz_transition_summary", {}).get("trust_gap_codes") == ["stale_telemetry"],
            {
                "task_id": quarantine_case.task_id,
                "latest": task_governance.get("latest", {}).get("authz_transition_summary"),
            },
        ),
        _check(
            "tasks.deny_governance",
            task_deny_governance.get("latest", {}).get("authz_transition_summary", {}).get("disposition") == "deny",
            {
                "task_id": deny_case.task_id,
                "latest": task_deny_governance.get("latest", {}).get("authz_transition_summary"),
            },
        ),
        _check(
            "replay.artifacts",
            replay_artifacts.get("verification_status", {}).get("verified") is True
            and replay_artifacts.get("policy_receipt", {}).get("governed_receipt_hash")
            == f"receipt-intent-trust-gap-quarantine-{quarantine_case.task_id[:8]}",
            {
                "policy_receipt_hash": replay_artifacts.get("policy_receipt", {}).get("governed_receipt_hash"),
                "trust_gap_codes": replay_artifacts.get("policy_receipt", {}).get("trust_gap_codes"),
                "verified": replay_artifacts.get("verification_status", {}).get("verified"),
            },
        ),
        _check(
            "governance.materialized_custody_event",
            custody_event.get("custody_event_jsonld", {}).get("@type") == "seedcore:SeedCoreCustodyEvent",
            {
                "event_type": custody_event.get("custody_event_jsonld", {}).get("@type"),
                "retrieval_value": custody_event.get("retrieval_value"),
            },
        ),
    ]
    return checks


def main() -> int:
    seeded = asyncio.run(_seed_cases())
    checks = _run_checks(seeded)

    print("==> Seeded cases")
    print(json.dumps([asdict(item) for item in seeded], indent=2))
    print("\n==> Verification")
    for result in checks:
        marker = "PASS" if result.ok else "FAIL"
        print(f"[{marker}] {result.name}: {json.dumps(result.detail, sort_keys=True)}")

    failures = [result for result in checks if not result.ok]
    if failures:
        print(f"\nGovernance verification failed: {len(failures)} check(s) failed.", file=sys.stderr)
        return 1

    print("\nGovernance verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
