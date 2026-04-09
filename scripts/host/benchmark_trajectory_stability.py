#!/usr/bin/env python3
"""Trajectory-stability benchmark scaffold (optional host lane).

This script intentionally ships as a lightweight, extensible scaffold:
- perturbation adapters (real + placeholder)
- trajectory trace schema
- divergence metric (trace distance + outcome parity)
- stable JSON artifact contract for CI/dashboard ingestion
"""

from __future__ import annotations

import argparse
import json
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple


DEFAULT_ARTIFACT_DIR = Path(".local-runtime/trajectory_stability")


@dataclass(frozen=True)
class PerturbationAdapter:
    name: str
    apply: Callable[[Dict[str, Any]], Dict[str, Any]]
    placeholder: bool = False


def _memory_order_shuffle(sample: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(sample)
    memory_items = list(out.get("memory_items") or [])
    if len(memory_items) > 1:
        shuffled = list(memory_items)
        random.shuffle(shuffled)
        out["memory_items"] = shuffled
    return out


def _observation_paraphrase_placeholder(sample: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(sample)
    obs = str(out.get("observation") or "")
    out["observation"] = f"{obs} [paraphrase-placeholder]"
    return out


def _irrelevant_context_injection_placeholder(sample: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(sample)
    noise = list(out.get("irrelevant_context") or [])
    noise.append("placeholder-noise-token")
    out["irrelevant_context"] = noise
    return out


def _build_adapter_registry() -> Dict[str, PerturbationAdapter]:
    return {
        "memory_order_shuffle": PerturbationAdapter(
            name="memory_order_shuffle",
            apply=_memory_order_shuffle,
            placeholder=False,
        ),
        "observation_paraphrase": PerturbationAdapter(
            name="observation_paraphrase",
            apply=_observation_paraphrase_placeholder,
            placeholder=True,
        ),
        "irrelevant_context_injection": PerturbationAdapter(
            name="irrelevant_context_injection",
            apply=_irrelevant_context_injection_placeholder,
            placeholder=True,
        ),
    }


def _stable_action_trace(sample: Dict[str, Any]) -> List[str]:
    """Deterministic trace generator scaffold.

    In follow-up tranches, replace this with real agent/tool traces.
    """
    observation = str(sample.get("observation") or "")
    memory_items = list(sample.get("memory_items") or [])
    memory_order_fingerprint = ",".join(str(item) for item in memory_items[:8])
    steps = [
        f"observe:{observation[:48]}",
        f"memory_count:{len(memory_items)}",
        f"memory_order:{memory_order_fingerprint}",
        "reason:placeholder",
    ]
    if sample.get("irrelevant_context"):
        steps.append(f"noise_count:{len(sample.get('irrelevant_context') or [])}")
    steps.append("decide:allow")
    return steps


def _trace_distance(baseline: List[str], perturbed: List[str]) -> float:
    max_len = max(len(baseline), len(perturbed))
    if max_len == 0:
        return 0.0
    mismatches = 0
    for i in range(max_len):
        b = baseline[i] if i < len(baseline) else None
        p = perturbed[i] if i < len(perturbed) else None
        if b != p:
            mismatches += 1
    return mismatches / float(max_len)


def compute_divergence_metrics(
    baseline_trace: List[str],
    perturbed_trace: List[str],
    baseline_outcome: str,
    perturbed_outcome: str,
) -> Dict[str, Any]:
    dist = _trace_distance(baseline_trace, perturbed_trace)
    outcome_parity = baseline_outcome == perturbed_outcome
    return {
        "trace_distance": round(dist, 6),
        "outcome_parity": outcome_parity,
        "trajectory_diverged": dist > 0.0,
    }


def _sample_task(index: int) -> Dict[str, Any]:
    return {
        "task_id": f"traj-task-{index}",
        "observation": f"Resolve scoped workflow issue #{index}",
        "memory_items": [f"m-{index}-a", f"m-{index}-b", f"m-{index}-c"],
    }


def run_benchmark(
    *,
    perturbations: List[str],
    runs: int,
    artifact_dir: Path,
    divergence_threshold: float,
) -> Dict[str, Any]:
    registry = _build_adapter_registry()
    unknown = [name for name in perturbations if name not in registry]
    if unknown:
        raise ValueError(f"Unknown perturbations: {unknown}")

    selected = [registry[name] for name in perturbations]
    records: List[Dict[str, Any]] = []

    for i in range(runs):
        base_input = _sample_task(i)
        baseline_trace = _stable_action_trace(base_input)
        baseline_outcome = "success"
        for adapter in selected:
            perturbed_input = adapter.apply(base_input)
            perturbed_trace = _stable_action_trace(perturbed_input)
            perturbed_outcome = "success"
            metrics = compute_divergence_metrics(
                baseline_trace=baseline_trace,
                perturbed_trace=perturbed_trace,
                baseline_outcome=baseline_outcome,
                perturbed_outcome=perturbed_outcome,
            )
            records.append(
                {
                    "task_id": base_input["task_id"],
                    "perturbation": adapter.name,
                    "placeholder_adapter": adapter.placeholder,
                    "baseline": {
                        "trace": baseline_trace,
                        "outcome": baseline_outcome,
                    },
                    "perturbed": {
                        "trace": perturbed_trace,
                        "outcome": perturbed_outcome,
                    },
                    "metrics": metrics,
                }
            )

    if records:
        avg_trace_distance = sum(r["metrics"]["trace_distance"] for r in records) / len(records)
        outcome_parity_rate = (
            sum(1 for r in records if r["metrics"]["outcome_parity"]) / float(len(records))
        )
    else:
        avg_trace_distance = 0.0
        outcome_parity_rate = 1.0

    summary = {
        "runs": runs,
        "perturbations": perturbations,
        "records": len(records),
        "avg_trace_distance": round(avg_trace_distance, 6),
        "outcome_parity_rate": round(outcome_parity_rate, 6),
        "divergence_threshold": divergence_threshold,
        "threshold_exceeded": avg_trace_distance > divergence_threshold,
    }

    artifact = {
        "schema_version": "trajectory_stability.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "benchmark": "trajectory_stability_scaffold",
        "summary": summary,
        "records": records,
    }

    artifact_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    artifact_path = artifact_dir / f"trajectory_stability_{ts}.json"
    artifact_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    artifact["artifact_path"] = str(artifact_path)
    return artifact


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--perturbations",
        type=str,
        default="memory_order_shuffle,observation_paraphrase,irrelevant_context_injection",
        help="Comma-separated perturbation adapters.",
    )
    parser.add_argument("--runs", type=int, default=5, help="Number of baseline runs.")
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=DEFAULT_ARTIFACT_DIR,
        help="Directory for JSON artifacts.",
    )
    parser.add_argument(
        "--divergence-threshold",
        type=float,
        default=0.15,
        help="Average trace-distance threshold for reporting.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    perturbations = [part.strip() for part in args.perturbations.split(",") if part.strip()]
    artifact = run_benchmark(
        perturbations=perturbations,
        runs=max(1, int(args.runs)),
        artifact_dir=args.artifact_dir,
        divergence_threshold=float(args.divergence_threshold),
    )
    print("[SUMMARY] " + json.dumps(artifact["summary"], sort_keys=True))
    print(f"[ARTIFACT] {artifact['artifact_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
