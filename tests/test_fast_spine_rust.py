from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from seedcore.integrations.rust_kernel import (
    verify_execution_token_with_rust,
    verify_spine_session_with_rust,
)
from seedcore.robotics.fast_spine.authority import TokenAuthority
from seedcore.robotics.fast_spine.contracts import CommandChunk, digest
from seedcore.robotics.fast_spine.evidence import (
    seal_receipt,
    simulation_trust_bundle,
    verify_receipt,
)
from seedcore.robotics.fast_spine.rehearsal import fixture_spec, fixture_token
from seedcore.robotics.fast_spine.session import SessionRuntime
from seedcore.robotics.fast_spine.store import ClaimStore

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def signed_attempt(tmp_path):
    if not (ROOT / "rust/target/debug/seedcore-verify").is_file():
        pytest.skip("build seedcore-verify with documented Rust toolchain first")
    key = Ed25519PrivateKey.generate()
    spec = fixture_spec()
    now = datetime.now(timezone.utc)
    token = fixture_token(spec, key, now=now)
    bundle = simulation_trust_bundle(
        {
            "simulation-fixture-pdp": key.public_key(),
            "simulation-receipt-host": key.public_key(),
        },
        endpoint_id=spec.endpoint_id,
    )
    store = ClaimStore(tmp_path / "claims.sqlite")
    runtime = SessionRuntime(
        spec,
        TokenAuthority({"simulation-fixture-pdp": key.public_key()}),
        store,
        channel_key=b"c" * 32,
        clock=lambda: 100.0,
        wall_clock=lambda: now,
    )
    runtime.admit(token)
    runtime.submit(
        CommandChunk(
            session_id=spec.session_id,
            endpoint_id=spec.endpoint_id,
            boot_nonce=spec.boot_nonce,
            token_sha256=digest(token),
            sequence=1,
            generated_at_ms=0,
            waypoints=({"at_ms": 100, "positions_rad": [0.002] * 3},),
        )
    )
    runtime.local_stop()
    receipt = seal_receipt(runtime.receipt_payload(), key)
    yield key, spec, token, bundle, receipt
    store.close()


def test_real_ed25519_execution_token_matches_rust_kernel(signed_attempt):
    _, _, token, bundle, _ = signed_attempt
    report = verify_execution_token_with_rust(token, trust_bundle=bundle)
    assert report["verified"] is True, report
    forged = copy.deepcopy(token)
    forged["constraints"]["endpoint_id"] = "spine_sim://other"
    assert (
        verify_execution_token_with_rust(forged, trust_bundle=bundle)["verified"]
        is False
    )


@pytest.mark.parametrize("revoked", [False, True])
def test_cross_language_receipts_and_revoked_signers(signed_attempt, revoked):
    key, spec, token, bundle, receipt = signed_attempt
    if revoked:
        bundle["revoked_keys"] = ["simulation-receipt-host"]
    report = verify_spine_session_with_rust(
        receipt,
        spec=spec.model_dump(mode="json"),
        trust_bundle=bundle,
        token_sha256=digest(token),
    )
    assert report["verified"] is (not revoked), report
    assert report["physical_acceptance"] is False
    if not revoked:
        py = verify_receipt(
            receipt,
            {"simulation-receipt-host": key.public_key()},
            spec=spec,
            token_sha256=digest(token),
        )
        assert py["disposition"] == report["disposition"] == "verified_interrupted"


@pytest.mark.parametrize(
    "change", ["gap", "missing", "hardware", "binding", "bounds", "signature"]
)
def test_rust_quarantines_invalid_captured_evidence(signed_attempt, change):
    key, spec, token, bundle, receipt = signed_attempt
    payload = copy.deepcopy(receipt["artifact"])
    if change == "gap":
        payload["events"][1]["sequence"] = 99
    elif change == "missing":
        payload["events"].pop()
    elif change == "hardware":
        payload["profile"] = "hardware"
    elif change == "binding":
        payload["session_id"] = "other"
    elif change == "bounds":
        payload["events"][1]["positions_urad"][0] = 900000
    receipt = seal_receipt(payload, key)
    if change == "signature":
        receipt["signature"]["signature"] = "AAAA"
    report = verify_spine_session_with_rust(
        receipt,
        spec=spec.model_dump(mode="json"),
        trust_bundle=bundle,
        token_sha256=digest(token),
    )
    assert not report["verified"], report
    assert report["disposition"] == "quarantine"
