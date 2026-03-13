# Import mock dependencies BEFORE any other imports
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from seedcore.coordinator.core.governance import (
    build_action_intent,
    evaluate_intent,
)
from seedcore.models.action_intent import (
    ActionIntent,
    IntentAction,
    IntentPrincipal,
    IntentResource,
    SecurityContract,
)
from seedcore.models.task_payload import TaskPayload
import seedcore.services.coordinator_service as cs


def _iso_utc(delta_seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat()


def _build_release_intent(
    *,
    source_registration_id: str | None = None,
    registration_decision_id: str | None = None,
    agent_id: str = "agent-1",
) -> ActionIntent:
    return ActionIntent(
        intent_id="intent-test",
        timestamp=_iso_utc(-30),
        valid_until=_iso_utc(120),
        principal=IntentPrincipal(
            agent_id=agent_id,
            role_profile="PACKING_OPERATOR",
            session_token="session-test",
        ),
        action=IntentAction(
            type="RELEASE",
            parameters={},
            security_contract=SecurityContract(hash="abc", version="snapshot:5"),
        ),
        resource=IntentResource(
            asset_id="asset-1",
            target_zone="packing_line_a",
            provenance_hash="prov-1",
            source_registration_id=source_registration_id,
            registration_decision_id=registration_decision_id,
        ),
    )


def test_build_action_intent_maps_task_payload_contract():
    task = TaskPayload(
        task_id="task-123",
        type="action",
        description="move sealed tote",
        correlation_id="corr-123",
        snapshot_id=42,
        ttl_seconds=45,
        params={
            "interaction": {
                "assigned_agent_id": "agent-77",
                "conversation_id": "session-9",
            },
            "routing": {
                "required_specialization": "VAULT_OPERATOR",
            },
            "multimodal": {
                "location_context": "vault_a",
                "media_uri": "camera://vault_a/front",
            },
            "resource": {
                "asset_id": "lot-9",
                "source_registration_id": "reg-123",
            },
            "intent": "release",
        },
    )

    intent = build_action_intent(task)

    assert intent.principal.agent_id == "agent-77"
    assert intent.principal.role_profile == "VAULT_OPERATOR"
    assert intent.principal.session_token == "session-9"
    assert intent.action.type == "RELEASE"
    assert intent.action.security_contract.version == "snapshot:42"
    assert intent.resource.asset_id == "lot-9"
    assert intent.resource.target_zone == "vault_a"
    assert intent.resource.source_registration_id == "reg-123"

    issued_at = datetime.fromisoformat(intent.timestamp).astimezone(timezone.utc)
    valid_until = datetime.fromisoformat(intent.valid_until).astimezone(timezone.utc)
    assert int((valid_until - issued_at).total_seconds()) == 45


def test_build_action_intent_stable_schema_and_deterministic_policy_fields():
    payload_one = {
        "type": "action",
        "description": "release payload one",
        "params": {
            "routing": {"required_specialization": "PACKING_OPERATOR"},
            "interaction": {"assigned_agent_id": "agent-11"},
            "multimodal": {"location_context": "zone_a"},
            "intent": "release",
            "custom_b": "b",
            "custom_a": "a",
        },
    }
    payload_two = {
        "description": "release payload one",
        "type": "action",
        "params": {
            "intent": "release",
            "custom_a": "a",
            "custom_b": "b",
            "multimodal": {"location_context": "zone_a"},
            "interaction": {"assigned_agent_id": "agent-11"},
            "routing": {"required_specialization": "PACKING_OPERATOR"},
        },
    }
    fixed_now = datetime(2026, 3, 13, 10, 0, tzinfo=timezone.utc)

    with patch("seedcore.coordinator.core.governance._utcnow", return_value=fixed_now):
        intent_one = build_action_intent(payload_one)
        intent_two = build_action_intent(payload_two)

    dumped = intent_one.model_dump(mode="json")
    assert list(dumped.keys()) == [
        "intent_id",
        "timestamp",
        "valid_until",
        "principal",
        "action",
        "resource",
    ]
    assert list(dumped["principal"].keys()) == [
        "agent_id",
        "role_profile",
        "session_token",
    ]
    assert list(dumped["action"].keys()) == ["type", "parameters", "security_contract"]
    assert list(dumped["resource"].keys()) == [
        "asset_id",
        "target_zone",
        "provenance_hash",
        "source_registration_id",
        "registration_decision_id",
    ]

    assert intent_one.principal.agent_id == intent_two.principal.agent_id
    assert intent_one.principal.role_profile == intent_two.principal.role_profile
    assert intent_one.principal.session_token == intent_two.principal.session_token
    assert intent_one.resource.asset_id == intent_two.resource.asset_id
    assert intent_one.action.parameters == intent_two.action.parameters
    assert list(intent_one.action.parameters.keys()) == ["custom_a", "custom_b", "intent"]


def test_evaluate_intent_denies_expired_ttl():
    expired = _build_release_intent(source_registration_id="reg-1", registration_decision_id="decision-1")
    expired.timestamp = _iso_utc(-300)
    expired.valid_until = _iso_utc(-10)

    decision = evaluate_intent(expired, policy_snapshot="snapshot:5")

    assert decision.allowed is False
    assert decision.deny_code == "expired_intent"


def test_evaluate_intent_denies_release_without_source_registration():
    intent = _build_release_intent()

    decision = evaluate_intent(intent, policy_snapshot="snapshot:5")

    assert decision.allowed is False
    assert decision.deny_code == "missing_source_registration"


def test_evaluate_intent_denies_release_with_unapproved_source_registration():
    intent = _build_release_intent(
        source_registration_id="reg-1",
        registration_decision_id="decision-1",
    )

    decision = evaluate_intent(
        intent,
        policy_snapshot="snapshot:5",
        approved_source_registrations={},
    )

    assert decision.allowed is False
    assert decision.deny_code == "unapproved_source_registration"


def test_evaluate_intent_denies_release_with_mismatched_decision_id():
    intent = _build_release_intent(
        source_registration_id="reg-1",
        registration_decision_id="decision-2",
    )

    decision = evaluate_intent(
        intent,
        policy_snapshot="snapshot:5",
        approved_source_registrations={"reg-1": "decision-1"},
    )

    assert decision.allowed is False
    assert decision.deny_code == "mismatched_registration_decision"


def test_evaluate_intent_denies_missing_principal():
    intent = _build_release_intent(
        source_registration_id="reg-1",
        registration_decision_id="decision-1",
        agent_id="",
    )

    decision = evaluate_intent(
        intent,
        policy_snapshot="snapshot:5",
        approved_source_registrations={"reg-1": "decision-1"},
    )

    assert decision.allowed is False
    assert decision.deny_code == "missing_principal"


def test_evaluate_intent_allows_release_with_approved_source_registration():
    intent = _build_release_intent(
        source_registration_id="reg-1",
        registration_decision_id="decision-1",
    )

    decision = evaluate_intent(
        intent,
        policy_snapshot="snapshot:5",
        approved_source_registrations={"reg-1": "decision-1"},
    )

    assert decision.allowed is True
    assert decision.execution_token is not None
    assert decision.reason == "allow_release_with_approved_source_registration"

    token = decision.execution_token.model_dump(mode="json")
    assert list(token.keys()) == [
        "token_id",
        "intent_id",
        "issued_at",
        "valid_until",
        "contract_version",
        "signature",
        "constraints",
    ]
    assert list(token["constraints"].keys()) == [
        "action_type",
        "target_zone",
        "asset_id",
        "principal_agent_id",
        "source_registration_id",
        "registration_decision_id",
    ]


@pytest.mark.asyncio
async def test_coordinator_handoff_injects_governance_context():
    with patch.object(cs.Coordinator, "__init__", return_value=None):
        coordinator = cs.Coordinator.__new__(cs.Coordinator)

    organism_post = AsyncMock(
        return_value={
            "success": True,
            "payload": {"status": "ok"},
            "error": None,
            "error_type": None,
            "meta": {},
            "path": "organism_service",
        }
    )

    coordinator.organism_timeout_s = 12
    coordinator.organism_client = SimpleNamespace(post=organism_post)
    coordinator._compute_drift_score = AsyncMock(return_value=0.0)
    coordinator.graph_task_repo = None
    coordinator.ml_client = None
    coordinator.metrics = MagicMock()
    coordinator.cognitive_client = None
    coordinator._persist_proto_plan = AsyncMock()
    coordinator._record_router_telemetry = AsyncMock()
    coordinator._session_factory = MagicMock()
    coordinator.fast_path_latency_slo_ms = 1000.0
    coordinator._run_eventizer = MagicMock()

    exec_cfg = coordinator._build_execution_config("cid-123")

    result = await exec_cfg.organism_execute(
        "organism",
        {
            "task_id": "task-999",
            "type": "action",
            "snapshot_id": 8,
            "correlation_id": "corr-9",
            "params": {
                "interaction": {
                    "assigned_agent_id": "agent-99",
                    "conversation_id": "session-99",
                },
                "routing": {
                    "required_specialization": "ROBOT_OPERATOR",
                },
                "multimodal": {
                    "location_context": "zone_b",
                },
                "resource": {
                    "asset_id": "asset-22",
                },
                "intent": "transport",
            },
        },
        1.0,
        "cid-123",
    )

    assert organism_post.await_count == 1
    sent_payload = organism_post.await_args.kwargs["json"]["task"]
    governance = sent_payload["params"]["governance"]
    assert governance["action_intent"]["principal"]["agent_id"] == "agent-99"
    assert governance["action_intent"]["principal"]["role_profile"] == "ROBOT_OPERATOR"
    assert governance["execution_token"]["contract_version"] == "snapshot:8"
    assert governance["policy_decision"]["allowed"] is True
    assert result["meta"]["governance"]["execution_token"]["intent_id"] == governance["action_intent"]["intent_id"]
