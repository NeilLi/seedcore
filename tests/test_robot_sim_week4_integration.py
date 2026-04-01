from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from seedcore.hal.custody.transition_receipts import verify_transition_receipt
from seedcore.hal.drivers.robot_sim_driver import RobotSimExecutionDriver
from seedcore.hal.robot_sim.actuator.execution_registry import ExecutionRegistry
from seedcore.hal.service import main as hal_main
from seedcore.ops.evidence.builder import attach_evidence_bundle


def _token_dict(
    token_id: str = "tok-week4",
    *,
    endpoint_id: str | None = None,
    target_zone: str | None = None,
    ttl_seconds: int = 5,
) -> dict[str, object]:
    issued_at = datetime.now(timezone.utc)
    constraints: dict[str, str] = {}
    if endpoint_id is not None:
        constraints["endpoint_id"] = endpoint_id
    if target_zone is not None:
        constraints["target_zone"] = target_zone

    payload = {
        "token_id": token_id,
        "intent_id": "intent-week4",
        "issued_at": issued_at.isoformat(),
        "valid_until": (issued_at + timedelta(seconds=ttl_seconds)).isoformat(),
        "contract_version": "snapshot:test",
        "constraints": constraints,
    }
    payload["signature"] = _sign_token_payload(payload)
    return payload


def _sign_token_payload(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        {
            "token_id": payload["token_id"],
            "intent_id": payload["intent_id"],
            "issued_at": payload["issued_at"],
            "valid_until": payload["valid_until"],
            "contract_version": payload["contract_version"],
            "constraints": payload["constraints"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hmac.new(
        b"seedcore-dev-signing-secret",
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def test_behavior_registry_auto_discovery_registers_plugins() -> None:
    registry = ExecutionRegistry()
    names = registry.auto_register_from_behaviors()

    assert "move_forward" in names
    assert "rotate" in names
    assert "scan_environment" in names
    assert "pick_object" in names
    assert "actuate_pose" in names


@pytest.mark.asyncio
async def test_robot_sim_endpoint_requires_valid_execution_token() -> None:
    driver = RobotSimExecutionDriver(config={"runtime": "in_memory"})
    assert driver.connect() is True

    original = hal_main.driver
    hal_main.driver = driver
    try:
        with pytest.raises(Exception) as exc:
            await hal_main.actuate(
                hal_main.ActuationRequest(
                    behavior_name="move_forward",
                    behavior_params={"distance": 1},
                    execution_token=None,
                )
            )
        assert "invalid ExecutionToken" in str(exc.value)
    finally:
        driver.disconnect()
        hal_main.driver = original


@pytest.mark.asyncio
async def test_week4_allow_to_endpoint_response_and_evidence_capture() -> None:
    driver = RobotSimExecutionDriver(config={"runtime": "in_memory"})
    assert driver.connect() is True

    original = hal_main.driver
    hal_main.driver = driver
    try:
        response = await hal_main.actuate(
            hal_main.ActuationRequest(
                behavior_name="move_forward",
                behavior_params={"distance": 2},
                execution_token=_token_dict(
                    "tok-allow-1",
                    endpoint_id="robot_sim://pybullet_r2d2_01",
                ),
            )
        )

        assert response["status"] == "accepted"
        assert response["actuator_ack"] is True
        assert response["actuator_endpoint"].startswith("robot_sim://")
        assert isinstance(response["result_hash"], str)
        assert len(response["result_hash"]) == 64
        assert isinstance(response.get("transition_receipt"), dict)
        assert (
            verify_transition_receipt(
                response["transition_receipt"],
                expected_intent_id="intent-week4",
                expected_token_id="tok-allow-1",
                expected_endpoint_id=response["actuator_endpoint"],
            )
            is None
        )

        task_dict = {
            "task_id": "task-week4-1",
            "params": {
                "governance": {
                    "action_intent": {
                        "intent_id": "intent-week4",
                        "resource": {"target_zone": "lab-a"},
                    },
                    "execution_token": {"token_id": "tok-allow-1"},
                }
            },
        }
        envelope = {
            "payload": {"results": [{"tool": "reachy.motion", "output": response}]},
            "meta": {"exec": {"finished_at": datetime.now(timezone.utc).isoformat()}},
        }

        out = attach_evidence_bundle(
            task_dict=task_dict,
            envelope=envelope,
            organ_id="actuator_organ_1",
            agent_id="agent_week4",
        )

        bundle = out["meta"]["evidence_bundle"]
        summary = bundle["evidence_inputs"]["execution_summary"]
        assert summary["actuator_endpoint"] == response["actuator_endpoint"]
        assert summary["actuator_result_hash"] == response["result_hash"]
        transition_receipts = bundle["evidence_inputs"]["transition_receipts"]
        assert transition_receipts
        assert transition_receipts[0]["payload_hash"] == response["transition_receipt"]["payload_hash"]
    finally:
        driver.disconnect()
        hal_main.driver = original


@pytest.mark.asyncio
async def test_robot_sim_endpoint_emits_ed25519_transition_receipt_when_key_configured(
    monkeypatch,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    endpoint_id = "robot_sim://pybullet_r2d2_01"
    monkeypatch.setenv(
        "SEEDCORE_HAL_RECEIPT_PRIVATE_KEY_B64",
        base64.b64encode(private_bytes).decode("ascii"),
    )
    monkeypatch.setenv(
        "SEEDCORE_HAL_RECEIPT_PUBLIC_KEYS_JSON",
        json.dumps({endpoint_id: base64.b64encode(public_bytes).decode("ascii")}),
    )

    driver = RobotSimExecutionDriver(config={"runtime": "in_memory"})
    assert driver.connect() is True

    original = hal_main.driver
    hal_main.driver = driver
    try:
        response = await hal_main.actuate(
            hal_main.ActuationRequest(
                behavior_name="move_forward",
                behavior_params={"distance": 1},
                execution_token=_token_dict(
                    "tok-ed25519-1",
                    endpoint_id=endpoint_id,
                ),
            )
        )

        receipt = response["transition_receipt"]
        assert receipt["signer_metadata"]["signing_scheme"] == "ed25519"
        assert verify_transition_receipt(
            receipt,
            expected_intent_id="intent-week4",
            expected_token_id="tok-ed25519-1",
            expected_endpoint_id=endpoint_id,
        ) is None
    finally:
        driver.disconnect()
        hal_main.driver = original


@pytest.mark.asyncio
async def test_robot_sim_endpoint_rejects_forged_execution_token() -> None:
    driver = RobotSimExecutionDriver(config={"runtime": "in_memory"})
    assert driver.connect() is True

    original = hal_main.driver
    hal_main.driver = driver
    try:
        forged = _token_dict("tok-forged-1")
        forged["signature"] = "forged-signature"

        with pytest.raises(Exception) as exc:
            await hal_main.actuate(
                hal_main.ActuationRequest(
                    behavior_name="move_forward",
                    behavior_params={"distance": 1},
                    execution_token=forged,
                )
            )
        assert "forged ExecutionToken" in str(exc.value)
    finally:
        driver.disconnect()
        hal_main.driver = original


@pytest.mark.asyncio
async def test_robot_sim_endpoint_rejects_expired_execution_token() -> None:
    driver = RobotSimExecutionDriver(config={"runtime": "in_memory"})
    assert driver.connect() is True

    original = hal_main.driver
    hal_main.driver = driver
    try:
        expired = _token_dict("tok-expired-1")
        issued_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        expired["issued_at"] = issued_at.isoformat()
        expired["valid_until"] = (issued_at + timedelta(minutes=1)).isoformat()
        expired["signature"] = _sign_token_payload(expired)

        with pytest.raises(Exception) as exc:
            await hal_main.actuate(
                hal_main.ActuationRequest(
                    behavior_name="move_forward",
                    behavior_params={"distance": 1},
                    execution_token=expired,
                )
            )
        assert "expired ExecutionToken" in str(exc.value)
    finally:
        driver.disconnect()
        hal_main.driver = original


@pytest.mark.asyncio
async def test_robot_sim_endpoint_rejects_execution_token_exceeding_max_ttl() -> None:
    driver = RobotSimExecutionDriver(config={"runtime": "in_memory"})
    assert driver.connect() is True

    original = hal_main.driver
    hal_main.driver = driver
    try:
        with pytest.raises(Exception) as exc:
            await hal_main.actuate(
                hal_main.ActuationRequest(
                    behavior_name="move_forward",
                    behavior_params={"distance": 1},
                    execution_token=_token_dict("tok-long-ttl-1", ttl_seconds=30),
                )
            )
        assert "expired ExecutionToken" in str(exc.value)
    finally:
        driver.disconnect()
        hal_main.driver = original


@pytest.mark.asyncio
async def test_robot_sim_endpoint_rejects_revoked_execution_token(monkeypatch) -> None:
    class FakeRedis:
        def exists(self, key: str) -> int:
            return int(key.endswith("tok-revoked-1"))

        def get(self, key: str) -> None:
            return None

    monkeypatch.setattr(hal_main, "get_redis_client", lambda: FakeRedis())

    driver = RobotSimExecutionDriver(config={"runtime": "in_memory"})
    assert driver.connect() is True

    original = hal_main.driver
    hal_main.driver = driver
    try:
        with pytest.raises(Exception) as exc:
            await hal_main.actuate(
                hal_main.ActuationRequest(
                    behavior_name="move_forward",
                    behavior_params={"distance": 1},
                    execution_token=_token_dict("tok-revoked-1"),
                )
            )
        assert "revoked ExecutionToken" in str(exc.value)
    finally:
        driver.disconnect()
        hal_main.driver = original


@pytest.mark.asyncio
async def test_robot_sim_endpoint_rejects_execution_token_after_estop_cutoff(monkeypatch) -> None:
    class FakeRedis:
        def exists(self, key: str) -> int:
            return 0

        def get(self, key: str) -> str | None:
            if key == hal_main.EXECUTION_TOKEN_REVOCATION_CUTOFF_KEY:
                return datetime.now(timezone.utc).isoformat()
            return None

    monkeypatch.setattr(hal_main, "get_redis_client", lambda: FakeRedis())

    driver = RobotSimExecutionDriver(config={"runtime": "in_memory"})
    assert driver.connect() is True

    original = hal_main.driver
    hal_main.driver = driver
    try:
        with pytest.raises(Exception) as exc:
            await hal_main.actuate(
                hal_main.ActuationRequest(
                    behavior_name="move_forward",
                    behavior_params={"distance": 1},
                    execution_token=_token_dict("tok-estop-1"),
                )
            )
        assert "revoked ExecutionToken" in str(exc.value)
    finally:
        driver.disconnect()
        hal_main.driver = original


@pytest.mark.asyncio
async def test_admin_revoke_execution_token_stores_crl_entry(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeRedis:
        def setex(self, key: str, ttl_seconds: int, value: str) -> bool:
            captured["key"] = key
            captured["ttl_seconds"] = ttl_seconds
            captured["value"] = value
            return True

    monkeypatch.setattr(hal_main, "get_redis_client", lambda: FakeRedis())

    response = await hal_main.revoke_execution_token(
        hal_main.RevokeExecutionTokenRequest(token_id="tok-admin-1", reason="operator revoke")
    )

    assert response["status"] == "revoked"
    assert response["token_id"] == "tok-admin-1"
    assert captured["key"] == f"{hal_main.EXECUTION_TOKEN_REVOCATION_PREFIX}tok-admin-1"
    assert captured["ttl_seconds"] == hal_main.DEFAULT_EXECUTION_TOKEN_CRL_TTL_SECONDS
    assert captured["value"] == "1"


@pytest.mark.asyncio
async def test_admin_estop_sets_cutoff_and_stops_driver(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeRedis:
        def set(self, key: str, value: str) -> bool:
            captured["key"] = key
            captured["value"] = value
            return True

    monkeypatch.setattr(hal_main, "get_redis_client", lambda: FakeRedis())

    driver = RobotSimExecutionDriver(config={"runtime": "in_memory"})
    assert driver.connect() is True

    original = hal_main.driver
    hal_main.driver = driver
    try:
        response = await hal_main.emergency_stop_execution_tokens(
            hal_main.EmergencyStopRequest(reason="operator estop")
        )
        assert response["status"] == "emergency_stopped"
        assert captured["key"] == hal_main.EXECUTION_TOKEN_REVOCATION_CUTOFF_KEY
        assert driver.state.value == "emergency_stop"
    finally:
        driver.disconnect()
        hal_main.driver = original


@pytest.mark.asyncio
async def test_admin_clear_estop_removes_cutoff(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeRedis:
        def delete(self, key: str) -> int:
            captured["key"] = key
            return 1

    monkeypatch.setattr(hal_main, "get_redis_client", lambda: FakeRedis())

    response = await hal_main.clear_emergency_stop_execution_tokens()

    assert response["status"] == "emergency_stop_cleared"
    assert response["cleared"] is True
    assert captured["key"] == hal_main.EXECUTION_TOKEN_REVOCATION_CUTOFF_KEY


@pytest.mark.asyncio
async def test_robot_sim_endpoint_rejects_endpoint_constraint_mismatch() -> None:
    driver = RobotSimExecutionDriver(config={"runtime": "in_memory"})
    assert driver.connect() is True

    original = hal_main.driver
    hal_main.driver = driver
    try:
        with pytest.raises(Exception) as exc:
            await hal_main.actuate(
                hal_main.ActuationRequest(
                    behavior_name="move_forward",
                    behavior_params={"distance": 1},
                    execution_token=_token_dict(
                        "tok-mismatch-1",
                        endpoint_id="robot_sim://other_endpoint",
                    ),
                )
            )
        assert "endpoint mismatch" in str(exc.value)
    finally:
        driver.disconnect()
        hal_main.driver = original


@pytest.mark.asyncio
async def test_robot_sim_endpoint_rejects_target_zone_mismatch_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HAL_TARGET_ZONE", "lab-a")
    driver = RobotSimExecutionDriver(config={"runtime": "in_memory"})
    assert driver.connect() is True

    original = hal_main.driver
    hal_main.driver = driver
    try:
        with pytest.raises(Exception) as exc:
            await hal_main.actuate(
                hal_main.ActuationRequest(
                    behavior_name="move_forward",
                    behavior_params={"distance": 1},
                    execution_token=_token_dict(
                        "tok-zone-1",
                        target_zone="lab-b",
                    ),
                )
            )
        assert "target zone mismatch" in str(exc.value)
    finally:
        driver.disconnect()
        hal_main.driver = original
