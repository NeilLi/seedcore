#!/usr/bin/env python3
"""Build, run or compare offline robot experiments using the pinned MuJoCo engine."""

import argparse
import json
from pathlib import Path

from seedcore.robotics.mujoco_workbench.contracts import (
    ComparisonSpec,
    ControllerSpec,
    ExperimentCriteria,
    ExperimentSpec,
    RobotSpec,
)
from seedcore.robotics.mujoco_workbench.runtime import (
    compare_experiments,
    inspect_robot,
    inspect_model_package,
    run_experiment,
)


def example(name: str) -> ExperimentSpec | ComparisonSpec:
    if name == "contact":
        return ExperimentSpec(
            robot=RobotSpec(name="free-box", links=(), floating_base=True)
        )
    baseline = ExperimentSpec(
        controller=ControllerSpec(mode="position", values=(0.5, -0.5)),
        steps=1500,
        sample_every=15,
        criteria=ExperimentCriteria(
            final_joint_error_rad=0.05, max_joint_speed_rad_s=10
        ),
    )
    if name == "arm":
        return baseline
    candidate = baseline.model_dump(mode="json")
    candidate["controller"].update(kp=48.0)
    return ComparisonSpec(
        baseline=baseline, candidate=ExperimentSpec.model_validate(candidate)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", choices=("build", "run", "compare", "inspect-package")
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--spec", type=Path, help="RobotSpec, ExperimentSpec or ComparisonSpec JSON"
    )
    group.add_argument(
        "--manifest", type=Path, help="Versioned external model-package manifest"
    )
    group.add_argument(
        "--example", choices=("arm", "contact", "comparison"), default="arm"
    )
    parser.add_argument(
        "--output", type=Path, help="Write complete run/trace JSON for review"
    )
    parser.add_argument(
        "--mjcf-output", type=Path, help="Write generated model for the native viewer"
    )
    parser.add_argument(
        "--manifest-sha256", help="Require an independently pinned manifest digest"
    )
    args = parser.parse_args()
    if args.operation == "inspect-package":
        if not args.manifest or args.mjcf_output:
            parser.error("inspect-package requires --manifest and does not export MJCF")
        result = inspect_model_package(
            args.manifest, expected_manifest_sha256=args.manifest_sha256
        )
        payload = json.dumps(result, indent=2, allow_nan=False)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload + "\n")
        print(payload)
        return
    if args.manifest or args.manifest_sha256:
        parser.error("manifest options require inspect-package")
    if args.spec:
        raw = json.loads(args.spec.read_text())
    else:
        draft = example("comparison" if args.operation == "compare" else args.example)
        if isinstance(draft, ComparisonSpec) and args.operation != "compare":
            parser.error("the comparison example requires the compare operation")
        raw = (
            draft.robot.model_dump(mode="json")
            if args.operation == "build"
            else draft.model_dump(mode="json")
        )
    if args.operation == "build":
        result = inspect_robot(RobotSpec.model_validate(raw))
        xml = result["mjcf"]
    elif args.operation == "run":
        spec = ExperimentSpec.model_validate(raw)
        result = run_experiment(spec)
        xml = inspect_robot(spec.robot)["mjcf"] if args.mjcf_output else None
    else:
        if args.mjcf_output:
            parser.error("build each comparison model separately for MJCF export")
        result = compare_experiments(ComparisonSpec.model_validate(raw))
        xml = None
    if args.mjcf_output:
        args.mjcf_output.parent.mkdir(parents=True, exist_ok=True)
        args.mjcf_output.write_text(xml)
    payload = json.dumps(result, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n")
        print(f"Wrote {args.output.resolve()}")
    else:
        print(payload)


if __name__ == "__main__":
    main()
