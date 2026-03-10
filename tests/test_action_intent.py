# Import mock dependencies BEFORE any other imports
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies

from datetime import datetime, timezone
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

    issued_at = datetime.fromisoformat(intent.timestamp).astimezone(timezone.utc)
    valid_until = datetime.fromisoformat(intent.valid_until).astimezone(timezone.utc)
    assert int((valid_until - issued_at).total_seconds()) == 45


def test_evaluate_intent_denies_expired_contract():
    expired = ActionIntent(
        intent_id="intent-1",
        timestamp="2026-03-10T00:00:10+00:00",
        valid_until="2026-03-10T00:00:09+00:00",
        principal=IntentPrincipal(
            agent_id="agent-1",
            role_profile="VAULT_OPERATOR",
            session_token="session-1",
        ),
        action=IntentAction(
            type="RELEASE",
            parameters={},
            security_contract=SecurityContract(hash="abc", version="snapshot:5"),
        ),
        resource=IntentResource(
            asset_id="asset-1",
            target_zone="vault_a",
            provenance_hash="prov-1",
        ),
    )

    decision = evaluate_intent(expired, policy_snapshot="snapshot:5")

    assert decision.allowed is False
    assert decision.deny_code == "expired_intent"


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

