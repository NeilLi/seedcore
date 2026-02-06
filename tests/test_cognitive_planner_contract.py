import pytest

from seedcore.cognitive.cognitive_core import CognitiveCore


def _core():
    # Avoid heavy __init__
    return CognitiveCore.__new__(CognitiveCore)


def test_planner_contract_allows_explicit_dag():
    core = _core()
    payload = {
        "nodes": [
            {"id": "wait_noise", "type": "condition"},
            {"id": "set_temp", "type": "action"},
            {"id": "lights_off", "type": "action"},
        ],
        "edges": [["wait_noise", "set_temp"], ["wait_noise", "lights_off"]],
        "estimated_complexity": 5.0,
    }
    violations = []
    assert core._validate_planner_contract(payload, violations) is True
    assert violations == []


def test_planner_contract_allows_implicit_dag():
    core = _core()
    payload = {
        "solution_steps": [
            {"id": "wait_noise", "type": "condition", "depends_on": []},
            {"id": "set_temp", "type": "action", "depends_on": ["wait_noise"]},
            {"id": "lights_off", "type": "action", "depends_on": ["wait_noise"]},
        ],
        "estimated_complexity": 4.0,
    }
    violations = []
    assert core._validate_planner_contract(payload, violations) is True
    assert violations == []


def test_planner_contract_rejects_both_shapes():
    core = _core()
    payload = {
        "nodes": [{"id": "n1", "type": "condition"}],
        "edges": [],
        "solution_steps": [{"id": "s1", "type": "action", "depends_on": []}],
    }
    violations = []
    assert core._validate_planner_contract(payload, violations) is False
    assert any("exactly one shape" in v for v in violations)


def test_planner_contract_rejects_missing_edges_in_explicit_dag():
    core = _core()
    payload = {
        "nodes": [{"id": "n1", "type": "condition"}],
    }
    violations = []
    assert core._validate_planner_contract(payload, violations) is False
    assert any("edges must be a list" in v for v in violations)


def test_planner_contract_rejects_extra_keys_in_step():
    core = _core()
    payload = {
        "solution_steps": [
            {
                "id": "wait_noise",
                "type": "condition",
                "depends_on": [],
                "params": {"routing": {"specialization": "SecurityMonitoring"}},
            }
        ]
    }
    violations = []
    assert core._validate_planner_contract(payload, violations) is False
    assert any("forbidden keys" in v for v in violations)
    assert any("forbidden field 'routing'" in v for v in violations)


def test_planner_contract_rejects_top_level_forbidden_keys():
    core = _core()
    payload = {
        "solution_steps": [
            {"id": "wait_noise", "type": "condition", "depends_on": []}
        ],
        "routing": {"specialization": "SecurityMonitoring"},
    }
    violations = []
    assert core._validate_planner_contract(payload, violations) is False
    assert any("forbidden top-level keys" in v for v in violations)
    assert any("forbidden field 'routing'" in v for v in violations)


def test_planner_contract_rejects_missing_depends_on():
    core = _core()
    payload = {
        "solution_steps": [
            {"id": "wait_noise", "type": "condition"}
        ]
    }
    violations = []
    assert core._validate_planner_contract(payload, violations) is False
    assert any("missing required 'depends_on'" in v for v in violations)
