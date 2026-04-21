#!/usr/bin/env python3
"""Verify admission-contract evidence for critical side-effecting SeedCore components."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Evidence:
    path: str
    pattern: str
    reason: str


@dataclass(frozen=True)
class Clause:
    name: str
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class ComponentSpec:
    component: str
    clauses: tuple[Clause, ...]


@dataclass
class ClauseResult:
    name: str
    ok: bool
    detail: dict[str, object]


@dataclass
class ComponentResult:
    component: str
    ok: bool
    clauses: list[ClauseResult]


COMPONENT_SPECS: tuple[ComponentSpec, ...] = (
    ComponentSpec(
        component="agent_action_gateway_boundary",
        clauses=(
            Clause(
                name="formal_contract_declared",
                evidence=(
                    Evidence(
                        path="src/seedcore/api/routers/agent_actions_router.py",
                        pattern=r'@router\.post\("/agent-actions/evaluate"',
                        reason="gateway evaluate endpoint exists at canonical runtime boundary",
                    ),
                    Evidence(
                        path="tests/test_agent_actions_router.py",
                        pattern=r"seedcore\.agent_action_gateway\.v1",
                        reason="contract version asserted in tests",
                    ),
                ),
            ),
            Clause(
                name="token_requirement_is_enforced",
                evidence=(
                    Evidence(
                        path="src/seedcore/api/routers/agent_actions_router.py",
                        pattern=r"mint_execution_token_with_rust",
                        reason="execution token minted through authority path",
                    ),
                    Evidence(
                        path="src/seedcore/api/routers/agent_actions_router.py",
                        pattern=r"execution_token",
                        reason="execution token propagated in evaluation pipeline",
                    ),
                ),
            ),
            Clause(
                name="signed_receipt_and_evidence_linkage",
                evidence=(
                    Evidence(
                        path="src/seedcore/api/routers/agent_actions_router.py",
                        pattern=r"policy_receipt",
                        reason="policy receipt materialized in gateway flow",
                    ),
                    Evidence(
                        path="src/seedcore/api/routers/agent_actions_router.py",
                        pattern=r"evidence_bundle",
                        reason="evidence bundle linkage present in gateway flow",
                    ),
                ),
            ),
            Clause(
                name="replay_correlation_and_idempotency_tests",
                evidence=(
                    Evidence(
                        path="scripts/host/verify_agent_action_gateway_productization_real_calls.py",
                        pattern=r"/api/v1/replay",
                        reason="host verifier checks replay correlation surfaces",
                    ),
                    Evidence(
                        path="tests/test_agent_actions_router.py",
                        pattern=r"idempotency_conflict",
                        reason="idempotency conflict behavior covered by tests",
                    ),
                ),
            ),
        ),
    ),
    ComponentSpec(
        component="hal_execution_boundary",
        clauses=(
            Clause(
                name="execution_boundary_declared",
                evidence=(
                    Evidence(
                        path="src/seedcore/hal/service/main.py",
                        pattern=r'@app\.post\("/actuate"\)',
                        reason="single actuation boundary endpoint is explicit",
                    ),
                    Evidence(
                        path="scripts/host/verify_zero_trust_boundaries.py",
                        pattern=r"boundary\.no_execution_without_authorization",
                        reason="host boundary verifier checks deny-by-default execution",
                    ),
                ),
            ),
            Clause(
                name="token_validation_is_fail_closed",
                evidence=(
                    Evidence(
                        path="src/seedcore/hal/service/main.py",
                        pattern=r"def _validate_execution_token\(",
                        reason="explicit token validation function exists",
                    ),
                    Evidence(
                        path="src/seedcore/hal/service/main.py",
                        pattern=r"invalid ExecutionToken",
                        reason="invalid token path returns fail-closed denial",
                    ),
                ),
            ),
            Clause(
                name="signed_transition_receipt_emission",
                evidence=(
                    Evidence(
                        path="src/seedcore/hal/service/main.py",
                        pattern=r"build_transition_receipt",
                        reason="transition receipts are built for actuation outcomes",
                    ),
                    Evidence(
                        path="src/seedcore/hal/service/main.py",
                        pattern=r"_build_actuation_transition_receipt",
                        reason="canonical receipt build path is retained",
                    ),
                ),
            ),
            Clause(
                name="boundary_replay_tests_exist",
                evidence=(
                    Evidence(
                        path="tests/test_zero_trust_boundaries.py",
                        pattern=r"ExecutionToken endpoint mismatch",
                        reason="endpoint binding mismatch is asserted in tests",
                    ),
                    Evidence(
                        path="scripts/host/verify_zero_trust_boundaries.py",
                        pattern=r"boundary\.no_policy_bypass_endpoint_mismatch",
                        reason="host verifier asserts endpoint mismatch fail-closed behavior",
                    ),
                ),
            ),
        ),
    ),
    ComponentSpec(
        component="governed_tools_mutation_manager",
        clauses=(
            Clause(
                name="governed_mutation_gate_exists",
                evidence=(
                    Evidence(
                        path="src/seedcore/tools/manager.py",
                        pattern=r"Governance gate for governed mutations",
                        reason="governed mutation gate is explicitly implemented",
                    ),
                    Evidence(
                        path="src/seedcore/tools/manager.py",
                        pattern=r"contract\.is_mutating\(\)",
                        reason="mutation contracts are used to gate side effects",
                    ),
                ),
            ),
            Clause(
                name="token_and_receipt_validation",
                evidence=(
                    Evidence(
                        path="src/seedcore/tools/manager.py",
                        pattern=r"verify_transition_receipt",
                        reason="transition receipt validation is enforced",
                    ),
                    Evidence(
                        path="src/seedcore/tools/manager.py",
                        pattern=r"missing_transition_receipt",
                        reason="missing transition receipts hard-fail mutation paths",
                    ),
                ),
            ),
            Clause(
                name="signed_receipt_chain_persistence",
                evidence=(
                    Evidence(
                        path="src/seedcore/tools/manager.py",
                        pattern=r"_persist_governance_audit_record",
                        reason="governance audit persistence path is explicit",
                    ),
                    Evidence(
                        path="src/seedcore/tools/manager.py",
                        pattern=r'authority_source = "governed_transition_receipt"',
                        reason="custody authority source pinned to governed transition receipts",
                    ),
                ),
            ),
            Clause(
                name="lineage_and_evidence_tests_exist",
                evidence=(
                    Evidence(
                        path="tests/test_governed_closure.py",
                        pattern=r'update\["authority_source"\] == "governed_transition_receipt"',
                        reason="governed closure test checks custody authority propagation",
                    ),
                    Evidence(
                        path="tests/test_governed_closure.py",
                        pattern=r'"evidence_bundle"',
                        reason="governed closure tests assert evidence bundle linkage",
                    ),
                ),
            ),
        ),
    ),
    ComponentSpec(
        component="replay_and_custody_trust_surfaces",
        clauses=(
            Clause(
                name="replay_from_artifacts_boundary",
                evidence=(
                    Evidence(
                        path="src/seedcore/services/replay_service.py",
                        pattern=r"async def assemble_replay_record\(",
                        reason="replay service assembles deterministic replay records from artifacts",
                    ),
                    Evidence(
                        path="tests/test_replay_service.py",
                        pattern=r"test_replay_includes_custody_transition_and_dispute_refs",
                        reason="replay test asserts custody/dispute linkage surfaces",
                    ),
                ),
            ),
            Clause(
                name="time_and_id_injection_support",
                evidence=(
                    Evidence(
                        path="src/seedcore/services/replay_service.py",
                        pattern=r"self\._clock",
                        reason="replay service supports injected clock",
                    ),
                    Evidence(
                        path="src/seedcore/services/replay_service.py",
                        pattern=r"self\._id_generator",
                        reason="replay service supports injected id generator",
                    ),
                    Evidence(
                        path="tests/test_replay_service.py",
                        pattern=r"test_replay_service_supports_injected_clock_and_id_generator",
                        reason="injected clock/id behavior asserted by tests",
                    ),
                    Evidence(
                        path="tests/test_custody_graph_service.py",
                        pattern=r"test_open_dispute_supports_injected_id_generator",
                        reason="custody graph injected id behavior asserted by tests",
                    ),
                ),
            ),
            Clause(
                name="stable_output_replay_tests",
                evidence=(
                    Evidence(
                        path="tests/test_replay_service.py",
                        pattern=r"test_replay_timeline_fallback_event_ids_are_deterministic",
                        reason="timeline fallback ids are asserted deterministic",
                    ),
                    Evidence(
                        path="scripts/host/verify_execution_spine.py",
                        pattern=r"spine\.verification_surface_projection_current_equivalent",
                        reason="execution spine verifier asserts replay/trust-surface coherence",
                    ),
                ),
            ),
        ),
    ),
)


def _load_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def _search(path: Path, pattern: str) -> tuple[bool, str]:
    if not path.exists():
        return False, "file_missing"
    text = _load_text(path)
    match = re.search(pattern, text, flags=re.MULTILINE)
    if match is None:
        return False, "pattern_missing"
    line = text.count("\n", 0, match.start()) + 1
    return True, f"line:{line}"


def _evaluate_clause(clause: Clause) -> ClauseResult:
    evidence_results: list[dict[str, object]] = []
    ok = True
    for item in clause.evidence:
        file_path = PROJECT_ROOT / item.path
        matched, detail = _search(file_path, item.pattern)
        evidence_results.append(
            {
                "path": item.path,
                "pattern": item.pattern,
                "reason": item.reason,
                "matched": matched,
                "detail": detail,
            }
        )
        if not matched:
            ok = False
    return ClauseResult(
        name=clause.name,
        ok=ok,
        detail={"evidence": evidence_results},
    )


def _evaluate_component(spec: ComponentSpec) -> ComponentResult:
    clause_results = [_evaluate_clause(clause) for clause in spec.clauses]
    ok = all(result.ok for result in clause_results)
    return ComponentResult(component=spec.component, ok=ok, clauses=clause_results)


def _flatten_failed(results: Iterable[ComponentResult]) -> list[tuple[str, ClauseResult]]:
    failed: list[tuple[str, ClauseResult]] = []
    for component in results:
        for clause in component.clauses:
            if not clause.ok:
                failed.append((component.component, clause))
    return failed


def main() -> int:
    results = [_evaluate_component(spec) for spec in COMPONENT_SPECS]
    failed = _flatten_failed(results)

    for component in results:
        marker = "PASS" if component.ok else "FAIL"
        print(f"[{marker}] component.{component.component}")
        for clause in component.clauses:
            clause_marker = "PASS" if clause.ok else "FAIL"
            print(f"  [{clause_marker}] {clause.name}")
            if not clause.ok:
                for evidence in clause.detail.get("evidence", []):
                    if isinstance(evidence, dict) and not evidence.get("matched"):
                        print(
                            "    - missing: "
                            + json.dumps(
                                {
                                    "path": evidence.get("path"),
                                    "reason": evidence.get("reason"),
                                    "detail": evidence.get("detail"),
                                },
                                sort_keys=True,
                            )
                        )

    summary = {
        "components_total": len(results),
        "components_passed": sum(1 for item in results if item.ok),
        "components_failed": sum(1 for item in results if not item.ok),
        "clauses_failed": len(failed),
    }
    print(json.dumps({"summary": summary}, sort_keys=True))

    if failed:
        print(
            f"\nAdmission-contract inventory verification failed: {len(failed)} clauses failed.",
            file=sys.stderr,
        )
        return 1

    print("\nAdmission-contract inventory verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
