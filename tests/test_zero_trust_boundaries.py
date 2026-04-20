from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

from seedcore.hal.custody.forensic_sealer import ForensicSealer
from seedcore.hal.drivers.robot_sim_driver import RobotSimExecutionDriver
from seedcore.hal.service import main as hal_main

from test_replay_router import _build_audit_record, _make_client


def _sign_token_payload(payload: dict[str, object]) -> str:
    return hal_main._expected_execution_token_signature(payload)  # noqa: SLF001 - boundary contract test


def _token_dict(
    token_id: str = "tok-zero-trust",
    *,
    endpoint_id: str | None = None,
    payload_hash: str | None = None,
    resource_state_hash: str | None = None,
    approval_transition_head: str | None = None,
    context_token: str | None = None,
    target_zone: str | None = None,
    ttl_seconds: float = 1.0,
) -> dict[str, object]:
    issued_at = datetime.now(timezone.utc)
    constraints: dict[str, str] = {}
    execution_preconditions: dict[str, str] = {}
    if endpoint_id is not None:
        constraints["endpoint_id"] = endpoint_id
        execution_preconditions["endpoint_id"] = endpoint_id
    if payload_hash is not None:
        constraints["payload_hash"] = payload_hash
        execution_preconditions["payload_hash"] = payload_hash
    if resource_state_hash is not None:
        execution_preconditions["resource_state_hash"] = resource_state_hash
    if approval_transition_head is not None:
        execution_preconditions["approval_transition_head"] = approval_transition_head
    if context_token is not None:
        execution_preconditions["context_token"] = context_token
    if target_zone is not None:
        constraints["target_zone"] = target_zone

    payload: dict[str, object] = {
        "token_id": token_id,
        "intent_id": "intent-zero-trust",
        "issued_at": issued_at.isoformat(),
        "valid_until": (issued_at + timedelta(seconds=ttl_seconds)).isoformat(),
        "contract_version": "snapshot:test",
        "constraints": constraints,
        "execution_preconditions": execution_preconditions,
    }
    payload["signature"] = _sign_token_payload(payload)
    return payload


def _payload_hash_for(request: hal_main.ActuationRequest) -> str:
    return hal_main._canonical_actuation_payload_hash(request)  # noqa: SLF001 - boundary contract test


@pytest.mark.asyncio
async def test_no_execution_without_authorization() -> None:
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
async def test_bypass_attempt_with_mismatched_endpoint_is_rejected() -> None:
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
                        "tok-endpoint-mismatch",
                        endpoint_id="robot_sim://wrong_endpoint",
                    ),
                )
            )
        assert "ExecutionToken endpoint mismatch" in str(exc.value)
    finally:
        driver.disconnect()
        hal_main.driver = original


@pytest.mark.asyncio
async def test_invalid_forged_execution_token_is_rejected() -> None:
    driver = RobotSimExecutionDriver(config={"runtime": "in_memory"})
    assert driver.connect() is True

    original = hal_main.driver
    hal_main.driver = driver
    try:
        forged = _token_dict("tok-forged-boundary")
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
async def test_payload_tampering_with_bound_execution_token_is_rejected() -> None:
    driver = RobotSimExecutionDriver(config={"runtime": "in_memory"})
    assert driver.connect() is True

    original = hal_main.driver
    hal_main.driver = driver
    try:
        baseline_request = hal_main.ActuationRequest(
            behavior_name="move_forward",
            behavior_params={"distance": 1},
            execution_token=None,
        )
        tampered_request = hal_main.ActuationRequest(
            behavior_name="move_forward",
            behavior_params={"distance": 2},
            execution_token=_token_dict(
                "tok-payload-boundary",
                endpoint_id=hal_main._derive_actuator_endpoint(driver),  # noqa: SLF001
                payload_hash=_payload_hash_for(baseline_request),
            ),
        )

        with pytest.raises(Exception) as exc:
            await hal_main.actuate(tampered_request)
        assert "ExecutionToken payload mismatch" in str(exc.value)
    finally:
        driver.disconnect()
        hal_main.driver = original


@pytest.mark.asyncio
async def test_execution_token_is_single_use() -> None:
    driver = RobotSimExecutionDriver(config={"runtime": "in_memory"})
    assert driver.connect() is True

    original = hal_main.driver
    hal_main.driver = driver
    try:
        request = hal_main.ActuationRequest(
            behavior_name="move_forward",
            behavior_params={"distance": 1},
            execution_token=None,
        )
        token = _token_dict(
            "tok-single-use",
            endpoint_id=hal_main._derive_actuator_endpoint(driver),  # noqa: SLF001
            payload_hash=_payload_hash_for(request),
        )

        first = await hal_main.actuate(
            hal_main.ActuationRequest(
                behavior_name="move_forward",
                behavior_params={"distance": 1},
                execution_token=token,
            )
        )
        assert first["status"] == "accepted"

        with pytest.raises(Exception) as exc:
            await hal_main.actuate(
                hal_main.ActuationRequest(
                    behavior_name="move_forward",
                    behavior_params={"distance": 1},
                    execution_token=token,
                )
            )
        assert "replayed ExecutionToken" in str(exc.value)
    finally:
        driver.disconnect()
        hal_main.driver = original


@pytest.mark.asyncio
async def test_execution_token_context_token_mismatch_is_rejected() -> None:
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
                        "tok-context-mismatch",
                        endpoint_id=hal_main._derive_actuator_endpoint(driver),  # noqa: SLF001
                        context_token="sha256:token-context-001",
                    ),
                    execution_context=hal_main.ExecutionPreconditions(
                        context_token="sha256:token-context-002",
                    ),
                )
            )
        assert "ExecutionToken context token mismatch" in str(exc.value)
    finally:
        driver.disconnect()
        hal_main.driver = original


def test_public_replay_projection_does_not_leak_evidence() -> None:
    record = _build_audit_record(
        task_id="task-zero-trust-public",
        intent_id="intent-zero-trust-public",
        asset_id="asset-1",
    )
    client = _make_client(record)

    response = client.get(
        "/replay/artifacts",
        params={"audit_id": record["id"], "projection": "public"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "public_artifacts" in body
    assert "evidence_bundle" not in body
    assert "policy_receipt" not in body
    assert "transition_receipts" not in body


def test_hal_sealer_restrictions_hold_for_attested_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEEDCORE_EVIDENCE_ED25519_PRIVATE_KEY_B64", raising=False)
    monkeypatch.delenv("SEEDCORE_EVIDENCE_ED25519_PRIVATE_KEY_PEM", raising=False)

    sealer = ForensicSealer(device_identity="robot_sim://unit-zero-trust")

    with pytest.raises(ValueError, match="hal_capture requires Ed25519 signing"):
        sealer.seal_custody_event_pilot(
            event_id="urn:seedcore:event:zero-trust",
            platform_state="allow",
            policy_hash="policy-receipt-zero-trust",
            auth_token="token-zero-trust",
            from_zone="zone-a",
            to_zone="zone-b",
            transition_receipt={"transition_receipt_id": "tr-zero-trust", "actuator_result_hash": "trajectory-hash"},
            actuator_telemetry={},
            media_hash_references=[],
            trajectory_hash=None,
            environmental_data={"temperatureC": 22.0},
        )
