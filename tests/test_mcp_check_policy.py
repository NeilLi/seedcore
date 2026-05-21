from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import pytest

from seedcore.plugin.mcp_server import seedcore_agent_action_check_policy


@pytest.mark.asyncio
async def test_check_policy_tool_builds_valid_payload_and_evaluates():
    # 1. Setup mock AppContext and SeedcoreRuntimeClient
    mock_runtime = MagicMock()
    mock_runtime.evaluate_agent_action = AsyncMock(return_value={
        "decision": {"allowed": True, "disposition": "allow", "reason_code": "allowed"},
        "execution_token": {"token_id": "tok-mcp-789"},
        "forensic_linkage": {
            "audit_id": "aud-mcp-789",
            "replay_ref": "replay://workflow/mcp-789",
            "forensic_block_id": "fb-mcp-789"
        },
    })
    mock_runtime.api_url = MagicMock(return_value="http://127.0.0.1:8002/api/v1/agent-actions/evaluate")

    # Construct the nested context mock
    mock_ctx = MagicMock()
    mock_ctx.request_context.lifespan_context.runtime = mock_runtime

    # 2. Invoke the check_policy MCP tool
    result = await seedcore_agent_action_check_policy(
        mock_ctx,
        action_name="TRANSFER_CUSTODY",
        asset_ref="asset:lot-9999",
        declared_value_usd=2500.0,
        telemetry_evidence=["origin_scan", "delivery_scan", "signed_edge_telemetry"],
        buyer_did="did:seedcore:owner:custom-buyer",
        delegation_id="delegation:custom-delegation",
        session_token="session-custom",
    )

    # 3. Assert correct output structure
    assert result["ok"] is True
    assert result["decision"]["disposition"] == "allow"
    assert result["execution_token"]["token_id"] == "tok-mcp-789"
    assert result["forensic_linkage"]["audit_id"] == "aud-mcp-789"

    # 4. Inspect the mock evaluate call arguments
    mock_runtime.evaluate_agent_action.assert_called_once()
    called_args = mock_runtime.evaluate_agent_action.call_args[0]
    called_kwargs = mock_runtime.evaluate_agent_action.call_args[1]

    # Retrieve the constructed request payload
    request_payload = called_args[0]
    assert called_kwargs.get("no_execute") is True

    # Assert correct parameters were mapped
    assert request_payload["contract_version"] == "seedcore.agent_action_gateway.v1"
    assert request_payload["principal"]["owner_id"] == "did:seedcore:owner:custom-buyer"
    assert request_payload["principal"]["delegation_ref"] == "delegation:custom-delegation"
    assert request_payload["principal"]["session_token"] == "session-custom"
    assert request_payload["principal"]["actor_token"] is None
    assert request_payload["asset"]["asset_id"] == "asset:lot-9999"
    assert request_payload["asset"]["lot_id"] == "lot-9999"
    assert request_payload["asset"]["product_ref"] == "shopify:gid://shopify/Product/1234567890"
    assert request_payload["asset"]["declared_value_usd"] == 2500.0
    assert request_payload["telemetry"]["evidence_refs"] == ["origin_scan", "delivery_scan", "signed_edge_telemetry"]


@pytest.mark.asyncio
async def test_check_policy_tool_requires_explicit_authority_and_identity():
    mock_ctx = MagicMock()

    with pytest.raises(ValueError, match="buyer_did is required"):
        await seedcore_agent_action_check_policy(
            mock_ctx,
            action_name="TRANSFER_CUSTODY",
            asset_ref="asset:lot-9999",
            telemetry_evidence=["origin_scan"],
            delegation_id="delegation:custom-delegation",
            session_token="session-custom",
        )

    with pytest.raises(ValueError, match="delegation_id is required"):
        await seedcore_agent_action_check_policy(
            mock_ctx,
            action_name="TRANSFER_CUSTODY",
            asset_ref="asset:lot-9999",
            telemetry_evidence=["origin_scan"],
            buyer_did="did:seedcore:owner:custom-buyer",
            session_token="session-custom",
        )

    with pytest.raises(ValueError, match="session_token or actor_token is required"):
        await seedcore_agent_action_check_policy(
            mock_ctx,
            action_name="TRANSFER_CUSTODY",
            asset_ref="asset:lot-9999",
            telemetry_evidence=["origin_scan"],
            buyer_did="did:seedcore:owner:custom-buyer",
            delegation_id="delegation:custom-delegation",
        )


@pytest.mark.asyncio
async def test_check_policy_tool_rejects_unsupported_action_name():
    with pytest.raises(ValueError, match="TRANSFER_CUSTODY"):
        await seedcore_agent_action_check_policy(
            MagicMock(),
            action_name="DELETE_ASSET",
            asset_ref="asset:lot-9999",
            telemetry_evidence=["origin_scan"],
            buyer_did="did:seedcore:owner:custom-buyer",
            delegation_id="delegation:custom-delegation",
            session_token="session-custom",
        )
