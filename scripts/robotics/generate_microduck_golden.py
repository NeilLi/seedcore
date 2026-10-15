#!/usr/bin/env python3
"""Reproduce observation goldens from pinned upstream Rust, not SeedCore's builder.

ONNX actions come from ONNX ReferenceEvaluator, independently of ONNX Runtime.
This is export/artifact replay parity, NOT a training-checkpoint comparison.
No upstream Python module is imported or executed, and no hardware is opened.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def generate(runtime_checkout: Path, policy_path: Path, output: Path):
    import onnx
    from onnx.reference import ReferenceEvaluator

    profile = json.loads(
        (ROOT / "packages/robotics-profiles/microduck-sim-v1.json").read_text()
    )
    revision = profile["runtime"]["revision"]
    relative = "duck-control/src/obs.rs"
    source = subprocess.check_output(
        ["git", "-C", str(runtime_checkout), "show", f"{revision}:{relative}"]
    )
    if hashlib.sha256(source).hexdigest() != profile["runtime"]["files"][relative]:
        raise ValueError("upstream observation source pin mismatch")
    policy_bytes = policy_path.read_bytes()
    if hashlib.sha256(policy_bytes).hexdigest() != profile["policy"]["sha256"]:
        raise ValueError("policy SHA-256 mismatch")
    home = list(profile["home_rad"])
    home.insert(9, 0.0)
    cases = []
    random = np.random.default_rng(14015)
    for index in range(16):
        q = np.asarray(home) + (random.uniform(-0.1, 0.1, 15) if index else 0)
        q[9] = 0.4  # Mouth is deliberately distinguishable and must not leak.
        cases.append(
            {
                "id": f"source-vector-{index:02d}",
                "input": {
                    "positions": q.tolist(),
                    "velocities": random.uniform(-0.2, 0.2, 15).tolist(),
                    "gyro": random.uniform(-0.2, 0.2, 3).tolist(),
                    "gravity": [0.0, 0.0, -1.0],
                    "previous_action": random.uniform(-0.1, 0.1, 14).tolist(),
                    "twist": [0.01 * index, 0.0, 0.0],
                    "head": [0.01, -0.02, 0.03, -0.04],
                    "body": [0.0, 0.0, 0.001, 0.002, -0.003, 0.0],
                },
            }
        )

    def array(values):
        return "[" + ",".join(repr(float(x)) for x in values) + "]"

    rust = """mod model {pub const NUM_JOINTS:usize=15; pub const MOUTH_INDEX:usize=9;}
mod imu {pub struct ImuData {pub gyro:[f64;3],pub gravity:[f64;3]}}
mod obs;
fn main() {
"""
    for case in cases:
        x = case["input"]
        rust += f"""{{let imu=imu::ImuData{{gyro:{array(x["gyro"])},gravity:{array(x["gravity"])}}};
let command=obs::Command{{twist:{array(x["twist"])},head:{array(x["head"])},body:obs::BodyPose{{z:0.001,roll:0.002,pitch:-0.003}}}};
let result=obs::Observation::build(&imu,&{array(x["positions"])},&{array(x["velocities"])},&{array(home)},&{array(x["previous_action"])},&command);
println!("{{:?}}",result.as_slice());}}
"""
    rust += "}\n"
    # The upstream module includes compile-time IPC dimension checks.
    rust = (
        "extern crate self as duck_ipc_proto; pub const POLICY_OBS_LEN:usize=61; pub const POLICY_ACTION_LEN:usize=14;\n"
        + rust
    )
    with tempfile.TemporaryDirectory(prefix="seedcore-microduck-reference-") as tmp:
        temp = Path(tmp)
        (temp / "obs.rs").write_bytes(source)
        (temp / "main.rs").write_text(rust)
        subprocess.run(
            [
                "rustup",
                "run",
                "1.89.0",
                "rustc",
                "--edition=2021",
                "-A",
                "dead_code",
                str(temp / "main.rs"),
                "-o",
                str(temp / "reference"),
            ],
            check=True,
        )
        vectors = subprocess.check_output(
            [str(temp / "reference")], text=True
        ).splitlines()
    reference = ReferenceEvaluator(onnx.load_model_from_string(policy_bytes))
    for case, vector in zip(cases, vectors, strict=True):
        obs = json.loads(vector)
        case["observation"] = obs
        actions = reference.run(
            ["actions"], {"obs": np.asarray([obs], dtype=np.float32)}
        )[0]
        if actions.shape != (1, 14) or not np.isfinite(actions).all():
            raise ValueError("invalid reference policy output")
        case["actions"] = actions[0].tolist()
    result = {
        "schema_version": "seedcore.microduck.golden.v1",
        "runtime_revision": revision,
        "observation_source_sha256": hashlib.sha256(source).hexdigest(),
        "policy_sha256": profile["policy"]["sha256"],
        "reference": "pinned upstream Rust Observation::build + ONNX ReferenceEvaluator",
        "training_checkpoint_parity": "not_available",
        "cases": cases,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(f"Wrote {len(cases)} independently generated offline reference cases")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-checkout", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    generate(args.runtime_checkout, args.policy, args.output)
