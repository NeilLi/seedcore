import json
import time
from dataclasses import dataclass
from math import ceil
from typing import Any

import pytest

from seedcore.fixtures.lane1_config import LANE_1_TARGETS


class DynamicTargetDriftError(Exception):
    """Raised when execution time exceeds the sub-millisecond boundary."""


@dataclass(frozen=True)
class CausalityValidation:
    accepted: bool
    reason_code: str | None = None


def _extract_sequence(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    candidate = value.rsplit(":", 1)[-1]
    try:
        return int(candidate)
    except ValueError:
        return None


def evaluate_causality_token_chain(context_envelope: dict[str, Any]) -> CausalityValidation:
    """Execute deterministic causality validation over the fixture envelope."""
    freshness = context_envelope.get("context_freshness")
    if not isinstance(freshness, dict):
        return CausalityValidation(False, "context_freshness_missing")

    token = freshness.get("causality_token")
    local_view_ref = freshness.get("local_view_ref")
    if not isinstance(token, str) or not token.startswith("ctx:"):
        return CausalityValidation(False, "causality_token_invalid")
    if not isinstance(local_view_ref, str) or not local_view_ref.startswith("view:"):
        return CausalityValidation(False, "local_view_ref_invalid")

    token_seq = _extract_sequence(token)
    local_view_seq = _extract_sequence(local_view_ref)
    if token_seq is None or local_view_seq is None:
        return CausalityValidation(False, "context_freshness_sequence_invalid")
    if local_view_seq < token_seq:
        return CausalityValidation(False, "context_freshness_below_required_bound")

    return CausalityValidation(True)


def verify_causality_token(context_envelope: dict[str, Any]) -> tuple[CausalityValidation, float]:
    """Wrap the causality verification loop inside a high-resolution monotonic clock."""
    start_ns = time.perf_counter_ns()
    validation = evaluate_causality_token_chain(context_envelope)
    elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
    return validation, elapsed_ms


def p99_nearest_rank(latencies_ms: list[float]) -> float:
    if not latencies_ms:
        raise ValueError("latencies_ms must not be empty")
    ordered = sorted(latencies_ms)
    index = max(0, ceil(0.99 * len(ordered)) - 1)
    return ordered[index]


def envelope_size_kb(envelopes: list[dict[str, Any]]) -> float:
    if not envelopes:
        return 0.0
    total_bytes = sum(
        len(json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        for envelope in envelopes
    )
    return total_bytes / len(envelopes) / 1024.0


def format_performance_report(
    actual_p99: float,
    parity_rate: float,
    stale_count: int,
    false_positive_count: int,
    avg_envelope_size_kb: float,
) -> str:
    """Format the replay artifact dashboard report for console output."""
    status_str = "PASS" if actual_p99 < float(LANE_1_TARGETS["convergence_p99_max_ms"]) else "FAIL"
    return f"""================================================================================
SEEDCORE LANE 1 PERFORMANCE REPORT (RCT SIMULATOR)
================================================================================
Target P99 Convergence Ceiling : < {LANE_1_TARGETS['convergence_p99_max_ms']:.3f} ms
Actual P99 Convergence Latency : {actual_p99:.3f} ms  [{status_str}]
--------------------------------------------------------------------------------
Replay Parity Rate             : {parity_rate:.1f}%
Stale-Context Blocked Actions  : {stale_count}
False-Positive Quarantine Count: {false_positive_count}
Average Data Envelope Size     : {avg_envelope_size_kb:.1f} KB
================================================================================"""


def _valid_context_envelope() -> dict[str, Any]:
    return {
        "context_freshness": {
            "causality_token": "ctx:approval-transfer-001:000042",
            "minimum_observed_at": "2026-04-02T08:00:12Z",
            "local_view_ref": "view:rct-edge-handoff-bay-3:000042",
        }
    }


@pytest.mark.rct_degraded_edge
def test_lane_1_causality_validator_fails_closed_for_stale_local_view() -> None:
    stale_context = _valid_context_envelope()
    stale_context["context_freshness"]["local_view_ref"] = "view:rct-edge-handoff-bay-3:000041"

    validation = evaluate_causality_token_chain(stale_context)

    assert validation == CausalityValidation(
        accepted=False,
        reason_code="context_freshness_below_required_bound",
    )


@pytest.mark.rct_degraded_edge
def test_lane_1_freshness_convergence_under_ceiling() -> None:
    context_envelope = _valid_context_envelope()
    runs = int(LANE_1_TARGETS["sample_count"])
    latencies: list[float] = []

    for _ in range(runs):
        validation, elapsed_ms = verify_causality_token(context_envelope)
        assert validation.accepted is True
        latencies.append(elapsed_ms)

    p99_latency = p99_nearest_rank(latencies)
    scenario_envelopes = [
        context_envelope,
        {
            "context_freshness": {
                "causality_token": "ctx:approval-transfer-001:000042",
                "minimum_observed_at": "2026-04-02T08:00:12Z",
                "local_view_ref": "view:rct-edge-handoff-bay-3:000041",
            }
        },
        {
            "context_freshness": {
                "causality_token": "not-a-seedcore-token",
                "local_view_ref": "view:rct:000042",
            }
        },
    ]
    expected_acceptance = [True, False, False]
    scenario_results = [evaluate_causality_token_chain(envelope) for envelope in scenario_envelopes]
    parity_ok = sum(
        result.accepted == expected
        for result, expected in zip(scenario_results, expected_acceptance)
    )
    stale_count = sum(result.reason_code == "context_freshness_below_required_bound" for result in scenario_results)
    false_positive_count = sum(
        not result.accepted
        for result, expected in zip(scenario_results, expected_acceptance)
        if expected
    )

    report = format_performance_report(
        actual_p99=p99_latency,
        parity_rate=(parity_ok / len(scenario_results)) * 100.0,
        stale_count=stale_count,
        false_positive_count=false_positive_count,
        avg_envelope_size_kb=envelope_size_kb(scenario_envelopes),
    )
    print("\n" + report)

    if p99_latency >= LANE_1_TARGETS["convergence_p99_max_ms"]:
        raise DynamicTargetDriftError(
            f"Local freshness convergence latency p99={p99_latency:.3f} ms drifted "
            f"beyond the sub-millisecond target boundary (< {LANE_1_TARGETS['convergence_p99_max_ms']} ms)."
        )
    assert parity_ok == len(scenario_results)
    assert stale_count == 1
    assert false_positive_count == 0
