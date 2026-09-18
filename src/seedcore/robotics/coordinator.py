"""Synchronized planning, governed fan-out, and verified team-round barriers.

No physical atomicity is implied. Dispatch is never retried here. A partial or
uncertain round halts the mission and retains ownership for reconciliation.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from uuid import uuid4

from seedcore.models.task_payload import TaskPayload

from .agent import prepare_robot_task
from .cognitive import RobotCognitivePlanner
from .contracts import ActionClosure, RoundResult, TeamMission, TeamObservation

Dispatch = Callable[[TaskPayload], Awaitable[dict]]
Verify = Callable[[TaskPayload, dict], Awaitable[ActionClosure]]
Halt = Callable[[TeamMission, str], Awaitable[None]]


class RobotTeamCoordinator:
    """Single-owner mission runtime with mandatory trusted dispatch/verify/halt ports.

    dispatch must enter Coordinator.route_and_execute, not Organism or a socket.
    verify must load authentic RESULT_VERIFIER evidence and bind it to the task.
    halt must revoke/stop bounded sessions through the admitted safety path.
    Transport acknowledgements and model self-reports are not closure evidence.
    """

    def __init__(
        self, mission: TeamMission, planners: Mapping[str, RobotCognitivePlanner],
        *, dispatch: Dispatch, verify: Verify, halt: Halt,
        clock: Callable[[], float] = time.time,
    ):
        self._mission = TeamMission.model_validate(mission.model_dump(mode="json"))
        if set(planners) != {b.agent_id for b in mission.bindings}:
            raise ValueError("one planner required for each assigned agent")
        if not all(callable(port) for port in (dispatch, verify, halt)):
            raise ValueError("governed dispatch, verifier and halt adapters are required")
        self._planners = dict(planners)
        self._dispatch, self._verify, self._halt = dispatch, verify, halt
        self._clock = clock
        self._lock = asyncio.Lock()
        self._last_sequence = -1
        self.halted = False
        self.last_result: RoundResult | None = None

    @property
    def mission(self) -> TeamMission:
        return self._mission.model_copy(deep=True)

    @property
    def is_running(self) -> bool:
        return self._lock.locked()

    async def halt_mission(self) -> bool:
        """End an idle mission through the admitted safety port; never auto-release.

        For an active round, cancel and await its task first so any partial
        closures and uncertain submissions are recorded before reconciliation.
        """
        if self._lock.locked():
            raise RuntimeError("cancel and await the active round before halting")
        async with self._lock:
            return await self._request_halt("mission_end_requested")

    def _check_observation(self, observation: TeamObservation) -> None:
        if observation.mission_id != self._mission.mission_id:
            raise ValueError("wrong observation mission")
        if set(observation.robots) != {b.robot_id for b in self._mission.bindings}:
            raise ValueError("observation must cover exactly the mission robots")
        age = self._clock() - observation.observed_at
        if age < 0 or age > self._mission.max_observation_age_s:
            raise ValueError("stale or future observation")

    async def _request_halt(self, reason: str) -> bool:
        self.halted = True
        try:
            await asyncio.wait_for(
                self._halt(self._mission.model_copy(deep=True), reason),
                timeout=self._mission.execution_timeout_s,
            )
            return True
        except Exception:
            # No claim that cancellation, timeout, or an RPC error stopped hardware.
            return False

    async def _execute(self, task: TaskPayload) -> ActionClosure:
        # Recheck freshness immediately before submission (HAL must recheck at start).
        command = task.params["robot_command"]
        if self.halted:
            raise ValueError("team halted before dispatch")
        if self._clock() >= command["start_before"]:
            raise ValueError("command start deadline expired")
        result = await self._dispatch(task.model_copy(deep=True))
        if result.get("success") is not True:
            raise ValueError("governed execution did not succeed")
        closure = await self._verify(task.model_copy(deep=True), result)
        closure = ActionClosure.model_validate(closure.model_dump(mode="json"))
        expected = {
            "task_id": task.task_id,
            **{key: command[key] for key in (
                "mission_id", "round_id", "robot_id", "agent_id", "endpoint_id", "observation_sequence",
            )},
            "command_hash": task.params["payload_hash"],
        }
        if not closure.verified or any(getattr(closure, key) != value for key, value in expected.items()):
            raise ValueError("verification failed or closure identity mismatch")
        return closure

    async def run_round(self, observation: TeamObservation) -> RoundResult:
        if self._lock.locked():
            raise RuntimeError("a team round is already running")
        async with self._lock:
            if self.halted:
                raise RuntimeError("mission halted; reconcile before starting a new mission")
            round_id = str(uuid4())
            closures: dict[str, ActionClosure] = {}
            failures: dict[str, str] = {}
            halt_task: asyncio.Task | None = None

            def request_halt(reason: str) -> asyncio.Task:
                nonlocal halt_task
                if halt_task is None:
                    self.halted = True
                    halt_task = asyncio.create_task(self._request_halt(reason))
                return halt_task

            async def execute_and_record(binding, task):
                try:
                    closures[binding.agent_id] = await asyncio.wait_for(
                        self._execute(task), self._mission.execution_timeout_s,
                    )
                except Exception as exc:
                    failures[binding.agent_id] = type(exc).__name__
                    # Request revocation promptly; do not wait for a stuck peer.
                    request_halt("team_round_failed")

            try:
                observation = TeamObservation.model_validate(observation.model_dump(mode="json"))
                self._check_observation(observation)
                if observation.sequence <= self._last_sequence:
                    raise ValueError("observation sequence replay")
                self._last_sequence = observation.sequence

                async def plan(binding):
                    return await asyncio.wait_for(
                        self._planners[binding.agent_id].propose(
                            self._mission.model_copy(deep=True), binding.model_copy(deep=True),
                            observation.model_copy(deep=True),
                        ), timeout=self._mission.planning_timeout_s,
                    )

                proposals = await asyncio.gather(
                    *(plan(b) for b in self._mission.bindings), return_exceptions=True,
                )
                # Barrier: no robot is dispatched if ANY plan is invalid/late.
                self._check_observation(observation)
                tasks = []
                claimed: set[str] = set()
                for binding, proposal in zip(self._mission.bindings, proposals):
                    if isinstance(proposal, BaseException):
                        raise ValueError(f"planner failed for {binding.agent_id}")
                    claims = binding.exclusive_resources | proposal.exclusive_resources
                    if claimed & claims:
                        raise ValueError("conflicting exclusive resources in team round")
                    claimed.update(claims)
                    tasks.append(prepare_robot_task(
                        agent_id=binding.agent_id, binding=binding, mission=self._mission,
                        observation=observation, proposal=proposal, round_id=round_id,
                    ))
                await asyncio.gather(*(
                    execute_and_record(binding, task)
                    for binding, task in zip(self._mission.bindings, tasks)
                ))
            except asyncio.CancelledError:
                for binding in self._mission.bindings:
                    if binding.agent_id not in closures:
                        failures.setdefault(binding.agent_id, "cancelled_execution_uncertain")
                self.last_result = RoundResult(
                    mission_id=self._mission.mission_id, round_id=round_id,
                    observation_sequence=observation.sequence, status="halted",
                    closures=closures, failures=failures,
                )
                acknowledged = await asyncio.shield(request_halt("round_cancelled_execution_uncertain"))
                self.last_result = self.last_result.model_copy(update={"halt_acknowledged": acknowledged})
                raise
            except Exception as exc:
                failures["team"] = str(exc)

            self.last_result = RoundResult(
                mission_id=self._mission.mission_id, round_id=round_id,
                observation_sequence=observation.sequence,
                status="halted" if failures else "verified",
                closures=closures, failures=failures,
            )
            if failures:
                acknowledged = await asyncio.shield(request_halt("team_round_failed"))
                self.last_result = self.last_result.model_copy(update={"halt_acknowledged": acknowledged})
            return self.last_result.model_copy(deep=True)
