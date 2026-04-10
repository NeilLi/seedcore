from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_deploy_all_exposes_kube_verification_flags_and_runner() -> None:
    script = (ROOT / "deploy" / "deploy-all.sh").read_text()

    assert "--verify-kube" in script
    assert "--verify-kube-no-degraded" in script
    assert "--verify-kube-no-benchmark" in script
    assert "--enforce-kube-q3-gate" in script
    assert "verify_kube_topology()" in script
    assert '"${DEPLOY_DIR}/verify-kube-topology.sh"' in script


def test_verify_kube_topology_script_runs_required_gates_and_writes_signoff() -> None:
    script = (ROOT / "deploy" / "verify-kube-topology.sh").read_text()

    assert 'verify_hot_path_observability.sh' in script
    assert 'verify_pkg_redis_resilience.sh' in script
    assert 'benchmark_rct_hot_path.py' in script
    assert 'capture_hot_path_deployment_baseline.py' in script
    assert "green_enough_for_narrow_q3_bridge" in script
    assert "safe_gemini_read_surface" in script
    assert "probe_verification_api()" in script
    assert "start_port_forward_if_needed()" in script
