#!/usr/bin/env python3
"""Offline contract demo only: fixture observations, deterministic advisors, NO actuation.

Run from repository root with PYTHONPATH=src .venv/bin/python
scripts/robotics/plan_team_demo.py --scenario football (or work).
"""

import argparse
import asyncio
import json
import time

from seedcore.robotics.agent import prepare_robot_task
from seedcore.robotics.cognitive import RobotCognitivePlanner
from seedcore.robotics.contracts import RobotBinding, TeamMission, TeamObservation
from seedcore.robotics.roster import RobotTeamRoster


async def main(scenario: str):
    names = ("blue", "orange")
    football = scenario == "football"
    team = TeamMission(
        mission_id=f"demo-{scenario}", organ_id="robotics",
        objective=("Play football: blue attacks +x; orange attacks -x" if football
                   else "Inspect two separate work areas before a later verified handoff"),
        mode="competitive" if football else "cooperative",
        roles={"blue": "attack +x" if football else "inspect left work area",
               "orange": "attack -x" if football else "inspect right work area"},
        bindings=tuple(RobotBinding(
            robot_id=f"duck-{name}", agent_id=name, organ_id="robotics",
            endpoint_id=f"hal://microduck/{name}",
            # Contract example, not a tool registered by this demo.
            tool_name="microduck.bounded_skill", profile="simulation",
            skills={"approach_ball", "inspect_area", "hold"},
            exclusive_resources={f"work-area-{name}"} if not football else set(),
        ) for name in names),
    )
    roster = RobotTeamRoster("robotics")
    roster.reserve(team, set(names))
    observation = TeamObservation(
        mission_id=team.mission_id, sequence=1, observed_at=time.time(),
        robots={"duck-blue": {"position": [-1, 0]}, "duck-orange": {"position": [1, 0]}},
        world={"source": "offline-fixture", "ball": [0, 0]},
    )

    async def fixture_advisor(context):
        return {
            "observation_sequence": context["observation"]["sequence"],
            "skill": "approach_ball" if football else "inspect_area",
            "arguments": {"attack_direction": 1 if context["robot_id"] == "duck-blue" else -1}
            if football else {"area": context["role"]},
            "duration_ms": 500,
        }

    proposals = await asyncio.gather(*(
        RobotCognitivePlanner(fixture_advisor).propose(team, binding, observation)
        for binding in team.bindings
    ))
    tasks = [prepare_robot_task(
        agent_id=binding.agent_id, binding=binding, mission=team,
        observation=observation, proposal=proposal, round_id="dry-run-1",
    ).model_dump(mode="json") for binding, proposal in zip(team.bindings, proposals)]
    print(json.dumps({
        "mode": "OFFLINE_DRY_RUN_NO_ACTUATION", "model": "deterministic fixture (not GPT)",
        "tasks_requiring_pdp_admission": tasks,
    }, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("football", "work"), default="football")
    asyncio.run(main(parser.parse_args().scenario))
