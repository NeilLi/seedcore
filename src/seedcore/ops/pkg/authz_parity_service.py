from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from seedcore.coordinator.core.governance import evaluate_intent
from seedcore.models.action_intent import PolicyDecision

from .authz_graph import AuthzGraphProjectionService, CompiledAuthzIndex


PolicyEvaluator = Callable[[Mapping[str, Any]], PolicyDecision]
CompiledPolicyEvaluator = Callable[[Mapping[str, Any], CompiledAuthzIndex], PolicyDecision]


@dataclass(frozen=True)
class AuthzParityFixture:
    name: str
    payload: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedParityDecision:
    allowed: bool
    disposition: str
    reason: str | None
    deny_code: str | None
    break_glass_required: bool
    break_glass_used: bool
    trust_gap_codes: tuple[str, ...]
    snapshot: str | None


@dataclass(frozen=True)
class AuthzParityResult:
    fixture_name: str
    parity_ok: bool
    baseline: NormalizedParityDecision
    candidate: NormalizedParityDecision
    mismatches: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuthzParityReport:
    snapshot_ref: str
    snapshot_id: int | None
    snapshot_version: str | None
    total: int
    parity_ok: int
    mismatched: int
    results: tuple[AuthzParityResult, ...]


def _default_baseline_evaluator(payload: Mapping[str, Any]) -> PolicyDecision:
    return evaluate_intent(dict(payload))


def _default_compiled_evaluator(
    payload: Mapping[str, Any],
    compiled_authz_index: CompiledAuthzIndex,
) -> PolicyDecision:
    return evaluate_intent(dict(payload), compiled_authz_index=compiled_authz_index)


def normalize_policy_decision(decision: PolicyDecision) -> NormalizedParityDecision:
    trust_gap_codes = decision.governed_receipt.get("trust_gap_codes")
    if not trust_gap_codes:
        trust_gap_codes = decision.authz_graph.get("trust_gap_codes")
    codes = tuple(sorted(str(item) for item in (trust_gap_codes or []) if str(item).strip()))
    return NormalizedParityDecision(
        allowed=bool(decision.allowed),
        disposition=str(decision.disposition),
        reason=decision.reason,
        deny_code=decision.deny_code,
        break_glass_required=bool(decision.break_glass.required),
        break_glass_used=bool(decision.break_glass.used),
        trust_gap_codes=codes,
        snapshot=decision.policy_snapshot,
    )


def _diff_decisions(
    baseline: NormalizedParityDecision,
    candidate: NormalizedParityDecision,
) -> tuple[str, ...]:
    mismatches: list[str] = []
    if baseline.allowed != candidate.allowed:
        mismatches.append("allowed")
    if baseline.disposition != candidate.disposition:
        mismatches.append("disposition")
    if baseline.deny_code != candidate.deny_code:
        mismatches.append("deny_code")
    if baseline.reason != candidate.reason:
        mismatches.append("reason")
    if baseline.break_glass_required != candidate.break_glass_required:
        mismatches.append("break_glass_required")
    if baseline.break_glass_used != candidate.break_glass_used:
        mismatches.append("break_glass_used")
    if baseline.trust_gap_codes != candidate.trust_gap_codes:
        mismatches.append("trust_gap_codes")
    if baseline.snapshot != candidate.snapshot:
        mismatches.append("snapshot")
    return tuple(mismatches)


class AuthzParityService:
    """Runs the same governance payloads through baseline and compiled authz paths."""

    def __init__(
        self,
        *,
        projection_service: AuthzGraphProjectionService | None = None,
        baseline_evaluator: PolicyEvaluator | None = None,
        compiled_evaluator: CompiledPolicyEvaluator | None = None,
    ) -> None:
        self.projection_service = projection_service or AuthzGraphProjectionService()
        self.baseline_evaluator = baseline_evaluator or _default_baseline_evaluator
        self.compiled_evaluator = compiled_evaluator or _default_compiled_evaluator

    def compare_fixtures(
        self,
        *,
        compiled_authz_index: CompiledAuthzIndex,
        fixtures: Sequence[AuthzParityFixture | Mapping[str, Any]],
    ) -> AuthzParityReport:
        normalized_fixtures = tuple(self._coerce_fixture(item) for item in fixtures)
        results: list[AuthzParityResult] = []
        for fixture in normalized_fixtures:
            payload = copy.deepcopy(fixture.payload)
            baseline_decision = normalize_policy_decision(self.baseline_evaluator(payload))
            candidate_decision = normalize_policy_decision(
                self.compiled_evaluator(payload, compiled_authz_index)
            )
            mismatches = _diff_decisions(baseline_decision, candidate_decision)
            results.append(
                AuthzParityResult(
                    fixture_name=fixture.name,
                    parity_ok=not mismatches,
                    baseline=baseline_decision,
                    candidate=candidate_decision,
                    mismatches=mismatches,
                    metadata=copy.deepcopy(fixture.metadata),
                )
            )

        parity_ok = sum(1 for item in results if item.parity_ok)
        return AuthzParityReport(
            snapshot_ref=compiled_authz_index.snapshot_ref,
            snapshot_id=compiled_authz_index.snapshot_id,
            snapshot_version=compiled_authz_index.snapshot_version,
            total=len(results),
            parity_ok=parity_ok,
            mismatched=len(results) - parity_ok,
            results=tuple(results),
        )

    async def compare_snapshot(
        self,
        *,
        snapshot_ref: str,
        fixtures: Sequence[AuthzParityFixture | Mapping[str, Any]],
        snapshot_id: int | None = None,
        snapshot_version: str | None = None,
        **projection_kwargs: Any,
    ) -> AuthzParityReport:
        compiled, _ = await self.projection_service.build_compiled_index(
            snapshot_ref=snapshot_ref,
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            **projection_kwargs,
        )
        return self.compare_fixtures(compiled_authz_index=compiled, fixtures=fixtures)

    @staticmethod
    def _coerce_fixture(item: AuthzParityFixture | Mapping[str, Any]) -> AuthzParityFixture:
        if isinstance(item, AuthzParityFixture):
            return item
        payload = dict(item)
        return AuthzParityFixture(
            name=str(payload["name"]),
            payload=copy.deepcopy(payload["payload"]),
            metadata=copy.deepcopy(payload.get("metadata") or {}),
        )
