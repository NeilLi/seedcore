from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from seedcore.hal.drivers.robot_sim_driver import RobotSimExecutionDriver
from seedcore.hal.robot_sim.actuator.execution_registry import ExecutionRegistry
from seedcore.hal.service import main as hal_main
from seedcore.ops.evidence.builder import attach_evidence_bundle


def _token_dict(token_id: str = "tok-week4") -> dict[str, str]:
    return {
        "token_id": token_id,
        "intent_id": "intent-week4",
        "valid_until": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        "signature": "sig-week4",
    }


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
                execution_token=_token_dict("tok-allow-1"),
            )
        )

        assert response["status"] == "accepted"
        assert response["actuator_ack"] is True
        assert response["actuator_endpoint"].startswith("robot_sim://")
        assert isinstance(response["result_hash"], str)
        assert len(response["result_hash"]) == 64

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
        assert bundle["execution_receipt"]["actuator_endpoint"] == response["actuator_endpoint"]
        assert bundle["execution_receipt"]["actuator_result_hash"] == response["result_hash"]
    finally:
        driver.disconnect()
        hal_main.driver = original
