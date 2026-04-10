from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_deploy_all_exposes_kube_verification_flags_and_runner() -> None:
    script = (ROOT / "deploy" / "deploy-all.sh").read_text()

    assert "--verify-kube" in script
    assert "--verify-kube-no-degraded" in script
    assert "--verify-kube-no-benchmark" in script
    assert "--enforce-kube-q3-gate" in script
    assert "--deploy-verification-api" in script
    assert "--verification-api-image" in script
    assert "--skip-verification-api-build" in script
    assert "--enforce-kube-full-gate" in script
    assert "deploy_verification_api()" in script
    assert "verify_kube_topology()" in script
    assert '"${DEPLOY_DIR}/verify-kube-topology.sh"' in script
    assert '"${DEPLOY_DIR}/deploy-verification-api.sh"' in script


def test_verify_kube_topology_script_runs_required_gates_and_writes_signoff() -> None:
    script = (ROOT / "deploy" / "verify-kube-topology.sh").read_text()

    assert 'verify_hot_path_observability.sh' in script
    assert 'verify_pkg_redis_resilience.sh' in script
    assert 'benchmark_rct_hot_path.py' in script
    assert 'capture_hot_path_deployment_baseline.py' in script
    assert "green_enough_for_narrow_q3_bridge" in script
    assert "green_enough_for_full_external_agent_debugging" in script
    assert "safe_gemini_read_surface" in script
    assert "probe_verification_api()" in script
    assert "start_runtime_port_forward_if_needed()" in script
    assert "start_verification_port_forward_if_needed()" in script
    assert "verify_productized_surface.sh" in script
    assert "verification_surface_protocol_passed" in script
    assert "POSTGRES_POD_SELECTORS" in script
    assert "SEEDCORE_CONSTRUCT_RUNTIME_AUDIT_FIXTURE" in script
    assert "SEEDCORE_CONSTRUCT_PKG_MINIMAL_CONTRACT_FIXTURE" in script
    assert "seed_kube_runtime_audit_fixture.py" in script
    assert "seed_kube_pkg_minimal_contract.py" in script
    assert "attempt_pkg_minimal_contract_seed()" in script
    assert 'kubectl -n "${NAMESPACE}" exec "${pod_name}" --' in script
    assert "SEEDCORE_ENFORCE_FULL_VERIFICATION_GATE" in script


def test_deploy_verification_api_script_supports_build_load_and_health_rollout() -> None:
    script = (ROOT / "deploy" / "deploy-verification-api.sh").read_text()

    assert "docker/Dockerfile.verification-api" in script
    assert "smart_kind_load" in script
    assert "kubectl -n \"${NAMESPACE}\" rollout status deployment/" in script
    assert "curl -fsS http://127.0.0.1:7071/health" in script


def test_seed_kube_runtime_audit_fixture_script_uses_runtime_replay_fixture_and_psql_insert() -> None:
    script = (ROOT / "scripts" / "host" / "seed_kube_runtime_audit_fixture.py").read_text()

    assert "tests/fixtures/demo/rct_signoff_v1" in script
    assert "runtime_replay.json" in script
    assert "INSERT INTO tasks" in script
    assert "INSERT INTO governed_execution_audit" in script
    assert "kubectl" in script
    assert "psql" in script


def test_seed_kube_pkg_minimal_contract_script_upserts_manifest_taxonomy_and_governed_fact() -> None:
    script = (ROOT / "scripts" / "host" / "seed_kube_pkg_minimal_contract.py").read_text()

    assert "INSERT INTO pkg_snapshot_manifests" in script
    assert "INSERT INTO pkg_reason_codes" in script
    assert "INSERT INTO pkg_trust_gap_codes" in script
    assert "INSERT INTO pkg_obligation_codes" in script
    assert "INSERT INTO facts" in script
    assert "AllowedOperation" in script
    assert "/api/v1/pkg/reload" in script
