from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
import pytest


_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "host"
    / "benchmark_trajectory_stability.py"
)
_SPEC = importlib.util.spec_from_file_location("benchmark_trajectory_stability", _SCRIPT_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)


def test_artifact_schema_contract(tmp_path):
    artifact = _MODULE.run_benchmark(
        perturbations=[
            "memory_order_shuffle",
            "observation_paraphrase",
            "irrelevant_context_injection",
        ],
        runs=2,
        artifact_dir=tmp_path,
        divergence_threshold=0.1,
    )
    assert artifact["schema_version"] == "trajectory_stability.v1"
    assert artifact["benchmark"] == "trajectory_stability_scaffold"
    assert isinstance(artifact["summary"], dict)
    assert isinstance(artifact["records"], list)
    assert Path(artifact["artifact_path"]).exists()


def test_divergence_calculator_deterministic_synthetic_traces():
    metrics = _MODULE.compute_divergence_metrics(
        baseline_trace=["a", "b", "c"],
        perturbed_trace=["a", "x", "c"],
        baseline_outcome="success",
        perturbed_outcome="success",
    )
    assert metrics["trace_distance"] == pytest.approx(1.0 / 3.0, rel=1e-6)
    assert metrics["outcome_parity"] is True
    assert metrics["trajectory_diverged"] is True


def test_perturbation_adapter_registration_and_dispatch():
    registry = _MODULE._build_adapter_registry()
    assert "memory_order_shuffle" in registry
    assert "observation_paraphrase" in registry
    assert "irrelevant_context_injection" in registry

    sample = {"observation": "obs", "memory_items": ["a", "b"], "irrelevant_context": []}
    out = registry["irrelevant_context_injection"].apply(sample)
    assert isinstance(out["irrelevant_context"], list)
    assert len(out["irrelevant_context"]) == 1


def test_memory_order_shuffle_changes_trace_when_order_changes(monkeypatch):
    sample = {
        "observation": "obs",
        "memory_items": ["a", "b", "c"],
        "irrelevant_context": [],
    }
    baseline = _MODULE._stable_action_trace(sample)

    def _reverse(items):
        items[:] = list(reversed(items))

    monkeypatch.setattr(_MODULE.random, "shuffle", _reverse)
    perturbed = _MODULE._memory_order_shuffle(sample)
    perturbed_trace = _MODULE._stable_action_trace(perturbed)
    assert baseline != perturbed_trace
