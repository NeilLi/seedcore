from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from seedcore.adapters.shopify_sandbox_commerce_adapter import (
    map_shopify_sandbox_transaction_to_gateway_commerce_fields,
)
from seedcore.adapters.rct_gateway_correlation import build_rct_gateway_to_replay_correlation
from seedcore.models.agent_action_gateway import AgentActionEvaluateRequest


def build_rct_agent_action_evaluate_request_v1(
    *,
    request_id: str,
    idempotency_key: str,
    requested_at: str,
    policy_snapshot_ref: Optional[str],
    principal: Mapping[str, Any],
    workflow_valid_until: str,
    asset_base: Mapping[str, Any],
    approval_envelope_id: str,
    approval_expected_envelope_version: Optional[str],
    authority_scope_base: Mapping[str, Any],
    telemetry: Mapping[str, Any],
    security_contract: Mapping[str, Any],
    shopify_sandbox_transaction: Mapping[str, Any],
    options: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Reference agent adapter for RCT gateway evaluate requests.

    It constructs a strict `seedcore.agent_action_gateway.v1` request using:
    - the existing gateway contract model (Pydantic)
    - a narrow Shopify-Sandbox-shaped commerce mapping
    """
    commerce = map_shopify_sandbox_transaction_to_gateway_commerce_fields(
        product_ref=shopify_sandbox_transaction.get("product_ref"),
        quote_ref=shopify_sandbox_transaction.get("quote_ref"),
        declared_value_usd=shopify_sandbox_transaction.get("declared_value_usd"),
        economic_hash=shopify_sandbox_transaction.get("economic_hash"),
    )

    asset: Dict[str, Any] = {**dict(asset_base)}
    asset.update(commerce["asset"])

    # Preserve authority_scope_base.product_ref if present so schema invariants
    # can reject mismatches; otherwise fill it from commerce.
    authority_scope: Dict[str, Any] = {**dict(authority_scope_base)}
    if authority_scope.get("product_ref") is None:
        authority_scope["product_ref"] = commerce["asset"]["product_ref"]

    forensic_context: Dict[str, Any] = {
        "fingerprint_components": commerce["forensic_context"]["fingerprint_components"]
    }

    # Gateway workflow/action invariants: contract fixes type + action_type.
    payload = {
        "contract_version": "seedcore.agent_action_gateway.v1",
        "request_id": request_id,
        "requested_at": requested_at,
        "idempotency_key": idempotency_key,
        "policy_snapshot_ref": policy_snapshot_ref,
        "principal": dict(principal),
        "workflow": {
            "valid_until": workflow_valid_until,
        },
        "asset": asset,
        "approval": {
            "approval_envelope_id": approval_envelope_id,
            "expected_envelope_version": approval_expected_envelope_version,
        },
        "authority_scope": authority_scope,
        "telemetry": dict(telemetry),
        "forensic_context": forensic_context,
        "security_contract": dict(security_contract),
        "options": dict(options or {"debug": False}),
    }

    validated = AgentActionEvaluateRequest.model_validate(payload)
    return validated.model_dump(mode="json")


def build_rct_gateway_correlation_from_evaluate_response(
    *,
    request_id: str,
    gateway_evaluate_response: Mapping[str, Any],
) -> Dict[str, Any]:
    return build_rct_gateway_to_replay_correlation(
        request_id=request_id,
        gateway_evaluate_response=gateway_evaluate_response,
    )

