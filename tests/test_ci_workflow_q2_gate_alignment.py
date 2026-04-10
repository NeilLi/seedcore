from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_unit_tests_workflow_uses_canonical_q2_host_gate_script() -> None:
    workflow = (ROOT / ".github" / "workflows" / "unit-tests.yml").read_text(encoding="utf-8")

    assert "Q2 local verification gate (canonical host script)" in workflow
    assert "run: bash scripts/host/verify_q2_verification_contracts.sh" in workflow
    assert "SEEDCORE_ENABLE_RESULT_VERIFIER_PG_TESTS" in workflow
    assert "SEEDCORE_RESULT_VERIFIER_TEST_DSN" in workflow
