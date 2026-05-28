#!/usr/bin/env python3
"""Generate local runtime-backed RCT audit rows for verification-surface sign-off."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import httpx
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from seedcore.adapters.rct_agent_action_gateway_reference_adapter import (  # noqa: E402
    build_rct_agent_action_evaluate_request_v1,
)


DEFAULT_POLICY_SNAPSHOT_REF = "runtime-baseline-v1.0.0-local-rct-verification"


class RuntimeRctAuditError(RuntimeError):
    """Raised when the local RCT audit generator cannot produce a replayable row."""


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_run_id(*, prefix: str, index: int) -> str:
    normalized = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in prefix.strip())
    normalized = normalized.strip("-_") or "local-rct"
    return f"{normalized}-{index:03d}"


def build_evaluate_payload(
    *,
    run_id: str,
    policy_snapshot_ref: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    base_time = now or datetime.now(timezone.utc)
    request_id = f"req-{run_id}"
    asset_id = f"asset:{run_id}"
    return build_rct_agent_action_evaluate_request_v1(
        request_id=request_id,
        idempotency_key=f"idem-{run_id}",
        requested_at=_utc_iso(base_time),
        policy_snapshot_ref=policy_snapshot_ref,
        principal={
            "agent_id": "agent:custody_runtime_01",
            "role_profile": "TRANSFER_COORDINATOR",
            "session_token": f"session-{run_id}",
            "owner_id": "did:seedcore:owner:local-rct-verification",
            "delegation_ref": f"delegation:{run_id}",
            "organization_ref": "org:warehouse-north",
            "hardware_fingerprint": {
                "fingerprint_id": f"fp:{run_id}",
                "node_id": "node:local-rct-sim",
                "public_key_fingerprint": _stable_hash(f"hardware:{run_id}"),
                "attestation_type": "local_sim",
                "key_ref": f"local-sim:{run_id}",
            },
        },
        workflow_valid_until=_utc_iso(base_time + timedelta(minutes=5)),
        asset_base={
            "asset_id": asset_id,
            "lot_id": f"lot-{run_id}",
            "from_custodian_ref": "principal:facility_mgr_001",
            "to_custodian_ref": "principal:outbound_mgr_002",
            "from_zone": "vault_a",
            "to_zone": "handoff_bay_3",
            "provenance_hash": _stable_hash(f"asset-provenance:{run_id}"),
        },
        approval_envelope_id=f"approval-{run_id}",
        approval_expected_envelope_version="1",
        authority_scope_base={
            "scope_id": f"scope:{run_id}",
            "asset_ref": asset_id,
            "expected_from_zone": "vault_a",
            "expected_to_zone": "handoff_bay_3",
            "expected_coordinate_ref": "local-sim://warehouse/shelf/A3",
        },
        telemetry={
            "observed_at": _utc_iso(base_time - timedelta(seconds=2)),
            "freshness_seconds": 2,
            "max_allowed_age_seconds": 300,
            "current_zone": "vault_a",
            "current_coordinate_ref": "local-sim://warehouse/shelf/A3",
            "evidence_refs": [
                f"origin_scan:{run_id}",
                f"delivery_scan:{run_id}",
                f"signed_edge_telemetry:{run_id}",
            ],
        },
        security_contract={
            "hash": _stable_hash(f"security-contract:{run_id}"),
            "version": "rules@8.0.0",
        },
        shopify_sandbox_transaction={
            "product_ref": "shopify:gid://shopify/Product/1234567890",
            "order_ref": f"shopify:gid://shopify/Order/{run_id}",
            "quote_ref": f"shopify:quote:{run_id}",
            "declared_value_usd": 1500,
            "economic_hash": _stable_hash(f"commerce:{run_id}"),
        },
        options={"debug": False},
    )


def build_closure_payload(
    *,
    run_id: str,
    evaluate_payload: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    base_time = now or datetime.now(timezone.utc)
    request_id = str(evaluate_payload["request_id"])
    asset = evaluate_payload.get("asset") if isinstance(evaluate_payload.get("asset"), Mapping) else {}
    return {
        "contract_version": "seedcore.agent_action_gateway.v1",
        "request_id": request_id,
        "closure_id": f"closure-{run_id}",
        "idempotency_key": f"idem-closure-{run_id}",
        "closed_at": _utc_iso(base_time + timedelta(seconds=30)),
        "outcome": "completed",
        "evidence_bundle_id": f"evidence-bundle-{run_id}",
        "transition_receipt_ids": [f"transition-receipt-{run_id}"],
        "node_id": "node:local-rct-sim",
        "forensic_block": {
            "forensic_block_id": f"fb-{run_id}",
            "fingerprint_components": {
                "economic_hash": _stable_hash(f"economic:{run_id}"),
                "physical_presence_hash": _stable_hash(f"physical:{run_id}"),
                "reasoning_hash": _stable_hash(f"reasoning:{run_id}"),
                "actuator_hash": _stable_hash(f"actuator:{run_id}"),
            },
            "current_coordinate_ref": "local-sim://warehouse/handoff_bay_3/A3",
            "current_zone": "handoff_bay_3",
        },
        "summary": {
            "settlement_target": asset.get("asset_id"),
            "local_simulation": True,
        },
    }


def build_approval_envelope(
    *,
    run_id: str,
    evaluate_payload: Mapping[str, Any],
    policy_snapshot_ref: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    base_time = now or datetime.now(timezone.utc)
    asset = evaluate_payload.get("asset") if isinstance(evaluate_payload.get("asset"), Mapping) else {}
    approval = evaluate_payload.get("approval") if isinstance(evaluate_payload.get("approval"), Mapping) else {}
    principal = evaluate_payload.get("principal") if isinstance(evaluate_payload.get("principal"), Mapping) else {}
    return {
        "approval_envelope_id": str(approval.get("approval_envelope_id") or f"approval-{run_id}"),
        "workflow_type": "custody_transfer",
        "status": "APPROVED",
        "asset_ref": asset.get("asset_id"),
        "lot_id": asset.get("lot_id"),
        "from_custodian_ref": asset.get("from_custodian_ref"),
        "to_custodian_ref": asset.get("to_custodian_ref"),
        "transfer_context": {
            "from_zone": asset.get("from_zone"),
            "to_zone": asset.get("to_zone"),
            "facility_ref": principal.get("organization_ref") or "facility:local-rct",
            "custody_point_ref": "custody_point:handoff_bay_3",
        },
        "required_approvals": [
            {
                "role": "FACILITY_MANAGER",
                "principal_ref": "principal:facility_mgr_001",
                "status": "APPROVED",
                "approved_at": _utc_iso(base_time - timedelta(seconds=10)),
                "approval_ref": f"approval:{run_id}:facility_mgr_001",
            },
            {
                "role": "QUALITY_INSPECTOR",
                "principal_ref": "principal:quality_insp_017",
                "status": "APPROVED",
                "approved_at": _utc_iso(base_time - timedelta(seconds=5)),
                "approval_ref": f"approval:{run_id}:quality_insp_017",
            },
        ],
        "policy_snapshot_ref": policy_snapshot_ref,
        "expires_at": _utc_iso(base_time + timedelta(minutes=15)),
        "created_at": _utc_iso(base_time - timedelta(seconds=20)),
        "version": int(approval.get("expected_envelope_version") or 1),
    }


async def seed_approval_envelope(
    *,
    evaluate_payload: Mapping[str, Any],
    run_id: str,
    policy_snapshot_ref: str,
    session_factory: Any | None = None,
    approval_dao: Any | None = None,
) -> dict[str, Any]:
    from seedcore.coordinator.dao import TransferApprovalEnvelopeDAO  # noqa: PLC0415
    from seedcore.database import get_async_pg_session_factory  # noqa: PLC0415

    resolved_session_factory = session_factory or get_async_pg_session_factory()
    if resolved_session_factory is None:
        raise RuntimeRctAuditError("Postgres session factory is unavailable for approval seed")
    dao = approval_dao or TransferApprovalEnvelopeDAO()
    envelope = build_approval_envelope(
        run_id=run_id,
        evaluate_payload=evaluate_payload,
        policy_snapshot_ref=policy_snapshot_ref,
    )
    async with resolved_session_factory() as session:
        async with session.begin():
            return await dao.create_or_update_envelope(session, envelope=envelope)


def require_allow_evaluate(evaluate_response: Mapping[str, Any]) -> None:
    decision = evaluate_response.get("decision") if isinstance(evaluate_response.get("decision"), Mapping) else {}
    if str(decision.get("disposition") or "").strip().lower() != "allow":
        raise RuntimeRctAuditError(
            "agent action evaluate did not return an allow disposition: "
            + json.dumps(decision, sort_keys=True)
        )


def extract_governed_audit_entry(closure_response: Mapping[str, Any]) -> dict[str, Any] | None:
    settlement = closure_response.get("settlement_result")
    if not isinstance(settlement, Mapping):
        return None
    entry = settlement.get("governed_audit_entry")
    if not isinstance(entry, Mapping):
        return None
    audit_id = str(entry.get("entry_id") or entry.get("id") or "").strip()
    if not audit_id:
        return None
    return {"audit_id": audit_id, "entry": dict(entry)}


def _headers() -> dict[str, str]:
    token = os.getenv("SEEDCORE_AGENT_ACTION_GATEWAY_AUTH_TOKEN", "").strip()
    return {"authorization": f"Bearer {token}"} if token else {}


def _select_policy_snapshot(pkg_status: Mapping[str, Any], fallback: str) -> str:
    for key in ("active_version", "snapshot_id", "active_snapshot_version"):
        value = str(pkg_status.get(key) or "").strip()
        if value:
            return value
    return fallback


def _normalize_evaluate_for_fallback(
    *,
    evaluate_response: Mapping[str, Any],
    evaluate_payload: Mapping[str, Any],
    run_id: str,
) -> dict[str, Any]:
    normalized = json.loads(json.dumps(dict(evaluate_response)))
    decision = normalized.setdefault("decision", {})
    snapshot_ref = str(
        decision.get("policy_snapshot_ref")
        or evaluate_payload.get("policy_snapshot_ref")
        or DEFAULT_POLICY_SNAPSHOT_REF
    )
    snapshot_hash = str(decision.get("policy_snapshot_hash") or "").strip() or _stable_hash(snapshot_ref)
    decision["policy_snapshot_ref"] = snapshot_ref
    decision["policy_snapshot_hash"] = snapshot_hash

    governed_receipt = normalized.setdefault("governed_receipt", {})
    request_id = str(evaluate_payload["request_id"])
    asset = evaluate_payload.get("asset") if isinstance(evaluate_payload.get("asset"), Mapping) else {}
    governed_receipt.setdefault("audit_id", str(__import__("uuid").uuid5(__import__("uuid").NAMESPACE_URL, request_id)))
    governed_receipt.setdefault("asset_ref", asset.get("asset_id"))
    governed_receipt.setdefault("policy_receipt_id", f"policy-receipt:{request_id}")
    governed_receipt.setdefault("decision_hash", _stable_hash(f"decision:{run_id}"))
    governed_receipt.setdefault("snapshot_version", snapshot_ref)
    governed_receipt.setdefault("snapshot_hash", snapshot_hash)
    governed_receipt.setdefault("policy_snapshot_hash", snapshot_hash)
    governed_receipt.setdefault("decision_graph_snapshot_hash", snapshot_hash)
    governed_receipt.setdefault("disposition", decision.get("disposition"))
    governed_receipt.setdefault("reason", decision.get("reason"))
    return normalized


async def append_dao_fallback(
    *,
    evaluate_payload: Mapping[str, Any],
    evaluate_response: Mapping[str, Any],
    closure_payload: Mapping[str, Any],
    run_id: str,
    session_factory: Any | None = None,
    audit_dao: Any | None = None,
) -> dict[str, Any]:
    from seedcore.api.routers.agent_actions_router import (  # noqa: PLC0415
        AgentActionClosureRequest,
        AgentActionEvaluateResponse,
        GovernedExecutionAuditDAO,
        _AgentActionStoredRecord,
        _build_closure_evidence_bundle,
        _build_closure_policy_receipt,
        _closure_task_uuid,
    )
    from seedcore.database import get_async_pg_session_factory  # noqa: PLC0415

    response_payload = _normalize_evaluate_for_fallback(
        evaluate_response=evaluate_response,
        evaluate_payload=evaluate_payload,
        run_id=run_id,
    )
    response = AgentActionEvaluateResponse.model_validate(response_payload)
    closure = AgentActionClosureRequest.model_validate(dict(closure_payload))
    task_id = _closure_task_uuid(str(evaluate_payload["request_id"]))
    request_record = _AgentActionStoredRecord(
        request_id=response.request_id,
        idempotency_key=str(evaluate_payload.get("idempotency_key") or ""),
        request_hash=_stable_hash(json.dumps(evaluate_payload, sort_keys=True)),
        recorded_at=datetime.now(timezone.utc),
        response=response,
        request_payload=dict(evaluate_payload),
    )
    evidence_bundle = _build_closure_evidence_bundle(
        closure_payload=closure,
        request_record=request_record,
    )
    policy_receipt = _build_closure_policy_receipt(
        request_record=request_record,
        closure_payload=closure,
        evidence_bundle=evidence_bundle,
    )

    asset = evaluate_payload.get("asset") if isinstance(evaluate_payload.get("asset"), Mapping) else {}
    workflow = evaluate_payload.get("workflow") if isinstance(evaluate_payload.get("workflow"), Mapping) else {}
    principal = evaluate_payload.get("principal") if isinstance(evaluate_payload.get("principal"), Mapping) else {}
    authority_scope = (
        evaluate_payload.get("authority_scope")
        if isinstance(evaluate_payload.get("authority_scope"), Mapping)
        else {}
    )
    telemetry = evaluate_payload.get("telemetry") if isinstance(evaluate_payload.get("telemetry"), Mapping) else {}
    decision = response.decision
    governed_receipt = dict(response.governed_receipt)
    policy_decision = {
        "allowed": bool(decision.allowed),
        "disposition": decision.disposition,
        "reason": decision.reason,
        "reason_code": decision.reason_code,
        "policy_snapshot": decision.policy_snapshot_ref,
        "required_approvals": list(response.required_approvals or []),
        "authz_graph": {
            "workflow_type": "restricted_custody_transfer",
            "workflow_status": "closed",
            "disposition": decision.disposition,
            "reason": decision.reason,
            "snapshot_hash": evidence_bundle.get("decision_graph_snapshot_hash"),
            "snapshot_version": decision.policy_snapshot_ref,
            "policy_snapshot_hash": evidence_bundle.get("policy_snapshot_hash"),
            "decision_graph_snapshot_hash": evidence_bundle.get("decision_graph_snapshot_hash"),
            "state_binding_hash": evidence_bundle.get("state_binding_hash"),
            "asset_ref": asset.get("asset_id"),
            "trust_gaps": [],
            "obligations": list(response.obligations or []),
        },
        "governed_receipt": {
            **governed_receipt,
            "state_binding_hash": evidence_bundle.get("state_binding_hash"),
            "policy_snapshot_hash": evidence_bundle.get("policy_snapshot_hash"),
            "decision_graph_snapshot_hash": evidence_bundle.get("decision_graph_snapshot_hash"),
            "policy_receipt_id": policy_receipt.get("policy_receipt_id"),
            "asset_ref": asset.get("asset_id"),
            "disposition": decision.disposition,
            "reason": decision.reason,
        },
    }
    action_intent = {
        "intent_id": evaluate_payload["request_id"],
        "timestamp": evaluate_payload.get("requested_at"),
        "valid_until": workflow.get("valid_until"),
        "principal": {
            "agent_id": principal.get("agent_id"),
            "role_profile": principal.get("role_profile"),
        },
        "resource": {
            "asset_id": asset.get("asset_id"),
            "lot_id": asset.get("lot_id"),
            "target_zone": asset.get("to_zone"),
            "category_envelope": {
                "transfer_context": {
                    "from_zone": asset.get("from_zone"),
                    "to_zone": asset.get("to_zone"),
                    "facility_ref": principal.get("organization_ref"),
                    "custody_point_ref": authority_scope.get("expected_coordinate_ref"),
                    "expected_current_custodian": asset.get("from_custodian_ref"),
                    "next_custodian": asset.get("to_custodian_ref"),
                }
            },
        },
        "action": {
            "type": workflow.get("action_type"),
            "operation": workflow.get("type"),
            "parameters": {
                "endpoint_id": closure_payload.get("node_id"),
                "request_summary": f"Local runtime RCT verification wedge for {asset.get('asset_id')}",
                "gateway": {
                    "workflow_type": workflow.get("type"),
                    "idempotency_key": evaluate_payload.get("idempotency_key"),
                    "owner_id": principal.get("owner_id"),
                    "delegation_ref": principal.get("delegation_ref"),
                    "organization_ref": principal.get("organization_ref"),
                    "scope_id": authority_scope.get("scope_id"),
                    "asset_ref": authority_scope.get("asset_ref") or asset.get("asset_id"),
                    "expected_from_zone": authority_scope.get("expected_from_zone"),
                    "expected_to_zone": authority_scope.get("expected_to_zone"),
                    "expected_coordinate_ref": authority_scope.get("expected_coordinate_ref"),
                    "hardware_node_id": (
                        principal.get("hardware_fingerprint", {}).get("node_id")
                        if isinstance(principal.get("hardware_fingerprint"), Mapping)
                        else None
                    ),
                    "fingerprint_components": closure_payload.get("forensic_block", {}).get("fingerprint_components", {}),
                },
                "approval_context": {
                    "approval_envelope_id": evaluate_payload.get("approval", {}).get("approval_envelope_id")
                    if isinstance(evaluate_payload.get("approval"), Mapping)
                    else None,
                    "approval_envelope_version": evaluate_payload.get("approval", {}).get("expected_envelope_version")
                    if isinstance(evaluate_payload.get("approval"), Mapping)
                    else None,
                    "approved_by": ["principal:facility_mgr_001", "principal:outbound_mgr_002"],
                },
                "telemetry": dict(telemetry),
            },
        },
    }
    policy_case = {
        "required_approvals": list(response.required_approvals or []),
        "trust_gaps": list(response.trust_gaps or []),
        "obligations": list(response.obligations or []),
        "workflow_hints": {
            "workflow_type": "restricted_custody_transfer",
            "strict_state_transition_fields": True,
        },
    }

    resolved_session_factory = session_factory or get_async_pg_session_factory()
    if resolved_session_factory is None:
        raise RuntimeRctAuditError("Postgres session factory is unavailable for DAO fallback")
    dao = audit_dao or GovernedExecutionAuditDAO()
    async with resolved_session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    """
                    INSERT INTO tasks (id, type, domain, description, params, status, snapshot_id)
                    VALUES (
                        CAST(:task_id AS uuid),
                        'action',
                        'restricted_custody_transfer',
                        :description,
                        CAST(:params AS jsonb),
                        'completed',
                        pkg_active_snapshot_id('default')
                    )
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "task_id": task_id,
                    "description": f"Local RCT verification audit seed {run_id}",
                    "params": json.dumps({"source": "generate_runtime_rct_audit", "run_id": run_id}),
                },
            )
            result = await dao.append_record(
                session,
                task_id=task_id,
                record_type="execution_receipt",
                intent_id=str(evaluate_payload["request_id"]),
                token_id=(
                    response.execution_token.token_id
                    if response.execution_token is not None
                    else f"execution-token:{evaluate_payload['request_id']}"
                ),
                policy_snapshot=str(decision.policy_snapshot_ref),
                policy_decision=policy_decision,
                action_intent=action_intent,
                policy_case=policy_case,
                policy_receipt=policy_receipt,
                evidence_bundle=evidence_bundle,
                actor_agent_id=str(principal.get("agent_id") or "").strip() or None,
                actor_organ_id=None,
            )
    audit_id = str(result.get("entry_id") or result.get("id") or "").strip()
    if not audit_id:
        raise RuntimeRctAuditError(f"DAO fallback did not return an audit id: {result}")
    return {"audit_id": audit_id, "entry": dict(result), "path": "dao_fallback_after_closure"}


async def generate_one(
    *,
    client: httpx.AsyncClient,
    api_base: str,
    run_id: str,
    policy_snapshot_ref: str,
    execute_evaluate: bool,
    allow_dao_fallback: bool,
) -> dict[str, Any]:
    health = await client.get(f"{api_base}/health")
    health.raise_for_status()
    pkg_status_payload: dict[str, Any] = {}
    try:
        pkg_status = await client.get(f"{api_base}/api/v1/pkg/status")
        if pkg_status.status_code == 200 and isinstance(pkg_status.json(), dict):
            pkg_status_payload = pkg_status.json()
    except Exception:
        pkg_status_payload = {}
    selected_snapshot = _select_policy_snapshot(pkg_status_payload, policy_snapshot_ref)
    evaluate_payload = build_evaluate_payload(run_id=run_id, policy_snapshot_ref=selected_snapshot)
    await seed_approval_envelope(
        evaluate_payload=evaluate_payload,
        run_id=run_id,
        policy_snapshot_ref=selected_snapshot,
    )
    no_execute = "false" if execute_evaluate else "true"
    evaluate = await client.post(
        f"{api_base}/api/v1/agent-actions/evaluate",
        params={"debug": "true", "no_execute": no_execute},
        json=evaluate_payload,
        headers=_headers(),
    )
    evaluate_payload_out = evaluate.json() if evaluate.headers.get("content-type", "").startswith("application/json") else {}
    if evaluate.status_code != 200 or not isinstance(evaluate_payload_out, dict):
        raise RuntimeRctAuditError(
            f"evaluate failed status={evaluate.status_code}: {json.dumps(evaluate_payload_out)[:1000]}"
        )
    require_allow_evaluate(evaluate_payload_out)

    closure_payload = build_closure_payload(run_id=run_id, evaluate_payload=evaluate_payload)
    closure = await client.post(
        f"{api_base}/api/v1/agent-actions/{evaluate_payload['request_id']}/closures",
        json=closure_payload,
        headers=_headers(),
    )
    closure_payload_out = closure.json() if closure.headers.get("content-type", "").startswith("application/json") else {}
    if closure.status_code != 200 or not isinstance(closure_payload_out, dict):
        raise RuntimeRctAuditError(
            f"closure failed status={closure.status_code}: {json.dumps(closure_payload_out)[:1000]}"
        )

    path = "api_closure"
    entry = extract_governed_audit_entry(closure_payload_out)
    if entry is None:
        if not allow_dao_fallback:
            raise RuntimeRctAuditError("closure succeeded but did not emit governed_audit_entry")
        entry = await append_dao_fallback(
            evaluate_payload=evaluate_payload,
            evaluate_response=evaluate_payload_out,
            closure_payload=closure_payload,
            run_id=run_id,
        )
        path = str(entry.get("path") or "dao_fallback_after_closure")

    audit_id = str(entry["audit_id"])
    return {
        "run_id": run_id,
        "request_id": str(evaluate_payload["request_id"]),
        "intent_id": str(evaluate_payload["request_id"]),
        "closure_id": str(closure_payload["closure_id"]),
        "audit_id": audit_id,
        "path": path,
        "policy_snapshot_ref": selected_snapshot,
        "replay_url": f"{api_base}/api/v1/replay?audit_id={audit_id}&projection=internal",
        "replay_artifacts_url": f"{api_base}/api/v1/replay/artifacts?audit_id={audit_id}&projection=internal",
        "verification_runtime_query": f"source=runtime&audit_id={audit_id}",
        "closure_settlement_status": closure_payload_out.get("settlement_status"),
    }


async def _async_main(args: argparse.Namespace) -> dict[str, Any]:
    api_base = str(args.api_base).rstrip("/")
    run_prefix = args.run_prefix or "local-rct-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    items: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=float(args.timeout)) as client:
        for index in range(1, int(args.count) + 1):
            items.append(
                await generate_one(
                    client=client,
                    api_base=api_base,
                    run_id=build_run_id(prefix=run_prefix, index=index),
                    policy_snapshot_ref=args.policy_snapshot_ref,
                    execute_evaluate=bool(args.execute_evaluate),
                    allow_dao_fallback=not bool(args.no_dao_fallback),
                )
            )
    payload: dict[str, Any] = {"ok": True, "count": len(items), "items": items}
    if len(items) == 1:
        payload.update(items[0])
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default=os.getenv("SEEDCORE_API", "http://127.0.0.1:8002"))
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--run-prefix", default="")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--policy-snapshot-ref", default=DEFAULT_POLICY_SNAPSHOT_REF)
    parser.add_argument(
        "--execute-evaluate",
        action="store_true",
        help="Do not request no_execute preflight; requires local execution dependencies to be ready.",
    )
    parser.add_argument(
        "--no-dao-fallback",
        action="store_true",
        help="Fail if the closure path does not emit governed_audit_entry.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if int(args.count) < 1:
        raise SystemExit("--count must be >= 1")
    try:
        result = asyncio.run(_async_main(args))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
