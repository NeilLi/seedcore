from __future__ import annotations

from typing import Any, Dict, Mapping

from seedcore.adapters.rct_agent_action_gateway_reference_adapter import (
    build_rct_agent_action_evaluate_request_v1,
)
from seedcore.models.rare_shoe_rct import CollectibleShoeRegistration


def build_rare_shoe_gateway_request_from_fixtures(
    *,
    registration: Mapping[str, Any],
    transfer_intent: Mapping[str, Any],
) -> Dict[str, Any]:
    """Map rare-shoe demo fixtures into the existing Agent Action Gateway v1 RCT contract."""
    shoe = CollectibleShoeRegistration.model_validate(registration)
    commerce = transfer_intent.get("commerce") if isinstance(transfer_intent.get("commerce"), Mapping) else {}
    principal = transfer_intent.get("principal") if isinstance(transfer_intent.get("principal"), Mapping) else {}
    workflow = transfer_intent.get("workflow") if isinstance(transfer_intent.get("workflow"), Mapping) else {}
    approval = transfer_intent.get("approval") if isinstance(transfer_intent.get("approval"), Mapping) else {}
    authority_scope = (
        transfer_intent.get("authority_scope")
        if isinstance(transfer_intent.get("authority_scope"), Mapping)
        else {}
    )
    telemetry = transfer_intent.get("telemetry") if isinstance(transfer_intent.get("telemetry"), Mapping) else {}
    security_contract = (
        transfer_intent.get("security_contract")
        if isinstance(transfer_intent.get("security_contract"), Mapping)
        else {}
    )

    asset_base = {
        "asset_id": shoe.asset_id,
        "lot_id": transfer_intent.get("lot_id") or shoe.style_code,
        "from_custodian_ref": transfer_intent.get("from_custodian_ref"),
        "to_custodian_ref": transfer_intent.get("to_custodian_ref"),
        "from_zone": transfer_intent.get("from_zone"),
        "to_zone": transfer_intent.get("to_zone"),
        "provenance_hash": transfer_intent.get("provenance_hash") or shoe.sku_serial_hash,
    }

    authority_scope_base = {
        "scope_id": authority_scope.get("scope_id"),
        "asset_ref": authority_scope.get("asset_ref") or shoe.asset_id,
        "product_ref": authority_scope.get("product_ref") or shoe.product_ref,
        "facility_ref": authority_scope.get("facility_ref"),
        "expected_from_zone": authority_scope.get("expected_from_zone"),
        "expected_to_zone": authority_scope.get("expected_to_zone"),
        "expected_coordinate_ref": authority_scope.get("expected_coordinate_ref"),
    }

    return build_rct_agent_action_evaluate_request_v1(
        request_id=str(transfer_intent.get("request_id")),
        idempotency_key=str(transfer_intent.get("idempotency_key")),
        requested_at=str(transfer_intent.get("requested_at")),
        policy_snapshot_ref=shoe.policy_snapshot_ref,
        principal=principal,
        workflow_valid_until=str(workflow.get("valid_until")),
        asset_base=asset_base,
        approval_envelope_id=str(approval.get("approval_envelope_id")),
        approval_expected_envelope_version=approval.get("expected_envelope_version"),
        authority_scope_base=authority_scope_base,
        telemetry=telemetry,
        security_contract=security_contract,
        shopify_sandbox_transaction={
            "product_ref": commerce.get("product_ref") or shoe.product_ref,
            "order_ref": commerce.get("order_ref"),
            "quote_ref": commerce.get("quote_ref"),
            "declared_value_usd": commerce.get("declared_value_usd"),
            "economic_hash": commerce.get("economic_hash"),
        },
        options=transfer_intent.get("options") if isinstance(transfer_intent.get("options"), Mapping) else None,
    )
