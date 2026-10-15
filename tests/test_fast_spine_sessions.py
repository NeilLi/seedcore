from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from seedcore.robotics.fast_spine.authority import TokenAuthority
from seedcore.robotics.fast_spine.contracts import CommandChunk, ControlMessage, digest
from seedcore.robotics.fast_spine.evidence import seal_receipt, verify_receipt
from seedcore.robotics.fast_spine.protocol import MessageType, encode_frame
from seedcore.robotics.fast_spine.rehearsal import fixture_spec, fixture_token
from seedcore.robotics.fast_spine.session import SessionRuntime
from seedcore.robotics.fast_spine.store import ClaimStore


class Clock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def wall(self):
        return datetime(2026, 10, 15, tzinfo=timezone.utc) + timedelta(
            seconds=self.value - 100
        )


@pytest.fixture
def setup(tmp_path):
    clock = Clock()
    key = Ed25519PrivateKey.generate()
    spec = fixture_spec()
    store = ClaimStore(tmp_path / "claims.sqlite")
    authority = TokenAuthority({"simulation-fixture-pdp": key.public_key()})
    runtime = SessionRuntime(
        spec,
        authority,
        store,
        channel_key=b"c" * 32,
        clock=clock,
        wall_clock=clock.wall,
    )
    token = fixture_token(spec, key, now=clock.wall())
    yield runtime, spec, token, clock, key, store, authority
    runtime.close()
    try:
        store.close()
    except Exception:
        pass


def chunk(spec, token, seq=1, *, at=100, generated=0, q=None):
    return CommandChunk(
        session_id=spec.session_id,
        endpoint_id=spec.endpoint_id,
        boot_nonce=spec.boot_nonce,
        token_sha256=digest(token),
        sequence=seq,
        generated_at_ms=generated,
        waypoints=(
            {"at_ms": at, "positions_rad": q or [0.002] * len(spec.initial_rad)},
        ),
    )


def control(spec, token, seq):
    return ControlMessage(
        session_id=spec.session_id,
        endpoint_id=spec.endpoint_id,
        boot_nonce=spec.boot_nonce,
        token_sha256=digest(token),
        sequence=seq,
    )


def test_allow_queue_apply_complete_and_signed_replay(setup):
    runtime, spec, token, clock, key, _, _ = setup
    assert runtime.admit(token)["state"] == "active"
    assert runtime.submit(chunk(spec, token))["status"] == "queued"
    assert runtime.status()["positions_rad"] == [0.0, 0.0, 0.0]  # ACK is not completion
    clock.value += 0.1
    runtime.poll()
    assert runtime.status()["positions_rad"] == [0.002] * 3
    runtime.control(control(spec, token, 2), MessageType.SESSION_END)
    receipt = seal_receipt(runtime.receipt_payload(), key)
    result = verify_receipt(
        receipt,
        {"simulation-receipt-host": key.public_key()},
        spec=spec,
        token_sha256=digest(token),
    )
    assert result["verified"] and result["disposition"] == "verified_completed"
    assert result["physical_acceptance"] is False


def test_expiry_during_validation_cannot_commit_a_chunk(setup, monkeypatch):
    runtime, spec, token, clock, *_ = setup
    runtime.admit(token)
    command = chunk(spec, token)

    def delayed_digest(value):
        clock.value += 1.0
        return digest(value)

    monkeypatch.setattr("seedcore.robotics.fast_spine.session.digest", delayed_digest)
    with pytest.raises(PermissionError, match="expired during"):
        runtime.submit(command)
    assert runtime.status()["reason"] == "session_deadline"
    assert not any(
        event["kind"] == "queued" for event in runtime.receipt_payload()["events"]
    )


@pytest.mark.parametrize("fault", ["exception", "nonfinite"])
def test_local_stop_works_even_when_the_capture_clock_fails(setup, fault):
    runtime, spec, token, *_ = setup
    runtime.admit(token)
    runtime.submit(chunk(spec, token))

    def broken_clock():
        if fault == "exception":
            raise RuntimeError("clock unavailable")
        return float("nan")

    runtime._clock = broken_clock
    runtime.local_stop()
    assert runtime.status()["reason"] == "local_stop"
    assert runtime.status()["queued_points"] == 0
    assert runtime.receipt_payload()["capture_complete"] is False


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "forged",
        "expired",
        "future",
        "endpoint",
        "principal",
        "scope",
        "debug",
    ],
)
def test_bad_authority_never_dispatches(setup, case):
    runtime, spec, token, clock, key, store, _ = setup
    if case == "missing":
        token = None
    elif case == "forged":
        token["constraints"]["endpoint_id"] = "spine_sim://other"
    elif case == "expired":
        token = fixture_token(spec, key, now=clock.wall() - timedelta(seconds=2))
    elif case == "future":
        token = fixture_token(spec, key, now=clock.wall() + timedelta(seconds=1))
    elif case == "endpoint":
        token = fixture_token(
            spec.model_copy(update={"endpoint_id": "spine_sim://other"}),
            key,
            now=clock.wall(),
        )
    elif case == "principal":
        token = fixture_token(
            spec.model_copy(update={"principal_id": "other"}), key, now=clock.wall()
        )
    elif case == "scope":
        token = fixture_token(
            spec.model_copy(update={"duration_ms": 2000}), key, now=clock.wall()
        )
    elif case == "debug":
        token["signature"]["signing_scheme"] = "debug_hash_v1"
    with pytest.raises(PermissionError):
        runtime.admit(token)
    assert runtime.status()["positions_rad"] == [0.0, 0.0, 0.0]
    assert runtime.status()["queued_points"] == 0


def test_consumption_survives_restart_and_cannot_be_released(setup, tmp_path):
    runtime, spec, token, clock, _, store, authority = setup
    runtime.admit(token)
    runtime.local_stop()
    store.close()
    restored = ClaimStore(tmp_path / "claims.sqlite")
    other = SessionRuntime(
        spec,
        authority,
        restored,
        channel_key=b"c" * 32,
        clock=clock,
        wall_clock=clock.wall,
    )
    with pytest.raises(PermissionError, match="replayed"):
        other.admit(token)
    restored.close()


@pytest.mark.parametrize(
    "change",
    [
        {"sequence": 2},
        {"endpoint_id": "spine_sim://other"},
        {"boot_nonce": "0" * 32},
        {"token_sha256": "0" * 64},
    ],
)
def test_bound_session_rejects_wrong_refresh_without_mutation(setup, change):
    runtime, spec, token, _, _, _, _ = setup
    runtime.admit(token)
    with pytest.raises(PermissionError):
        runtime.submit(chunk(spec, token).model_copy(update=change))
    assert runtime.status()["sequence"] == 0
    assert runtime.status()["queued_points"] == 0


def test_refresh_does_not_replay_token_or_extend_deadline(setup):
    runtime, spec, token, clock, _, _, _ = setup
    runtime.admit(token)
    deadline = runtime.status()["deadline_monotonic"]
    runtime.submit(chunk(spec, token))
    clock.value += 0.1
    runtime.submit(chunk(spec, token, 2, at=200, generated=100, q=[0.004] * 3))
    assert runtime.status()["deadline_monotonic"] == deadline
    with pytest.raises(PermissionError, match="replayed"):
        runtime.submit(chunk(spec, token, 2, at=250, generated=100))


def test_heartbeat_cannot_keep_stale_intent_alive(setup):
    runtime, spec, token, clock, _, _, _ = setup
    runtime.admit(token)
    runtime.submit(chunk(spec, token))
    clock.value += 0.15
    runtime.control(control(spec, token, 2), MessageType.HEARTBEAT)
    clock.value += 0.101
    runtime.poll()
    assert runtime.status()["reason"] == "stale_command"
    with pytest.raises(PermissionError):
        runtime.submit(chunk(spec, token, 3, at=400, generated=251))


@pytest.mark.parametrize(
    "case",
    [
        "revoke",
        "key_revoke",
        "store_down",
        "stale_authority",
        "clock_rollback",
        "local_stop",
    ],
)
def test_fault_fences_queue_and_never_auto_resumes(setup, case):
    runtime, spec, token, clock, _, store, _ = setup
    runtime.admit(token)
    runtime.submit(chunk(spec, token))
    if case == "revoke":
        store.revoke(token["token_id"])
    elif case == "key_revoke":
        store.revoke("simulation-fixture-pdp", kind="key")
    elif case == "store_down":
        store.close()
    elif case == "stale_authority":
        runtime._source = lambda *_: (False, clock.value - 1)
    elif case == "clock_rollback":
        clock.value -= 1
    else:
        runtime.local_stop()
    runtime.poll()
    assert runtime.status()["state"] == "fenced"
    assert runtime.status()["queued_points"] == 0
    clock.value += 0.1
    with pytest.raises(PermissionError):
        runtime.submit(chunk(spec, token, 2, at=200))


def test_entire_chunk_is_validated_before_queue_write(setup):
    runtime, spec, token, _, _, _, _ = setup
    runtime.admit(token)
    candidate = chunk(spec, token).model_dump(mode="json")
    candidate["waypoints"].append({"at_ms": 200, "positions_rad": [1.0, 0.0, 0.0]})
    with pytest.raises(PermissionError, match="envelope"):
        runtime.submit(CommandChunk.model_validate(candidate))
    assert runtime.status()["queued_points"] == 0
    assert runtime.status()["sequence"] == 0


def test_spline_extrema_are_checked_between_endpoints(setup):
    runtime, spec, token, _, _, _, _ = setup
    runtime.admit(token)
    with pytest.raises(PermissionError, match="spline"):
        runtime.submit(chunk(spec, token, at=10, q=[0.1] * 3))


def test_frame_authentication_precedes_dispatch(setup):
    runtime, spec, token, _, _, _, _ = setup
    runtime.admit(token)
    message = chunk(spec, token)
    bad = encode_frame(MessageType.CHUNK, 1, message.model_dump(mode="json"), b"x" * 32)
    with pytest.raises(ValueError, match="authentication"):
        runtime.accept_frame(bad)
    assert runtime.status()["queued_points"] == 0
    good = encode_frame(
        MessageType.CHUNK, 1, message.model_dump(mode="json"), b"c" * 32
    )
    assert runtime.accept_frame(good)["status"] == "queued"


def test_deadline_is_monotonic_even_if_wall_clock_rolls_back(setup):
    runtime, spec, token, clock, _, _, _ = setup
    runtime.admit(token)
    frozen = clock.wall()
    runtime._wall = lambda: frozen
    clock.value += 1.001
    runtime.poll()
    assert runtime.status()["reason"] == "session_deadline"


def test_watchdog_runs_without_browser_polling(tmp_path):
    key = Ed25519PrivateKey.generate()
    spec = fixture_spec()
    store = ClaimStore(tmp_path / "claims.sqlite")
    runtime = SessionRuntime(
        spec,
        TokenAuthority({"simulation-fixture-pdp": key.public_key()}),
        store,
        channel_key=b"c" * 32,
    )
    runtime.admit(fixture_token(spec, key))
    runtime.start_watchdog()
    try:
        until = time.monotonic() + 1
        while runtime.status()["state"] == "active" and time.monotonic() < until:
            time.sleep(0.01)
        assert runtime.status()["reason"] == "stale_command"
    finally:
        runtime.close()
        store.close()


@pytest.mark.parametrize(
    "tamper",
    [
        "gap",
        "missing",
        "stale",
        "wrong_session",
        "fake_hardware",
        "conflict",
        "signature",
    ],
)
def test_incomplete_or_mismatched_receipts_never_close(setup, tamper):
    runtime, spec, token, _, key, _, _ = setup
    runtime.admit(token)
    runtime.submit(chunk(spec, token))
    runtime.local_stop()
    payload = runtime.receipt_payload()
    if tamper == "gap":
        payload["events"][1]["sequence"] += 1
    elif tamper == "missing":
        payload["events"].pop(0)
    elif tamper == "stale":
        payload["events"][-1]["t_ms"] = -1
    elif tamper == "wrong_session":
        payload["session_id"] = "other"
    elif tamper == "fake_hardware":
        payload["profile"] = "hardware"
    elif tamper == "conflict":
        payload["outcome"] = "completed"
    receipt = seal_receipt(payload, key)
    if tamper == "signature":
        receipt["signature"]["signature"] = "AAAA"
    result = verify_receipt(
        receipt,
        {"simulation-receipt-host": key.public_key()},
        spec=spec,
        token_sha256=digest(token),
    )
    assert result["verified"] is False
    assert result["disposition"] == "quarantine"
