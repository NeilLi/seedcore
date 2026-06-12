from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from seedcore.ops.evidence.nfc_counter_ledger import CounterStoreError, InMemoryNfcCounterLedger
from seedcore.ops.evidence.nfc_verification import (
    anchor_counter_key,
    expected_fixture_challenge_response_hash,
    verify_dynamic_nfc_evidence,
    verify_dynamic_nfc_evidence_with_counter_ledger,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nfc"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _clock() -> datetime:
    return datetime(2026, 6, 10, 12, 0, 2, tzinfo=timezone.utc)


def test_nfc_happy_path_verifies_with_replay_safe_metadata() -> None:
    context = _load("nfc_registry_context.json")
    evidence = _load("nfc_happy_path.json")

    result = verify_dynamic_nfc_evidence(evidence, context, clock=_clock)
    payload = result.model_dump(mode="json")

    assert result.verified is True
    assert result.disposition == "allow"
    assert result.reason_code == "rct_nfc_scan_verified"
    assert result.observed_counter_for_persistence == 42
    assert result.anchor_counter_key == "sha256:d8a9f3b1fixtureasset001|profile:nxp-ntag424-dna-fixture-v1"
    assert "challenge_nonce" not in payload
    assert "challenge_response_hash" not in payload
    assert "cmac_ref" not in payload


def test_nfc_replay_or_clone_counter_reuse_denies() -> None:
    result = verify_dynamic_nfc_evidence(_load("nfc_replay_attack.json"), _load("nfc_registry_context.json"), clock=_clock)

    assert result.verified is False
    assert result.disposition == "deny"
    assert result.reason_code == "dynamic_nfc_proof_invalid"
    assert result.observed_counter_for_persistence == 41


def test_nfc_stale_scan_quarantines() -> None:
    result = verify_dynamic_nfc_evidence(_load("nfc_stale_scan.json"), _load("nfc_registry_context.json"), clock=_clock)

    assert result.verified is False
    assert result.disposition == "quarantine"
    assert result.reason_code == "nfc_scan_too_stale"
    assert result.freshness_seconds == 122


def test_nfc_tamper_state_quarantines_after_valid_dynamic_proof() -> None:
    result = verify_dynamic_nfc_evidence(_load("nfc_tampered_tag.json"), _load("nfc_registry_context.json"), clock=_clock)

    assert result.verified is False
    assert result.disposition == "quarantine"
    assert result.reason_code == "hardware_tamper_detected"


def test_nfc_wrong_asset_anchor_denies() -> None:
    result = verify_dynamic_nfc_evidence(_load("nfc_wrong_asset.json"), _load("nfc_registry_context.json"), clock=_clock)

    assert result.verified is False
    assert result.disposition == "deny"
    assert result.reason_code == "nfc_asset_anchor_mismatch"


def test_nfc_missing_required_field_quarantines_as_incomplete() -> None:
    result = verify_dynamic_nfc_evidence(_load("nfc_missing_required_field.json"), _load("nfc_registry_context.json"), clock=_clock)

    assert result.verified is False
    assert result.disposition == "quarantine"
    assert result.reason_code == "nfc_payload_incomplete"


def test_nfc_check_order_prefers_asset_binding_before_staleness() -> None:
    evidence = _load("nfc_stale_scan.json")
    evidence["nfc_payload"]["asset_ref"] = "asset:rare-shoe:other"

    result = verify_dynamic_nfc_evidence(evidence, _load("nfc_registry_context.json"), clock=_clock)

    assert result.disposition == "deny"
    assert result.reason_code == "nfc_asset_anchor_mismatch"


def test_fixture_response_hash_helper_is_deterministic_and_anchor_scoped() -> None:
    context = _load("nfc_registry_context.json")
    evidence = _load("nfc_happy_path.json")
    payload = evidence["nfc_payload"]

    assert payload["challenge_response_hash"] == expected_fixture_challenge_response_hash(
        mock_root_key=context["mock_root_key"],
        nfc_uid_hash=payload["nfc_uid_hash"],
        anchor_profile_ref=payload["anchor_profile_ref"],
        cmac_ref=payload["cmac_ref"],
        asset_ref=payload["asset_ref"],
        workflow_join_key=payload["workflow_join_key"],
        challenge_nonce=payload["challenge_nonce"],
        scan_counter=payload["scan_counter"],
    )
    assert anchor_counter_key(
        nfc_uid_hash=payload["nfc_uid_hash"],
        anchor_profile_ref=payload["anchor_profile_ref"],
    ) == "sha256:d8a9f3b1fixtureasset001|profile:nxp-ntag424-dna-fixture-v1"


def test_nfc_persistent_counter_successive_scans() -> None:
    context = _load("nfc_registry_context.json")
    evidence = _load("nfc_happy_path.json")
    ledger = InMemoryNfcCounterLedger()

    # Initial scan verifies successfully and updates the store to 42
    result = verify_dynamic_nfc_evidence_with_counter_ledger(
        evidence,
        context,
        counter_ledger=ledger,
        clock=_clock,
    )
    assert result.verified is True
    assert result.disposition == "allow"
    assert result.observed_counter_for_persistence == 42

    # A subsequent scan with a lower counter is denied
    evidence_retry = _load("nfc_happy_path.json")
    evidence_retry["nfc_payload"]["scan_counter"] = 41
    result_retry = verify_dynamic_nfc_evidence_with_counter_ledger(
        evidence_retry,
        context,
        counter_ledger=ledger,
        clock=_clock,
    )
    assert result_retry.verified is False
    assert result_retry.disposition == "deny"
    assert result_retry.reason_code == "dynamic_nfc_proof_invalid"

    # A subsequent scan with an equal counter is denied
    evidence_retry_equal = _load("nfc_happy_path.json")
    evidence_retry_equal["nfc_payload"]["scan_counter"] = 42
    result_retry_equal = verify_dynamic_nfc_evidence_with_counter_ledger(
        evidence_retry_equal,
        context,
        counter_ledger=ledger,
        clock=_clock,
    )
    assert result_retry_equal.verified is False
    assert result_retry_equal.disposition == "deny"
    assert result_retry_equal.reason_code == "dynamic_nfc_proof_invalid"

    # A subsequent scan with a higher counter is allowed (and updates the store to 43)
    evidence_higher = _load("nfc_happy_path.json")
    evidence_higher["nfc_payload"]["scan_counter"] = 43
    # Update expected hash in fixture for counter 43 to match new CMAC signature
    payload = evidence_higher["nfc_payload"]
    payload["challenge_response_hash"] = expected_fixture_challenge_response_hash(
        mock_root_key=context["mock_root_key"],
        nfc_uid_hash=payload["nfc_uid_hash"],
        anchor_profile_ref=payload["anchor_profile_ref"],
        cmac_ref=payload["cmac_ref"],
        asset_ref=payload["asset_ref"],
        workflow_join_key=payload["workflow_join_key"],
        challenge_nonce=payload["challenge_nonce"],
        scan_counter=43,
    )
    result_higher = verify_dynamic_nfc_evidence_with_counter_ledger(
        evidence_higher,
        context,
        counter_ledger=ledger,
        clock=_clock,
    )
    assert result_higher.verified is True
    assert result_higher.disposition == "allow"
    assert result_higher.observed_counter_for_persistence == 43


def test_nfc_stateful_verifier_quarantines_on_counter_store_error() -> None:
    class BrokenLedger:
        def get_highest_counter(self, **kwargs):
            raise CounterStoreError("Simulated DB connection failure")

    context = _load("nfc_registry_context.json")
    evidence = _load("nfc_happy_path.json")

    result = verify_dynamic_nfc_evidence_with_counter_ledger(
        evidence,
        context,
        counter_ledger=BrokenLedger(),
        clock=_clock,
    )
    assert result.verified is False
    assert result.disposition == "quarantine"
    assert result.reason_code == "counter_store_unavailable"
    assert "Simulated DB connection failure" in result.issues[0]
