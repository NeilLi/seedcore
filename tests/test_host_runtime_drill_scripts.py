from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_verify_hot_path_observability_uses_portable_python_resolution() -> None:
    script = (ROOT / "scripts" / "host" / "verify_hot_path_observability.sh").read_text()

    assert 'command -v python3' in script
    assert 'PYTHON_BIN="python3"' in script
    assert 'PYTHON_BIN="python"' in script
    assert '"${PYTHON_BIN}" - <<\'PY\'' in script


def test_verify_pkg_redis_resilience_covers_outage_and_recovery() -> None:
    script = (ROOT / "scripts" / "host" / "verify_pkg_redis_resilience.sh").read_text()

    assert 'docker stop "${REDIS_CONTAINER}"' in script
    assert 'docker start "${REDIS_CONTAINER}"' in script
    assert 'REDIS_DRILL_MODE="${SEEDCORE_REDIS_DRILL_MODE:-auto}"' in script
    assert 'REDIS_KUBE_NAMESPACE="${SEEDCORE_REDIS_KUBE_NAMESPACE:-seedcore-dev}"' in script
    assert 'REDIS_KUBE_DEPLOYMENT="${SEEDCORE_REDIS_KUBE_DEPLOYMENT:-redis}"' in script
    assert 'kubectl -n "${REDIS_KUBE_NAMESPACE}" scale deployment "${REDIS_KUBE_DEPLOYMENT}" --replicas=0' in script
    assert 'kubectl -n "${REDIS_KUBE_NAMESPACE}" scale deployment "${REDIS_KUBE_DEPLOYMENT}" --replicas="${redis_kube_original_replicas}"' in script
    assert 'resolve_redis_mode "${REDIS_DRILL_MODE}"' in script
    assert 'trap cleanup EXIT' in script
    assert '/health' in script
    assert '/readyz' in script
    assert '/pdp/hot-path/status' in script


def test_verify_productized_surface_can_enable_redis_dependency_drill() -> None:
    script = (ROOT / "scripts" / "host" / "verify_productized_surface.sh").read_text()

    assert 'SEEDCORE_RUN_REDIS_DEPENDENCY_DRILL' in script
    assert 'verify_pkg_redis_resilience.sh' in script


def test_verify_kafka_readyz_gate_runs_alternate_api_and_checks_readyz_flip() -> None:
    script = (ROOT / "scripts" / "host" / "verify_kafka_readyz_gate.sh").read_text()

    assert 'PORT="${PORT:-8012}"' in script
    assert 'EXISTING_API_PORT="${SEEDCORE_EXISTING_API_PORT:-8002}"' in script
    assert 'SEEDCORE_KAFKA_READYZ_CHECK=1' in script
    assert 'docker compose version' in script
    assert 'command -v docker-compose' in script
    assert '/proc/${pid}/environ' in script
    assert 'resolve_existing_api_pid()' in script
    assert 'read_env_value_from_pid "${pid}" "PG_DSN"' in script
    assert 'tail -n 80 "${API_LOG_PATH}"' in script
    assert 'docker stop "${KAFKA_CONTAINER}"' in script
    assert 'docker start "${KAFKA_CONTAINER}"' in script
    assert 'wait_for_status "${READYZ_URL}" "503"' in script
    assert 'wait_for_status "${READYZ_URL}" "200"' in script


def test_verify_productized_surface_can_enable_kafka_dependency_drill() -> None:
    script = (ROOT / "scripts" / "host" / "verify_productized_surface.sh").read_text()

    assert 'SEEDCORE_RUN_KAFKA_DEPENDENCY_DRILL' in script
    assert 'verify_kafka_readyz_gate.sh' in script


def test_verify_q2_verification_contracts_is_canonical_local_ci_gate() -> None:
    script = (ROOT / "scripts" / "host" / "verify_q2_verification_contracts.sh").read_text()

    assert "tests/test_authz_parity_service.py" in script
    assert "tests/test_replay_service.py" in script
    assert "tests/test_rct_replay_verification_phase4.py" in script
    assert "npm run typecheck" in script
    assert "npm test" in script
    assert "q2_verification_api_fixture_gate.sh" in script
    assert "verify_hot_path_alert_rules.sh" in script
    assert "verify_hot_path_benchmark_lane.sh" in script
    assert "verify_q2_degraded_edge_drill_matrix.sh" in script
    assert "verify_result_verifier_postgres_integration.sh" in script


def test_result_verifier_postgres_integration_script_is_opt_in_but_hard_fails_when_enabled_without_dsn() -> None:
    script = (ROOT / "scripts" / "host" / "verify_result_verifier_postgres_integration.sh").read_text()

    assert "SEEDCORE_ENABLE_RESULT_VERIFIER_PG_TESTS" in script
    assert "SEEDCORE_RESULT_VERIFIER_TEST_DSN" in script
    assert "tests/test_result_verifier_postgres_integration.py" in script


def test_verify_design_notes_full_wires_extended_design_notes_gate() -> None:
    script = (ROOT / "scripts" / "host" / "verify_design_notes_full.sh").read_text()

    assert "verify_host_regression.sh" in script
    assert "verify_pdp_boundary.sh" in script
    assert "verify_execution_spine.sh" in script
    assert "verify_evidence_contracts.sh" in script
    assert "verify_admission_contract_inventory.sh" in script
    assert "verify_kafka_ingress_non_bypass.sh" in script
    assert "verify_agent_action_gateway_productization_real_calls.sh" in script
    assert "verify_productized_surface.sh" in script
    assert "verify_q2_verification_contracts.sh" in script
    assert "maybe_start_verification_api()" in script
    assert "ts/services/verification-api" in script
    assert "SEEDCORE_SKIP_Q2_CONTRACT_GATE" in script


def test_verify_admission_contract_inventory_tracks_required_components() -> None:
    script = (ROOT / "scripts" / "host" / "verify_admission_contract_inventory.py").read_text()

    assert "agent_action_gateway_boundary" in script
    assert "hal_execution_boundary" in script
    assert "governed_tools_mutation_manager" in script
    assert "replay_and_custody_trust_surfaces" in script
    assert "Admission-contract inventory verification passed." in script


def test_verify_kafka_ingress_non_bypass_enforces_agent_actions_path() -> None:
    script = (ROOT / "scripts" / "host" / "verify_kafka_ingress_non_bypass.py").read_text()

    assert "/api/v1/agent-actions/evaluate" in script
    assert "/api/v1/intents/submit-signed" in script
    assert "process_delegated_intent_event" in script
    assert "SEEDCORE_KAFKA_INTENT_INGRESS_NO_EXECUTE" in script
