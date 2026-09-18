"""Organ-local reservations; deployment must have one owner per endpoint."""

from .contracts import TeamMission


class RobotTeamRoster:
    def __init__(self, organ_id: str):
        self.organ_id = organ_id
        self._missions: dict[str, TeamMission] = {}

    def reserve(self, mission: TeamMission, agent_ids: set[str]) -> None:
        mission = TeamMission.model_validate(mission.model_dump(mode="json"))
        if mission.organ_id != self.organ_id:
            raise ValueError("mission belongs to another organ")
        if mission.mission_id in self._missions:
            raise ValueError("mission already reserved")
        if not {b.agent_id for b in mission.bindings} <= agent_ids:
            raise ValueError("mission contains an unregistered agent")
        for active in self._missions.values():
            for key in ("robot_id", "agent_id", "endpoint_id"):
                if {getattr(b, key) for b in active.bindings} & {
                    getattr(b, key) for b in mission.bindings
                }:
                    raise ValueError(f"{key} already reserved by {active.mission_id}")
        self._missions[mission.mission_id] = mission

    def get(self, mission_id: str) -> TeamMission:
        return self._missions[mission_id].model_copy(deep=True)

    def assert_agent_removable(self, agent_id: str) -> None:
        if any(b.agent_id == agent_id for m in self._missions.values() for b in m.bindings):
            raise ValueError("agent has a reserved robot mission; reconcile before removal")

    def release_after_reconciliation(self, mission_id: str) -> None:
        """Administrative lifecycle operation, not evidence closure or a robot stop.

        The owner must settle uncertain actions/revoke sessions BEFORE calling.
        Never invoked automatically on timeout, cancellation, or agent failure.
        """
        del self._missions[mission_id]

