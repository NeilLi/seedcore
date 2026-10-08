#!/usr/bin/env python3
"""Print offline navigation assessments; requires no robot, network or plotting."""

import argparse
from dataclasses import asdict
import json

from seedcore.robotics.navigation_sandbox import (
    CircleObstacle, PlanarCommand, PlanarState, SandboxConfig,
    assess_command, propose_dynamic_window,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("clear", "obstacle", "blocked"), default="clear")
    args = parser.parse_args()
    obstacles = {
        "clear": (),
        "obstacle": (CircleObstacle(0.55, 0.0, 0.05),),
        "blocked": (CircleObstacle(0.0, 0.0, 0.05),),
    }[args.scenario]
    config = SandboxConfig()
    state = PlanarState(speed=0.2)
    goal = (1.0, 0.0)
    print(json.dumps({
        "scenario": args.scenario,
        "config": asdict(config),
        "state": asdict(state),
        "goal": goal,
        "obstacles": [asdict(obstacle) for obstacle in obstacles],
        "proposed_straight_motion": asdict(assess_command(state, PlanarCommand(0.2, 0), obstacles, config)),
        "dynamic_window": asdict(propose_dynamic_window(state, goal, obstacles, config)),
    }, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
