#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from scripts.host.verify_rct_hot_path_shadow import (  # noqa: E402
    CANONICAL_CASES,
    EXPECTED_DISPOSITIONS,
    _build_request,
    _persist_authoritative_approval,
    _resolve_active_snapshot,
)
from seedcore.coordinator.dao import AssetCustodyStateDAO, GovernedExecutionAuditDAO  # noqa: E402
from seedcore.database import get_async_pg_session_factory  # noqa: E402
from seedcore.hal.custody.transition_receipts import build_transition_receipt  # noqa: E402
from seedcore.ops.evidence.builder import build_evidence_bundle, build_policy_receipt_artifact  # noqa: E402
from seedcore.services.replay_service import ReplayService  # noqa: E402
from seedcore.integrations.rust_kernel import (  # noqa: E402
    seal_replay_bundle_with_rust,
    verify_replay_bundle_with_rust,
)
from sqlalchemy import text  # noqa: E402


FIXTURE_ROOT = REPO_ROOT / "rust" / "fixtures" / "transfers"
DEFAULT_RUNTIME_BASE = "http://127.0.0.1:8002/api/v1"
DEFAULT_VERIFY_BASE = "http://127.0.0.1:7071/api/v1"

# Keep host-mode defaults aligned with deploy/local/run-api.sh.
os.environ.setdefault("PG_DSN", "postgresql://ningli@127.0.0.1:5432/seedcore")
os.environ.setdefault("PG_DSN_ASYNC", "postgresql+asyncpg://ningli@127.0.0.1:5432/seedcore")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_get(url: str, *, timeout: float = 15.0) -> dict[str, Any]:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected_json_object:{url}")
    return payload


def _json_post(url: str, payload: dict[str, Any], *, timeout: float = 20.0) -> dict[str, Any]:
    response = requests.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError(f"expected_json_object:{url}")
    return body


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            output.append(item.strip())
    return output


def _derive_missing_prerequisites(disposition: str, authority_summary: dict[str, Any], trust_gaps: list[str]) -> list[str]:
    if isinstance(authority_summary.get("missing_prerequisites"), list):
        return _string_list(authority_summary.get("missing_prerequisites"))
    if disposition == "deny":
        return ["missing_dual_approval"]
    if disposition == "quarantine" and "stale_telemetry" in trust_gaps:
        return ["telemetry_freshness_gap"]
    if disposition == "escalate":
        return ["human_review_required"]
    return []


def _minted_artifacts(disposition: str, policy_receipt_id: str, token_id: str | None) -> list[dict[str, str]]:
    artifacts = [{"kind": "policy_receipt", "ref": policy_receipt_id}]
    if disposition == "allow" and token_id:
        artifacts.append({"kind": "execution_token", "ref": token_id})
    return artifacts


def _build_policy_decision(
    *,
    case_name: str,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any],
    approval_record: dict[str, Any],
    authority_summary: dict[str, Any],
    policy_receipt_id_hint: str,
) -> dict[str, Any]:
    decision = response_payload.get("decision") if isinstance(response_payload.get("decision"), dict) else {}
    action_intent = request_payload.get("action_intent") if isinstance(request_payload.get("action_intent"), dict) else {}
    action = action_intent.get("action") if isinstance(action_intent.get("action"), dict) else {}
    resource = action_intent.get("resource") if isinstance(action_intent.get("resource"), dict) else {}
    parameters = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
    approval_context = parameters.get("approval_context") if isinstance(parameters.get("approval_context"), dict) else {}
    transfer_context = (
        resource.get("category_envelope", {}).get("transfer_context")
        if isinstance(resource.get("category_envelope"), dict)
        and isinstance(resource.get("category_envelope", {}).get("transfer_context"), dict)
        else {}
    )
    if not isinstance(transfer_context, dict):
        transfer_context = {}

    disposition = str(decision.get("disposition") or "deny").strip().lower()
    reason = str(decision.get("reason") or decision.get("reason_code") or "policy_decision_resolved")
    trust_gaps = _string_list(response_payload.get("trust_gaps"))
    required_approvals = _string_list(response_payload.get("required_approvals"))
    approved_by = _string_list(approval_context.get("approved_by"))
    token = response_payload.get("execution_token") if isinstance(response_payload.get("execution_token"), dict) else None
    token_id = str(token.get("token_id")) if isinstance(token, dict) and token.get("token_id") is not None else None
    policy_snapshot = str(decision.get("policy_snapshot_ref") or request_payload.get("policy_snapshot_ref") or "snapshot:runtime")
    approval_envelope_id = str(approval_record.get("approval_envelope_id") or approval_context.get("approval_envelope_id") or "")
    approval_binding_hash = str(
        approval_record.get("approval_binding_hash")
        or approval_context.get("approval_binding_hash")
        or ""
    )
    approval_envelope_version = int(
        approval_record.get("version")
        or approval_context.get("approval_envelope_version")
        or approval_context.get("observed_version")
        or 0
    )
    decision_hash = f"sha256:{_sha256(f'{case_name}:{request_payload.get('request_id')}:{policy_snapshot}:{disposition}:{approval_binding_hash}')}"
    missing_prerequisites = _derive_missing_prerequisites(disposition, authority_summary, trust_gaps)
    matched_policy_refs = _string_list(authority_summary.get("matched_policy_refs")) or ["policy:transfer-v1"]
    authority_paths = _string_list(authority_summary.get("authority_paths")) or ["facility_manager -> transfer_lot"]
    obligations = (
        [dict(item) for item in response_payload.get("obligations", []) if isinstance(item, dict)]
        if isinstance(response_payload.get("obligations"), list)
        else []
    )
    signer_metadata = (
        token.get("signature")
        if isinstance(token, dict) and isinstance(token.get("signature"), dict)
        else None
    )

    return {
        "allowed": bool(decision.get("allowed")),
        "disposition": disposition,
        "reason": reason,
        "deny_code": str(decision.get("reason_code") or ""),
        "policy_snapshot": policy_snapshot,
        "required_approvals": required_approvals,
        "obligations": obligations,
        "execution_token": token if isinstance(token, dict) else None,
        "authz_graph": {
            "mode": "hot_path_shadow_runtime_signoff",
            "workflow_type": "restricted_custody_transfer",
            "workflow_status": {
                "allow": "ready_for_handoff",
                "deny": "blocked",
                "quarantine": "quarantined_pending_review",
                "escalate": "manual_review_required",
            }.get(disposition, "blocked"),
            "disposition": disposition,
            "reason": reason,
            "asset_ref": str(resource.get("asset_id") or request_payload.get("asset_context", {}).get("asset_ref") or ""),
            "resource_ref": str(resource.get("resource_uri") or ""),
            "current_custodian": str(
                transfer_context.get("expected_current_custodian")
                or request_payload.get("asset_context", {}).get("current_custodian_ref")
                or ""
            ),
            "approval_envelope_id": approval_envelope_id,
            "approval_envelope_version": approval_envelope_version if approval_envelope_version > 0 else None,
            "approval_binding_hash": approval_binding_hash or None,
            "required_approvals": required_approvals,
            "approved_by": approved_by,
            "co_sign_status": "co_signed" if disposition == "allow" else "pending",
            "matched_policy_refs": matched_policy_refs,
            "authority_path_summary": authority_paths,
            "missing_prerequisites": missing_prerequisites,
            "trust_gaps": [{"code": code, "message": code, "details": {}} for code in trust_gaps],
            "minted_artifacts": _minted_artifacts(disposition, policy_receipt_id_hint, token_id),
            "obligations": obligations,
            "snapshot_ref": policy_snapshot,
            "snapshot_id": policy_snapshot,
            "snapshot_version": policy_snapshot,
            "snapshot_hash": decision.get("policy_snapshot_hash"),
        },
        "governed_receipt": {
            "decision_hash": decision_hash,
            "disposition": disposition,
            "snapshot_ref": policy_snapshot,
            "snapshot_id": policy_snapshot,
            "snapshot_version": policy_snapshot,
            "snapshot_hash": decision.get("policy_snapshot_hash"),
            "principal_ref": str(action_intent.get("principal", {}).get("agent_id") if isinstance(action_intent.get("principal"), dict) else ""),
            "operation": str(action.get("type") or "TRANSFER_CUSTODY"),
            "asset_ref": str(resource.get("asset_id") or request_payload.get("asset_context", {}).get("asset_ref") or ""),
            "resource_ref": str(resource.get("resource_uri") or ""),
            "twin_ref": str(resource.get("asset_id") or request_payload.get("asset_context", {}).get("asset_ref") or ""),
            "reason": reason,
            "generated_at": str(response_payload.get("decided_at") or _now_iso()),
            "trust_gap_codes": trust_gaps,
            "approval_envelope_id": approval_envelope_id,
            "approval_envelope_version": approval_envelope_version if approval_envelope_version > 0 else None,
            "approval_binding_hash": approval_binding_hash or None,
            "required_roles": _string_list(approval_context.get("required_roles")),
            "approved_by": approved_by,
            "workflow_type": "restricted_custody_transfer",
            "signer_metadata": signer_metadata,
            "custody_proof": [f"custody:{case_name}:{approval_envelope_id}"] if approval_envelope_id else [],
            "evidence_refs": _string_list(request_payload.get("telemetry_context", {}).get("evidence_refs")),
            "provenance_sources": ["runtime_hot_path_shadow"],
        },
    }


def _build_task_governance_context(
    *,
    task_id: str,
    request_payload: dict[str, Any],
    policy_case: dict[str, Any],
    policy_decision: dict[str, Any],
    policy_receipt: dict[str, Any],
) -> dict[str, Any]:
    action_intent = request_payload.get("action_intent") if isinstance(request_payload.get("action_intent"), dict) else {}
    execution_token = policy_decision.get("execution_token") if isinstance(policy_decision.get("execution_token"), dict) else {}
    return {
        "task_id": task_id,
        "params": {
            "governance": {
                "action_intent": dict(action_intent),
                "policy_case": dict(policy_case),
                "policy_decision": dict(policy_decision),
                "execution_token": dict(execution_token),
                "policy_receipt": dict(policy_receipt),
            }
        },
    }


def _build_hal_envelope(
    *,
    task_id: str,
    case_name: str,
    decided_at: str,
    disposition: str,
    transition_receipt: dict[str, Any] | None,
    endpoint_id: str,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    if transition_receipt is not None:
        results.append(
            {
                "output": {
                    "transition_receipt": transition_receipt,
                    "actuator_endpoint": endpoint_id,
                    "result_hash": f"actuator-hash:{case_name}",
                }
            }
        )
    return {
        "task_id": task_id,
        "success": disposition == "allow",
        "payload": {
            "result": {
                "status": "executed" if disposition == "allow" else "governed_blocked",
                "disposition": disposition,
            },
            "results": results,
        },
        "meta": {"exec": {"finished_at": decided_at}},
    }


async def _append_audit_record(
    *,
    task_id: str,
    policy_snapshot: str,
    action_intent: dict[str, Any],
    policy_case: dict[str, Any],
    policy_decision: dict[str, Any],
    policy_receipt: dict[str, Any],
    evidence_bundle: dict[str, Any],
) -> str:
    dao = GovernedExecutionAuditDAO()
    custody_dao = AssetCustodyStateDAO()
    session_factory = get_async_pg_session_factory()
    disposition = str(policy_decision.get("disposition") or "deny").strip().lower()
    action = action_intent.get("action") if isinstance(action_intent.get("action"), dict) else {}
    parameters = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
    resource = action_intent.get("resource") if isinstance(action_intent.get("resource"), dict) else {}
    category_envelope = resource.get("category_envelope") if isinstance(resource.get("category_envelope"), dict) else {}
    transfer_context = category_envelope.get("transfer_context") if isinstance(category_envelope.get("transfer_context"), dict) else {}
    endpoint_id = str(parameters.get("endpoint_id") or "")
    token_id = (
        str(policy_decision.get("execution_token", {}).get("token_id"))
        if isinstance(policy_decision.get("execution_token"), dict)
        and policy_decision.get("execution_token", {}).get("token_id") is not None
        else None
    )
    principal = action_intent.get("principal") if isinstance(action_intent.get("principal"), dict) else {}
    asset_id = str(resource.get("asset_id") or "")
    decided_zone = (
        str(transfer_context.get("to_zone") or "")
        if disposition == "allow"
        else str(transfer_context.get("from_zone") or "")
    )
    last_transition = (
        evidence_bundle.get("evidence_inputs", {}).get("transition_receipts", [{}])[0]
        if isinstance(evidence_bundle.get("evidence_inputs"), dict)
        and isinstance(evidence_bundle.get("evidence_inputs", {}).get("transition_receipts"), list)
        and evidence_bundle.get("evidence_inputs", {}).get("transition_receipts")
        else {}
    )
    async with session_factory() as session:
        appended = await dao.append_record(
            session,
            task_id=task_id,
            record_type="execution_receipt",
            intent_id=str(action_intent.get("intent_id") or ""),
            token_id=token_id,
            policy_snapshot=policy_snapshot,
            policy_decision=policy_decision,
            action_intent=action_intent,
            policy_case=policy_case,
            policy_receipt=policy_receipt,
            evidence_bundle=evidence_bundle,
            actor_agent_id=str(principal.get("agent_id") or ""),
            actor_organ_id="organism",
        )
        if asset_id:
            await custody_dao.upsert_snapshot(
                session,
                asset_id=asset_id,
                lot_id=str(resource.get("lot_id") or "") or None,
                current_zone=decided_zone or None,
                is_quarantined=disposition == "quarantine",
                authority_source="rct_live_signoff_runtime",
                last_transition_seq=1,
                last_receipt_hash=str(last_transition.get("payload_hash") or "") or None,
                last_receipt_nonce=str(last_transition.get("receipt_nonce") or "") or None,
                last_receipt_counter=(
                    int(last_transition.get("trust_proof", {}).get("replay", {}).get("receipt_counter"))
                    if isinstance(last_transition.get("trust_proof"), dict)
                    and isinstance(last_transition.get("trust_proof", {}).get("replay"), dict)
                    and last_transition.get("trust_proof", {}).get("replay", {}).get("receipt_counter") is not None
                    else None
                ),
                last_endpoint_id=endpoint_id or None,
                last_task_id=task_id,
                last_intent_id=str(action_intent.get("intent_id") or "") or None,
                last_token_id=token_id,
                updated_by=str(principal.get("agent_id") or "seedcore:rct_signoff"),
            )
        await session.commit()
    return str(appended["entry_id"])


async def _resolve_existing_task_id() -> str:
    session_factory = get_async_pg_session_factory()
    async with session_factory() as session:
        result = await session.execute(text("SELECT id::text FROM public.tasks ORDER BY created_at DESC LIMIT 1"))
        row = result.first()
        if row is None or row[0] is None:
            raise RuntimeError("no_tasks_available_for_audit_fk")
        return str(row[0])


async def _build_rust_chain_report(audit_id: str) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    replay_service = ReplayService()
    session_factory = get_async_pg_session_factory()
    async with session_factory() as session:
        _, _, replay = await replay_service.assemble_replay_record(session, audit_id=audit_id)
    if isinstance(replay.audit_record, dict):
        record = dict(replay.audit_record)
    else:
        record = replay.audit_record.model_dump(mode="json")
    artifacts = replay_service._build_rust_replay_artifacts(  # noqa: SLF001
        record=record,
        policy_receipt=replay.policy_receipt,
        evidence_bundle=replay.evidence_bundle,
        transition_receipts=replay.transition_receipts,
        approval_context=replay_service._approval_context_from_record(record),  # noqa: SLF001
    )
    sealed_bundle = seal_replay_bundle_with_rust(artifacts)
    verify_report = verify_replay_bundle_with_rust(sealed_bundle)
    return artifacts, sealed_bundle, verify_report


def _run_surface_protocol(audit_id: str) -> tuple[int, str]:
    command = [
        "bash",
        "scripts/host/verify_productized_surface.sh",
    ]
    env = dict(os.environ)
    env["SEEDCORE_AUDIT_ID"] = audit_id
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def _assert_live_stack(runtime_base: str, verify_base: str) -> None:
    runtime_root = runtime_base.rstrip("/")
    if runtime_root.endswith("/api/v1"):
        runtime_root = runtime_root[: -len("/api/v1")]
    elif runtime_root.endswith("/api"):
        runtime_root = runtime_root[: -len("/api")]
    checks = [
        f"{runtime_root}/health",
        f"{runtime_base.rstrip('/')}/pkg/status",
        f"{verify_base.rstrip('/')}/transfers/catalog?source=fixture",
    ]
    for url in checks:
        response = requests.get(url, timeout=10)
        response.raise_for_status()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture RCT live sign-off runtime matrix with audit-linked artifacts.")
    parser.add_argument("--runtime-base", default=DEFAULT_RUNTIME_BASE)
    parser.add_argument("--verify-base", default=DEFAULT_VERIFY_BASE)
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / ".local-runtime" / "rct_live_signoff"),
        help="Directory to write capture artifacts.",
    )
    args = parser.parse_args()

    runtime_base = args.runtime_base.rstrip("/")
    verify_base = args.verify_base.rstrip("/")
    _assert_live_stack(runtime_base, verify_base)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = Path(args.output_dir).resolve() / timestamp
    output_root.mkdir(parents=True, exist_ok=True)

    active_snapshot = _resolve_active_snapshot(runtime_base)
    case_rows: list[dict[str, Any]] = []
    allow_audit_id: str | None = None
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    existing_task_id = loop.run_until_complete(_resolve_existing_task_id())

    for case_name in CANONICAL_CASES:
        case_dir = FIXTURE_ROOT / case_name
        case_output = output_root / case_name
        case_output.mkdir(parents=True, exist_ok=True)

        authority_summary = _read_json(case_dir / "input.authority_graph_summary.json")
        asset_state = _read_json(case_dir / "input.asset_state.json")
        persisted_approval = _persist_authoritative_approval(runtime_base, case_dir)
        approval_envelope_id = str(persisted_approval.get("approval_envelope_id") or "")
        approval_current = _json_get(f"{runtime_base}/transfer-approvals/{approval_envelope_id}")

        request_payload = _build_request(case_dir, persisted_approval=persisted_approval)
        if active_snapshot:
            request_payload["policy_snapshot_ref"] = active_snapshot
            request_payload["action_intent"]["action"]["security_contract"]["version"] = active_snapshot

        response_payload = _json_post(f"{runtime_base}/pdp/hot-path/evaluate?debug=true", request_payload)
        disposition = str(response_payload.get("decision", {}).get("disposition") or "deny").strip().lower()
        expected = EXPECTED_DISPOSITIONS[case_name]
        if disposition != expected:
            raise RuntimeError(f"disposition_mismatch:{case_name}:expected={expected}:actual={disposition}")

        task_id = existing_task_id
        action_intent = (
            dict(request_payload.get("action_intent"))
            if isinstance(request_payload.get("action_intent"), dict)
            else {}
        )
        principal = action_intent.get("principal") if isinstance(action_intent.get("principal"), dict) else {}
        action = action_intent.get("action") if isinstance(action_intent.get("action"), dict) else {}
        parameters = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
        endpoint_id = str(parameters.get("endpoint_id") or "hal://robot_sim/1")
        resource = action_intent.get("resource") if isinstance(action_intent.get("resource"), dict) else {}
        transfer_context = (
            resource.get("category_envelope", {}).get("transfer_context")
            if isinstance(resource.get("category_envelope"), dict)
            and isinstance(resource.get("category_envelope", {}).get("transfer_context"), dict)
            else {}
        )
        if not isinstance(transfer_context, dict):
            transfer_context = {}

        policy_receipt_hint = f"policy-receipt:{action_intent.get('intent_id') or case_name}"
        policy_decision = _build_policy_decision(
            case_name=case_name,
            request_payload=request_payload,
            response_payload=response_payload,
            approval_record=approval_current,
            authority_summary=authority_summary,
            policy_receipt_id_hint=policy_receipt_hint,
        )
        policy_case = {
            "policy_snapshot": response_payload.get("decision", {}).get("policy_snapshot_ref"),
            "workflow_type": "restricted_custody_transfer",
            "authoritative_approval_envelope": approval_current.get("envelope") if isinstance(approval_current.get("envelope"), dict) else {},
            "authoritative_approval_transition_history": (
                approval_current.get("transition_history")
                if isinstance(approval_current.get("transition_history"), list)
                else []
            ),
            "authoritative_approval_transition_head": approval_current.get("approval_transition_head"),
            "asset_context": request_payload.get("asset_context"),
            "telemetry_context": request_payload.get("telemetry_context"),
        }

        task_dict_for_receipt = {
            "task_id": task_id,
            "params": {
                "governance": {
                    "action_intent": action_intent,
                    "policy_case": policy_case,
                    "policy_decision": policy_decision,
                    "execution_token": (
                        dict(policy_decision.get("execution_token"))
                        if isinstance(policy_decision.get("execution_token"), dict)
                        else {}
                    ),
                }
            },
        }
        policy_receipt_model = build_policy_receipt_artifact(
            task_dict=task_dict_for_receipt,
            timestamp=str(response_payload.get("decided_at") or _now_iso()),
        )
        if policy_receipt_model is None:
            raise RuntimeError(f"policy_receipt_not_generated:{case_name}")
        policy_receipt = policy_receipt_model.model_dump(mode="json")

        transition_receipt: dict[str, Any] | None = None
        if disposition == "allow":
            execution_token = (
                policy_decision.get("execution_token")
                if isinstance(policy_decision.get("execution_token"), dict)
                else {}
            )
            transition_receipt = build_transition_receipt(
                intent_id=str(action_intent.get("intent_id") or f"intent:{case_name}"),
                token_id=str(execution_token.get("token_id") or f"token:{case_name}"),
                actuator_endpoint=endpoint_id,
                hardware_uuid="robot-sim-live-signoff-1",
                actuator_result_hash=f"sha256:{_sha256(f'actuator:{case_name}:{task_id}')}",
                target_zone=str(transfer_context.get("to_zone") or "handoff_bay_3"),
                from_zone=str(transfer_context.get("from_zone") or asset_state.get("current_zone_ref") or "vault_a"),
                to_zone=str(transfer_context.get("to_zone") or "handoff_bay_3"),
                executed_at=str(response_payload.get("decided_at") or _now_iso()),
                receipt_nonce=f"nonce:{case_name}:{uuid.uuid4()}",
                workflow_type="restricted_custody_transfer",
            )

        task_governance = _build_task_governance_context(
            task_id=task_id,
            request_payload=request_payload,
            policy_case=policy_case,
            policy_decision=policy_decision,
            policy_receipt=policy_receipt,
        )
        hal_envelope = _build_hal_envelope(
            task_id=task_id,
            case_name=case_name,
            decided_at=str(response_payload.get("decided_at") or _now_iso()),
            disposition=disposition,
            transition_receipt=transition_receipt,
            endpoint_id=endpoint_id,
        )
        evidence_bundle = build_evidence_bundle(
            task_dict=task_governance,
            envelope=hal_envelope,
            organ_id="organism",
            agent_id=str(principal.get("agent_id") or "agent:custody_runtime_01"),
        ).model_dump(mode="json")

        audit_id = loop.run_until_complete(
            _append_audit_record(
                task_id=task_id,
                policy_snapshot=str(response_payload.get("decision", {}).get("policy_snapshot_ref") or request_payload.get("policy_snapshot_ref") or "snapshot:runtime"),
                action_intent=action_intent,
                policy_case=policy_case,
                policy_decision=policy_decision,
                policy_receipt=policy_receipt,
                evidence_bundle=evidence_bundle,
            )
        )
        if disposition == "allow":
            allow_audit_id = audit_id

        runtime_replay = _json_get(f"{runtime_base}/replay?audit_id={audit_id}&projection=internal")
        runtime_verify = _json_post(f"{runtime_base}/verify", {"audit_id": audit_id})
        status_view = _json_get(f"{verify_base}/transfers/status?source=runtime&audit_id={audit_id}")
        forensic_view = _json_get(f"{verify_base}/assets/forensics?source=runtime&audit_id={audit_id}")
        proof_view = _json_get(f"{verify_base}/assets/proof?source=runtime&audit_id={audit_id}")

        rust_artifacts, rust_bundle, rust_verify = loop.run_until_complete(_build_rust_chain_report(audit_id))

        status_transition_ids = _string_list(status_view.get("transition_receipt_ids"))
        forensic_transition_ids = _string_list(forensic_view.get("transition_receipt_ids"))
        expected_transition_ids = _string_list(evidence_bundle.get("transition_receipt_ids"))
        replay_view = runtime_replay.get("view") if isinstance(runtime_replay.get("view"), dict) else {}
        replay_audit_record = replay_view.get("audit_record") if isinstance(replay_view.get("audit_record"), dict) else {}
        replay_action_intent = (
            replay_audit_record.get("action_intent")
            if isinstance(replay_audit_record.get("action_intent"), dict)
            else {}
        )
        replay_approval_context = (
            replay_action_intent.get("action", {}).get("parameters", {}).get("approval_context")
            if isinstance(replay_action_intent.get("action"), dict)
            and isinstance(replay_action_intent.get("action", {}).get("parameters"), dict)
            else {}
        )
        if not isinstance(replay_approval_context, dict):
            replay_approval_context = {}
        replay_policy_receipt = (
            replay_audit_record.get("policy_receipt")
            if isinstance(replay_audit_record.get("policy_receipt"), dict)
            else {}
        )
        replay_transition_ids = [
            str(item.get("transition_receipt_id"))
            for item in replay_view.get("transition_receipts", [])
            if isinstance(item, dict) and item.get("transition_receipt_id") is not None
        ] if isinstance(replay_view.get("transition_receipts"), list) else []
        replay_approval_envelope_id = str(
            replay_approval_context.get("approval_envelope_id")
            or ""
        )
        replay_policy_receipt_id = str(replay_policy_receipt.get("policy_receipt_id") or "")

        consistency_errors: list[str] = []
        if replay_approval_envelope_id != str(approval_current.get("approval_envelope_id") or ""):
            consistency_errors.append("runtime.approval_envelope_id_mismatch")
        if str(forensic_view.get("approval_envelope_id") or "") != replay_approval_envelope_id:
            consistency_errors.append("forensics.approval_envelope_id_mismatch")

        if replay_policy_receipt_id != str(policy_receipt.get("policy_receipt_id") or ""):
            consistency_errors.append("runtime.policy_receipt_id_mismatch")
        if str(forensic_view.get("policy_receipt_id") or "") != replay_policy_receipt_id:
            consistency_errors.append("forensics.policy_receipt_id_mismatch")

        if forensic_transition_ids != expected_transition_ids:
            consistency_errors.append("forensics.transition_receipt_ids_mismatch")
        if replay_transition_ids != expected_transition_ids:
            consistency_errors.append("runtime.transition_receipt_ids_mismatch")

        if str(status_view.get("business_state") or "") != str(forensic_view.get("business_state") or ""):
            consistency_errors.append("status.business_state_mismatch")
        if str(proof_view.get("business_state") or "") != str(forensic_view.get("business_state") or ""):
            consistency_errors.append("proof.business_state_mismatch")

        case_summary = {
            "case": case_name,
            "expected_disposition": expected,
            "actual_disposition": disposition,
            "audit_id": audit_id,
            "approval_envelope_id": (
                status_view.get("approval_envelope_id")
                or forensic_view.get("approval_envelope_id")
            ),
            "approval_envelope_version": (
                status_view.get("approval_envelope_version")
                or forensic_view.get("approval_envelope_version")
            ),
            "approval_binding_hash": (
                status_view.get("approval_binding_hash")
                or forensic_view.get("approval_binding_hash")
            ),
            "policy_receipt_id": (
                status_view.get("policy_receipt_id")
                or forensic_view.get("policy_receipt_id")
            ),
            "transition_receipt_ids": (
                status_transition_ids
                if status_transition_ids
                else forensic_transition_ids
            ),
            "business_state": status_view.get("business_state"),
            "runtime_verify_verified": runtime_verify.get("verified"),
            "runtime_verify_issues": runtime_verify.get("issues"),
            "rust_replay_chain_verified": rust_verify.get("verified"),
            "rust_replay_chain_error": rust_verify.get("error_code"),
            "signature_provenance": forensic_view.get("signature_provenance"),
            "cross_surface_consistent": not consistency_errors,
            "cross_surface_errors": consistency_errors,
        }

        _write_json(case_output / "hot_path_request.json", request_payload)
        _write_json(case_output / "hot_path_response.json", response_payload)
        _write_json(case_output / "approval_current.json", approval_current)
        _write_json(case_output / "runtime_replay.json", runtime_replay)
        _write_json(case_output / "runtime_verify.json", runtime_verify)
        _write_json(case_output / "verification_status.json", status_view)
        _write_json(case_output / "verification_forensics.json", forensic_view)
        _write_json(case_output / "verification_proof.json", proof_view)
        _write_json(case_output / "rust_replay_artifacts.json", {"artifacts": rust_artifacts})
        _write_json(case_output / "rust_replay_bundle.json", rust_bundle)
        _write_json(case_output / "rust_verify_chain.json", rust_verify)
        _write_json(case_output / "summary.json", case_summary)

        case_rows.append(case_summary)

    try:
        if allow_audit_id is None:
            raise RuntimeError("missing_allow_case_audit_id")
        protocol_rc, protocol_output = _run_surface_protocol(allow_audit_id)
        (output_root / "productized_surface_protocol.log").write_text(protocol_output, encoding="utf-8")

        matrix_summary = {
            "captured_at": _now_iso(),
            "runtime_base": runtime_base,
            "verify_base": verify_base,
            "active_snapshot": active_snapshot,
            "allow_audit_id": allow_audit_id,
            "productized_surface_protocol_rc": protocol_rc,
            "cases": case_rows,
        }
        _write_json(output_root / "matrix_summary.json", matrix_summary)

        print(f"capture_dir: {output_root}")
        print(f"active_snapshot: {active_snapshot}")
        print(f"allow_audit_id: {allow_audit_id}")
        print(f"productized_surface_protocol_rc: {protocol_rc}")
        print("cases:")
        for row in case_rows:
            print(
                f"  - {row['case']}: disposition={row['actual_disposition']} "
                f"business_state={row['business_state']} audit_id={row['audit_id']} "
                f"cross_surface_consistent={row['cross_surface_consistent']} rust_chain_verified={row['rust_replay_chain_verified']}"
            )

        if protocol_rc != 0:
            return 1
        if any(not bool(row.get("cross_surface_consistent")) for row in case_rows):
            return 1
        if any(not bool(row.get("rust_replay_chain_verified")) for row in case_rows):
            return 1
        return 0
    finally:
        loop.close()


if __name__ == "__main__":
    raise SystemExit(main())
