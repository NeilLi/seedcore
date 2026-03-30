#!/usr/bin/env python3
"""Benchmark and verify the current Rust-backed governed execution flow."""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
TESTS_ROOT = PROJECT_ROOT / "tests"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from seedcore.coordinator.core import governance as governance_mod  # noqa: E402
from seedcore.coordinator.core.governance import build_governance_context, evaluate_intent  # noqa: E402
from seedcore.hal.custody.transition_receipts import build_transition_receipt  # noqa: E402
from seedcore.integrations.rust_kernel import (  # noqa: E402
    apply_transfer_approval_transition_with_rust,
    mint_execution_token_with_rust,
    seal_replay_bundle_with_rust,
    summarize_transfer_approval_with_rust,
    validate_transfer_approval_with_rust,
    verify_execution_token_with_rust,
    verify_replay_bundle_with_rust,
)
from seedcore.ops.evidence.builder import build_evidence_bundle  # noqa: E402
from seedcore.services.replay_service import ReplayService  # noqa: E402
from test_action_intent import _compiled_transfer_graph, _transfer_approval_envelope, _transfer_payload  # noqa: E402


@dataclass
class BenchStat:
    name: str
    iterations: int
    min_ms: float
    p50_ms: float
    p95_ms: float
    avg_ms: float
    detail: dict[str, Any]


def _bench(name: str, fn: Callable[[], Any], *, iterations: int) -> tuple[BenchStat, Any]:
    samples: list[float] = []
    last_result: Any = None
    for _ in range(iterations):
        started = time.perf_counter()
        last_result = fn()
        samples.append((time.perf_counter() - started) * 1000.0)
    ordered = sorted(samples)
    p50 = ordered[len(ordered) // 2]
    p95 = ordered[min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))]
    stat = BenchStat(
        name=name,
        iterations=iterations,
        min_ms=min(ordered),
        p50_ms=p50,
        p95_ms=p95,
        avg_ms=statistics.fmean(ordered),
        detail={},
    )
    return stat, last_result


def _build_transfer_case() -> tuple[dict[str, Any], Any]:
    now = datetime(2099, 3, 20, 12, 0, 0, tzinfo=timezone.utc)
    payload = _transfer_payload()
    payload["task_id"] = "task-rust-benchmark"
    action_intent = payload["params"]["governance"]["action_intent"]
    action_intent["intent_id"] = "intent-rust-benchmark"
    action_intent["action"]["parameters"]["endpoint_id"] = "robot_sim://unit-1"
    compiled = _compiled_transfer_graph(
        now=now,
        telemetry_at=now - timedelta(minutes=1),
        inspection_at=now - timedelta(minutes=2),
        current_custodian="facility_mgr_001",
    )
    return payload, compiled


def _make_transition_envelope(action_intent: Mapping[str, Any], policy_snapshot: str) -> dict[str, Any]:
    envelope = _transfer_approval_envelope()
    envelope["policy_snapshot_ref"] = policy_snapshot
    envelope["asset_ref"] = str(action_intent.get("resource", {}).get("asset_id") or envelope["asset_ref"])
    return envelope


def _make_transition_apply_inputs(envelope: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    pending = dict(envelope)
    pending["status"] = "PARTIALLY_APPROVED"
    pending["version"] = 1
    required = list(pending.get("required_approvals") or [])
    if len(required) >= 2:
        required[1] = {
            **dict(required[1]),
            "status": "PENDING",
            "approved_at": None,
        }
    pending["required_approvals"] = required
    transition = {
        "type": "add_approval",
        "role": "QUALITY_INSPECTOR",
        "principal_ref": "principal:quality_insp_017",
        "approval_ref": "approval:quality_insp_017",
        "approved_at": "2099-03-20T12:00:03+00:00",
    }
    return pending, transition


def _build_replay_bundle_inputs(governance_ctx: Mapping[str, Any]) -> dict[str, Any]:
    transition_receipt = build_transition_receipt(
        intent_id=governance_ctx["action_intent"]["intent_id"],
        token_id=governance_ctx["execution_token"]["token_id"],
        actuator_endpoint="robot_sim://unit-1",
        hardware_uuid="robot-1",
        actuator_result_hash="actuator-hash-rust-benchmark",
        from_zone="vault-a",
        to_zone="handoff-bay-3",
        target_zone="handoff-bay-3",
        executed_at="2026-03-20T10:01:00+00:00",
        receipt_nonce="nonce-rust-benchmark",
    )
    envelope = {
        "task_id": "task-rust-benchmark",
        "success": True,
        "payload": {
            "result": {"status": "executed"},
            "results": [
                {
                    "output": {
                        "transition_receipt": transition_receipt,
                        "actuator_endpoint": "robot_sim://unit-1",
                        "result_hash": "actuator-hash-rust-benchmark",
                    }
                }
            ],
        },
        "meta": {"exec": {"finished_at": "2026-03-20T10:03:00+00:00"}},
    }
    task_dict = {
        "task_id": "task-rust-benchmark",
        "params": {
            "governance": dict(governance_ctx),
            "routing": {"target_organ_hint": "organism"},
        },
    }
    evidence_bundle = build_evidence_bundle(
        task_dict=task_dict,
        envelope=envelope,
        organ_id="organism",
        agent_id="agent-1",
    ).model_dump(mode="json")
    return {
        "transition_receipt": transition_receipt,
        "evidence_bundle": evidence_bundle,
    }


def main() -> int:
    iterations = int(os.getenv("SEEDCORE_RUST_BENCH_ITERS", "25"))
    os.environ.setdefault("SEEDCORE_PDP_USE_AUTHZ_GRAPH_TRANSITIONS", "true")

    payload, compiled = _build_transfer_case()
    authoritative_approval_envelope = _transfer_approval_envelope()

    rust_original = os.getenv("SEEDCORE_PDP_USE_RUST_POLICY_CORE_TRANSFER")

    def run_rust_policy_core() -> Any:
        os.environ["SEEDCORE_PDP_USE_RUST_POLICY_CORE_TRANSFER"] = "true"
        policy_case = governance_mod.prepare_policy_case(
            payload,
            authoritative_approval_envelope=authoritative_approval_envelope,
        )
        return evaluate_intent(policy_case, compiled_authz_index=compiled)

    def run_compiled_only() -> Any:
        os.environ["SEEDCORE_PDP_USE_RUST_POLICY_CORE_TRANSFER"] = "false"
        policy_case = governance_mod.prepare_policy_case(
            payload,
            authoritative_approval_envelope=authoritative_approval_envelope,
        )
        return evaluate_intent(policy_case, compiled_authz_index=compiled)

    rust_stat, rust_decision = _bench("pdp.restricted_transfer_rust_policy_core", run_rust_policy_core, iterations=iterations)
    compiled_stat, compiled_decision = _bench("pdp.restricted_transfer_compiled_graph", run_compiled_only, iterations=iterations)

    if rust_original is None:
        os.environ.pop("SEEDCORE_PDP_USE_RUST_POLICY_CORE_TRANSFER", None)
    else:
        os.environ["SEEDCORE_PDP_USE_RUST_POLICY_CORE_TRANSFER"] = rust_original

    if not rust_decision.allowed or rust_decision.disposition != "allow":
        print("Rust policy-core flow did not produce the expected allow decision.", file=sys.stderr)
        return 1
    if not compiled_decision.allowed or compiled_decision.disposition != "allow":
        print("Compiled-graph flow did not produce the expected allow decision.", file=sys.stderr)
        return 1

    rust_stat.detail = {
        "reason": rust_decision.reason,
        "workflow_type": rust_decision.authz_graph.get("workflow_type"),
        "evaluator": rust_decision.authz_graph.get("evaluator"),
        "governed_receipt_hash": rust_decision.governed_receipt.get("decision_hash"),
    }
    compiled_stat.detail = {
        "reason": compiled_decision.reason,
        "workflow_type": compiled_decision.authz_graph.get("workflow_type"),
        "evaluator": compiled_decision.authz_graph.get("evaluator"),
        "governed_receipt_hash": compiled_decision.governed_receipt.get("decision_hash"),
    }

    governance_ctx = build_governance_context(
        payload,
        compiled_authz_index=compiled,
        authoritative_approval_envelope=authoritative_approval_envelope,
    )
    approval_envelope = _make_transition_envelope(
        governance_ctx["action_intent"],
        governance_ctx["policy_decision"]["policy_snapshot"],
    )
    pending_envelope, approval_transition = _make_transition_apply_inputs(approval_envelope)

    token_claims = {
        "token_id": "bench-token-rust",
        "intent_id": governance_ctx["action_intent"]["intent_id"],
        "issued_at": "2099-03-20T12:00:00Z",
        "valid_until": "2099-03-20T12:01:00Z",
        "contract_version": governance_ctx["policy_decision"]["policy_snapshot"],
        "constraints": dict(governance_ctx["execution_token"]["constraints"]),
    }
    mint_stat, minted_token = _bench(
        "rust.mint_execution_token",
        lambda: mint_execution_token_with_rust(token_claims),
        iterations=iterations,
    )
    verify_stat, verify_token = _bench(
        "rust.verify_execution_token",
        lambda: verify_execution_token_with_rust(governance_ctx["execution_token"]),
        iterations=iterations,
    )
    summary_stat, summary_result = _bench(
        "rust.summarize_transfer_approval",
        lambda: summarize_transfer_approval_with_rust(approval_envelope),
        iterations=iterations,
    )
    validate_stat, validate_result = _bench(
        "rust.validate_transfer_approval",
        lambda: validate_transfer_approval_with_rust(approval_envelope),
        iterations=iterations,
    )
    apply_stat, apply_result = _bench(
        "rust.apply_transfer_approval_transition",
        lambda: apply_transfer_approval_transition_with_rust(
            pending_envelope,
            approval_transition,
            history={"events": [], "chain_head": None},
            now=datetime(2099, 3, 20, 12, 0, 3, tzinfo=timezone.utc),
        ),
        iterations=iterations,
    )

    replay_inputs = _build_replay_bundle_inputs(governance_ctx)
    replay_record = {
        "intent_id": governance_ctx["action_intent"]["intent_id"],
        "token_id": governance_ctx["execution_token"]["token_id"],
        "policy_snapshot": governance_ctx["policy_decision"]["policy_snapshot"],
        "action_intent": governance_ctx["action_intent"],
        "policy_decision": governance_ctx["policy_decision"],
        "policy_receipt": governance_ctx["policy_receipt"],
        "evidence_bundle": replay_inputs["evidence_bundle"],
        "actor_agent_id": "agent-1",
        "actor_organ_id": "organism",
    }
    replay_service = ReplayService(
        governance_audit_dao=object(),
        digital_twin_dao=object(),
        asset_custody_dao=object(),
    )
    rust_replay_artifacts = replay_service._build_rust_replay_artifacts(  # noqa: SLF001 - benchmark current production conversion
        record=replay_record,
        policy_receipt=governance_ctx["policy_receipt"],
        evidence_bundle=replay_inputs["evidence_bundle"],
        transition_receipts=[replay_inputs["transition_receipt"]],
        approval_context={},
    )
    seal_stat, sealed_bundle = _bench(
        "rust.seal_replay_bundle",
        lambda: seal_replay_bundle_with_rust(rust_replay_artifacts),
        iterations=iterations,
    )
    verify_chain_stat, verify_chain = _bench(
        "rust.verify_replay_bundle",
        lambda: verify_replay_bundle_with_rust(sealed_bundle),
        iterations=iterations,
    )

    checks = [
        ("mint", isinstance(minted_token, Mapping) and minted_token.get("token_id") is not None, minted_token),
        ("verify_token", bool(verify_token.get("verified")), verify_token),
        ("approval_summary", bool(summary_result.get("valid")) and summary_result.get("co_signed") is True, summary_result),
        ("approval_validate", bool(validate_result.get("valid")), validate_result),
        (
            "approval_apply_transition",
            bool(apply_result.get("valid"))
            and isinstance(apply_result.get("approval_envelope"), Mapping)
            and apply_result["approval_envelope"].get("status") == "APPROVED",
            apply_result,
        ),
        (
            "replay_verify_chain",
            bool(verify_chain.get("verified"))
            and isinstance(verify_chain.get("artifact_reports"), list)
            and len(verify_chain["artifact_reports"]) >= 6,
            verify_chain,
        ),
    ]
    failed = [name for name, ok, _ in checks if not ok]
    if failed:
        print(f"Rust flow verification failed: {failed}", file=sys.stderr)
        return 1

    for stat in (rust_stat, compiled_stat, mint_stat, verify_stat, summary_stat, validate_stat, apply_stat, seal_stat, verify_chain_stat):
        print(
            "[BENCH] "
            f"{stat.name}: "
            f"{json.dumps({'iterations': stat.iterations, 'min_ms': round(stat.min_ms, 3), 'p50_ms': round(stat.p50_ms, 3), 'p95_ms': round(stat.p95_ms, 3), 'avg_ms': round(stat.avg_ms, 3), **stat.detail}, sort_keys=True)}"
        )

    print(
        "[ANALYSIS] "
        + json.dumps(
            {
                "rust_policy_core_working": True,
                "compiled_graph_working": True,
                "token_mint_rust_working": True,
                "approval_summary_rust_working": True,
                "approval_transition_rust_working": True,
                "replay_chain_rust_working": True,
                "delta_avg_ms_rust_minus_compiled": round(rust_stat.avg_ms - compiled_stat.avg_ms, 3),
                "rust_reason": rust_decision.reason,
                "compiled_reason": compiled_decision.reason,
                "rust_governed_receipt_hash": rust_decision.governed_receipt.get("decision_hash"),
                "compiled_governed_receipt_hash": compiled_decision.governed_receipt.get("decision_hash"),
            },
            sort_keys=True,
        )
    )
    print("\nRust flow benchmark passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
