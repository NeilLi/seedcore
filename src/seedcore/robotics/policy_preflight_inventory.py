"""CW-S03 local artifact inventory and CPU replay. No download, simulation step or motor IO."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from .microduck_contract import DeploymentProfile, PinnedPolicy, build_observation
from .model_package import verify_model_package

ROOT = Path(__file__).resolve().parents[3]
PIN_FILE = "packages/robotics-profiles/reviews/cw-s03-preflight-inputs-v1.json"
PROFILE = "packages/robotics-profiles/microduck-sim-v1.json"
GOLDEN = "tests/fixtures/microduck/golden-v1.json"
MAX_POLICY_BYTES = 8 * 1024 * 1024


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_bounded(path: Path, maximum: int) -> bytes:
    with path.open("rb") as source:
        raw = source.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("artifact exceeds byte bound")
    return raw


def inspect_policy_inventory(*, root: Path = ROOT, policy_path: Path | None = None) -> dict:
    root = root.resolve()
    pins = json.loads(read_bounded(root / PIN_FILE, 32768))
    if (pins["schemaVersion"] != "seedcore.cw-s03.inventory-pins.v1"
            or pins["scope"] != "offline_policy_compatibility_preflight"
            or pins["physicalAcceptance"] is not False or pins["executionAuthority"] != "none"):
        raise ValueError("invalid inventory pin scope")
    required = {PROFILE, GOLDEN, "src/seedcore/robotics/microduck_contract.py"}
    if set(pins["files"]) != required:
        raise ValueError("inventory must pin profile, goldens and observation implementation")
    checks = []
    raw_files = {}
    for name, expected in sorted(pins["files"].items()):
        raw = read_bounded(root / name, 1024 * 1024)
        raw_files[name] = raw
        actual = sha256(raw)
        checks.append({"path": name, "sha256": actual, "bytes": len(raw)})
        if actual != expected:
            raise ValueError(f"inventory source pin mismatch: {name}")
    deployment = DeploymentProfile.model_validate_json(raw_files[PROFILE])
    profile = deployment.model_dump(mode="json")
    package = verify_model_package(root / deployment.body_manifest,
                                   expected_manifest_sha256=deployment.body_manifest_sha256)
    golden = json.loads(raw_files[GOLDEN])
    if (golden["policy_sha256"] != deployment.policy["sha256"]
            or golden["runtime_revision"] != deployment.runtime["revision"]
            or golden["observation_source_sha256"] != deployment.runtime["files"]["duck-control/src/obs.rs"]
            or golden["training_checkpoint_parity"] != "not_available"
            or len(golden["cases"]) != 16):
        raise ValueError("goldens do not bind the pinned source/policy reference")

    # Git object reads inspect immutable source bytes; never import upstream code.
    source_checks = []
    for kind, checkout in (("runtime", root.parent / "microduck"), ("rl", root.parent / "microduck_rl")):
        for name, expected in sorted(profile[kind]["files"].items()):
            result = subprocess.run(["git", "-C", str(checkout), "show", f'{profile[kind]["revision"]}:{name}'],
                                    capture_output=True, timeout=10)
            actual = sha256(result.stdout) if result.returncode == 0 else None
            source_checks.append({"kind": kind, "revision": profile[kind]["revision"], "path": name,
                                  "expectedSha256": expected, "actualSha256": actual,
                                  "status": "verified" if actual == expected else "missing" if actual is None else "failed"})

    policy_file = policy_path if policy_path is not None else root / deployment.policy["local_cache"]
    policy_info = {"expectedSha256": deployment.policy["sha256"], "expectedBytes": deployment.policy["size_bytes"],
                   "actualSha256": None, "actualBytes": None, "inspection": None, "status": "missing",
                   "licenseSpdx": None, "graphInspection": {"status": "not_run"}}
    replay = {"status": "missing", "policySha256": None, "modelDigest": None, "adapterDigest": None,
              "sourceSha256": sha256(raw_files[GOLDEN]), "caseCount": 0,
              "observationAtol": deployment.tolerances["observation_atol"],
              "actionAtol": deployment.tolerances["action_atol"], "rtol": 0.0,
              "maxObservationAbsoluteError": None, "maxActionAbsoluteError": None, "detail": "Pinned policy cache unavailable; no download attempted."}
    if policy_file.is_file():
        try:
            raw = read_bounded(policy_file, MAX_POLICY_BYTES)
            actual = sha256(raw)
            policy_info.update(actualSha256=actual, actualBytes=len(raw))
            if actual != deployment.policy["sha256"] or len(raw) != deployment.policy["size_bytes"]:
                raise ValueError("policy byte count/SHA-256 mismatch")
            import numpy as np
            import onnxruntime as ort
            if ort.__version__ != "1.31.0":
                raise ValueError("CPU policy inspection requires pinned onnxruntime==1.31.0")
            policy = PinnedPolicy(policy_file, expected_sha256=deployment.policy["sha256"])
            try:
                import onnx
                if onnx.__version__ != "1.17.0":
                    raise ValueError("Graph inventory requires pinned onnx==1.17.0")
                graph = onnx.load_model_from_string(raw)
                policy_info["graphInspection"] = {
                    "status": "inspected_not_browser_qualified", "onnxVersion": onnx.__version__,
                    "opsets": [{"domain": o.domain, "version": o.version} for o in graph.opset_import],
                    "nodeCount": len(graph.graph.node),
                    "operators": sorted({f"{n.domain or 'ai.onnx'}::{n.op_type}" for n in graph.graph.node}),
                    "browserCoverage": "not_run",
                }
            except ImportError:
                policy_info["graphInspection"] = {"status": "not_run", "detail": "Optional pinned ONNX parser unavailable"}
            # PinnedPolicy validates these ports and joint/home metadata against source.
            session = policy._session
            policy_info.update(status="verified", inspection={
                "inputs": [{"name": p.name, "shape": p.shape, "type": p.type} for p in session.get_inputs()],
                "outputs": [{"name": p.name, "shape": p.shape, "type": p.type} for p in session.get_outputs()],
                "metadata": policy.metadata, "onnxruntimeVersion": ort.__version__,
                "provider": "CPUExecutionProvider", "normalizationSource": deployment.policy["normalization"],
            })
            max_obs = max_action = 0.0
            for case in golden["cases"]:
                observation = build_observation(**case["input"])
                action = policy.infer(observation)
                np.testing.assert_allclose(observation, case["observation"], rtol=0, atol=replay["observationAtol"])
                np.testing.assert_allclose(action, case["actions"], rtol=0, atol=replay["actionAtol"])
                max_obs = max(max_obs, float(np.max(np.abs(observation - np.asarray(case["observation"])))))
                max_action = max(max_action, float(np.max(np.abs(action - np.asarray(case["actions"])))))
                replay["caseCount"] += 1
            replay.update(status="verified", policySha256=policy.sha256,
                          maxObservationAbsoluteError=max_obs, maxActionAbsoluteError=max_action,
                          detail="16-case CPU artifact replay against retained Rust/ONNX ReferenceEvaluator goldens; training-checkpoint comparison unavailable.")
        except ImportError:
            policy_info["status"] = "not_run"
            replay.update(status="not_run", detail="Optional pinned robotics-policy dependencies are unavailable; no install attempted.")
        except (ValueError, AssertionError, RuntimeError, OSError) as error:
            if policy_info["status"] != "verified":
                policy_info["status"] = "failed"
            replay.update(status="failed", detail=str(error)[:500])

    return {"schemaVersion": "seedcore.cw-s03.local-inventory.v1", "scope": "offline_policy_compatibility_preflight",
            "physicalAcceptance": False, "executionAuthority": "none", "status": "inspected",
            "inventoryPinsSha256": sha256((root / PIN_FILE).read_bytes()), "files": checks,
            "sourceChecks": source_checks, "deployment": profile, "policy": policy_info, "artifactReplay": replay,
            "body": {"modelDigest": package.manifest_sha256, "packageDigest": package.package_sha256,
                     "verifiedFileCount": len(package.files), "engineVersion": package.manifest.engine_version,
                     "topology": "floating_base" if any(j.type == "free" for j in package.manifest.parity.joints) else "fixed_base_serial",
                     "jointOrder": [a.joint for a in package.manifest.parity.actuators],
                     "actuatorProfile": "source_mjcf_position"},
            "unresolved": {"trainingCheckpointParity": deployment.policy["training_checkpoint_parity"],
                           "sourceRunPath": deployment.policy["source_run_path"], "policyLicenseSpdx": None,
                           "trainingActuatorEquivalence": None, "runtimePolicyPair": "not_verified",
                           "browserOperatorCoverage": "not_run", "browserInferenceTiming": "not_run"}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "artifacts"):
        parser.error("output must be inside repository artifacts/")
    report = inspect_policy_inventory()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(f'CW-S03 inventory: policy={report["policy"]["status"]}; artifact replay={report["artifactReplay"]["status"]}; training checkpoint={report["unresolved"]["trainingCheckpointParity"]}')


if __name__ == "__main__":
    main()
