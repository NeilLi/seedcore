from __future__ import annotations

import json
from pathlib import Path

from seedcore.adapters.rare_shoe_rct_adapter import build_rare_shoe_gateway_request_from_fixtures
from seedcore.models.agent_action_gateway import AgentActionEvaluateRequest
from seedcore.models.rare_shoe_rct import (
    CollectibleShoeRegistration,
    RareShoeBoundedCustodyAuthority,
    RareShoeEdgeTelemetry,
    build_rare_shoe_workflow_join_key,
    evaluate_rare_shoe_edge_telemetry,
    evaluate_rare_shoe_replay_bundle,
    validate_rare_shoe_public_proof_projection,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "rare_shoe_rct"
WORKFLOW_JOIN_KEY = "wf:0a8290b30996a3f27dfd9c22584d2adc71a8a2ed32bfe0bbfc2024c954ab7b31"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_collectible_shoe_registration_fixture_matches_contract_and_join_key() -> None:
    raw = _load("clean_rare_shoe_registration.json")
    registration = CollectibleShoeRegistration.model_validate(raw)

    assert registration.authentication_status == "approved"
    assert registration.custody_state == "VAULTED_SECURE"
    assert registration.risk_state == "CLEAR"
    assert registration.workflow_join_key == WORKFLOW_JOIN_KEY
    assert build_rare_shoe_workflow_join_key(
        asset_id=registration.asset_id,
        product_ref=registration.product_ref,
        quote_ref="rare-shoe-market:quote:2026-05-15-0001",
        order_ref="rare-shoe-market:order:2026-05-15-0001",
        policy_snapshot_ref=registration.policy_snapshot_ref,
        valid_from="2026-05-15T10:00:00Z",
        valid_until="2026-05-15T10:15:00Z",
    ) == WORKFLOW_JOIN_KEY


def test_rare_shoe_gateway_adapter_preserves_commerce_and_scope_fields() -> None:
    payload = build_rare_shoe_gateway_request_from_fixtures(
        registration=_load("clean_rare_shoe_registration.json"),
        transfer_intent=_load("authorized_rare_shoe_transfer_intent.json"),
    )
    request = AgentActionEvaluateRequest.model_validate(payload)

    assert request.contract_version == "seedcore.agent_action_gateway.v1"
    assert request.workflow.type == "restricted_custody_transfer"
    assert request.asset.asset_id == "asset:shoe:player-exclusive-001"
    assert request.asset.product_ref == "rare-shoe-market:product:pe-jordan-001"
    assert request.asset.quote_ref == "rare-shoe-market:quote:2026-05-15-0001"
    assert request.asset.order_ref == "rare-shoe-market:order:2026-05-15-0001"
    assert request.authority_scope.asset_ref == request.asset.asset_id
    assert request.authority_scope.product_ref == request.asset.product_ref
    assert request.forensic_context is not None
    assert request.forensic_context.fingerprint_components is not None
    assert (
        request.forensic_context.fingerprint_components.economic_hash
        == "sha256:economic-rare-shoe-order-0001"
    )


def test_happy_path_replay_bundle_verifies_and_public_projection_is_redacted() -> None:
    bundle = _load("rare_shoe_happy_path_replay_bundle.json")
    result = evaluate_rare_shoe_replay_bundle(bundle)

    assert result["verified"] is True
    assert result["reason_code"] == "rare_shoe_replay_verified"
    assert result["workflow_join_key"] == WORKFLOW_JOIN_KEY
    assert result["product_ref"] == "rare-shoe-market:product:pe-jordan-001"
    assert result["public_proof"]["status"] == "publishable"


def test_public_projection_with_authority_tier_fields_requires_review() -> None:
    public_proof = dict(_load("rare_shoe_happy_path_replay_bundle.json")["public_proof_projection"])
    public_proof["raw_telemetry_refs"] = ["telemetry:rare-shoe-origin-0001"]
    public_proof["challenge_nonce"] = "challenge:delivery:0001"

    result = validate_rare_shoe_public_proof_projection(public_proof)

    assert result["status"] == "review_required"
    assert result["reason_code"] == "PUBLIC_PROOF_REDACTION_REQUIRED"
    assert result["forbidden_keys"] == ["challenge_nonce", "raw_telemetry_refs"]


def test_dynamic_nfc_clone_fixture_fails_closed() -> None:
    registration = CollectibleShoeRegistration.model_validate(_load("clean_rare_shoe_registration.json"))
    authority = RareShoeBoundedCustodyAuthority.model_validate(_load("rare_shoe_bounded_custody_authority.json"))
    telemetry = RareShoeEdgeTelemetry.model_validate(_load("rare_shoe_nfc_clone_attack.json"))

    result = evaluate_rare_shoe_edge_telemetry(
        telemetry=telemetry,
        authority=authority,
        registration=registration,
        previous_scan_counter=41,
    )

    assert result["verified"] is False
    assert result["disposition"] == "quarantine"
    assert result["reason_code"] == "DYNAMIC_NFC_PROOF_INVALID"
    assert result["nfc_reason_code"] == "dynamic_nfc_proof_invalid"
    assert "DYNAMIC_NFC_PROOF_INVALID" in result["issues"]


def test_cross_asset_replay_preserves_join_key_and_commerce_refs_on_failure() -> None:
    bundle = _load("rare_shoe_happy_path_replay_bundle.json")
    bundle["edge_telemetry"][1] = _load("rare_shoe_cross_asset_replay.json")

    result = evaluate_rare_shoe_replay_bundle(bundle)

    assert result["verified"] is False
    assert result["reason_code"] == "CROSS_ASSET_REPLAY"
    assert result["workflow_join_key"] == WORKFLOW_JOIN_KEY
    assert result["product_ref"] == "rare-shoe-market:product:pe-jordan-001"
    assert result["quote_ref"] == "rare-shoe-market:quote:2026-05-15-0001"
    assert result["order_ref"] == "rare-shoe-market:order:2026-05-15-0001"


def test_delayed_telemetry_policy_accepts_observed_inside_window_only_within_submission_window() -> None:
    registration = CollectibleShoeRegistration.model_validate(_load("clean_rare_shoe_registration.json"))
    authority = RareShoeBoundedCustodyAuthority.model_validate(_load("rare_shoe_bounded_custody_authority.json"))
    delayed = RareShoeEdgeTelemetry.model_validate(_load("rare_shoe_delayed_telemetry.json"))
    expired = RareShoeEdgeTelemetry.model_validate(_load("rare_shoe_delayed_submission_expired.json"))

    accepted = evaluate_rare_shoe_edge_telemetry(
        telemetry=delayed,
        authority=authority,
        registration=registration,
        previous_scan_counter=41,
    )
    rejected = evaluate_rare_shoe_edge_telemetry(
        telemetry=expired,
        authority=authority,
        registration=registration,
        previous_scan_counter=41,
    )

    assert accepted["verified"] is True
    assert rejected["verified"] is False
    assert rejected["reason_code"] == "DELAYED_TELEMETRY_SUBMISSION_EXPIRED"
