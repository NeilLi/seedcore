"""Translate one agent's advisory proposal into the existing governed inbox."""

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from seedcore.models.task_payload import TaskPayload

from .contracts import RobotBinding, RobotProposal, TeamMission, TeamObservation, digest


def validate_robot_assignment(task: dict, agent_id: str, *, now: float) -> None:
    """Fail closed on misrouting or proposal tampering before tool execution.

    Cryptographic admission is still the PDP/HAL's responsibility. In particular,
    the presence of a token here does not validate its signature or revocation.
    """
    params = task["params"]
    command = params["robot_command"]
    governance = params["governance"]
    intent = governance["action_intent"]
    token = governance["execution_token"]
    if (
        command["agent_id"] != agent_id
        or params["interaction"]["assigned_agent_id"] != agent_id
        or intent["principal"]["agent_id"] != agent_id
        or intent["resource"]["asset_id"] != command["robot_id"]
        or intent["action"]["parameters"]["robot_command"] != command
        or intent["action"]["parameters"]["endpoint_id"] != command["endpoint_id"]
        or intent["action"]["parameters"]["payload_hash"] != digest(command)
        or params["payload_hash"] != digest(command)
        or not token.get("token_id")
        or governance["policy_decision"].get("allowed") is not True
        or not command["observed_at"] <= now < command["start_before"]
        or len(params["tool_calls"]) != 1
        or params["tool_calls"][0]["name"] != command["tool_name"]
        or params["tool_calls"][0]["args"] != {"command": command}
    ):
        raise ValueError("robot assignment, governance, command, or deadline mismatch")


def prepare_robot_task(
    *, agent_id: str, binding: RobotBinding, mission: TeamMission,
    observation: TeamObservation, proposal: RobotProposal, round_id: str,
) -> TaskPayload:
    if binding.agent_id != agent_id or binding not in mission.bindings:
        raise ValueError("agent/robot binding mismatch")
    if observation.mission_id != mission.mission_id:
        raise ValueError("observation belongs to another mission")
    if proposal.observation_sequence != observation.sequence:
        raise ValueError("proposal uses another observation")
    if proposal.skill not in binding.skills:
        raise ValueError("robot does not advertise proposed skill")
    if proposal.duration_ms > binding.max_duration_ms:
        raise ValueError("proposal exceeds robot duration limit")
    # Model arguments stay nested: they cannot overwrite identity or governance.
    command = {
        "mission_id": mission.mission_id, "round_id": round_id,
        "robot_id": binding.robot_id, "agent_id": agent_id,
        "endpoint_id": binding.endpoint_id, "profile": binding.profile,
        "tool_name": binding.tool_name,
        "observation_sequence": observation.sequence,
        "observation_hash": digest(observation),
        "observed_at": observation.observed_at,
        "start_before": observation.observed_at + mission.max_observation_age_s,
        "skill": proposal.skill, "arguments": proposal.arguments,
        "duration_ms": proposal.duration_ms,
        "exclusive_resources": sorted(binding.exclusive_resources | proposal.exclusive_resources),
    }
    command_hash = digest(command)
    task_id = str(uuid5(NAMESPACE_URL, f"seedcore:{mission.mission_id}:{round_id}:{agent_id}"))
    deadline = datetime.fromtimestamp(command["start_before"], tz=timezone.utc).isoformat()
    tool_calls = [{"name": binding.tool_name, "args": {"command": command}}]
    return TaskPayload(
        task_id=task_id, type="action", domain="robotics",
        description=f"Bounded robot skill: {proposal.skill}",
        correlation_id=mission.mission_id,
        interaction_mode="coordinator_routed", assigned_agent_id=agent_id,
        routing_tools=[binding.tool_name], deadline_at=deadline, tool_calls=tool_calls,
        params={
            "interaction": {"mode": "coordinator_routed", "assigned_agent_id": agent_id},
            "routing": {"tools": [binding.tool_name], "hints": {"deadline_at": deadline}},
            "resource": {"asset_id": binding.robot_id, "provenance_hash": digest(observation)},
            "action_type": "ROBOT_SKILL",
            "endpoint_id": binding.endpoint_id,
            "robot_command": command,
            "payload_hash": command_hash,
            "tool_calls": tool_calls,
            "governance": {"require_action_intent": True},
            "metadata": {"robot_team": {"mission_id": mission.mission_id, "round_id": round_id}},
        },
    )
