"""CW-S03 inventory: immutable local pins, missing-cache reporting and CPU replay scope."""
import json
from pathlib import Path
import shutil

import pytest

from seedcore.robotics import policy_preflight_inventory as inventory


def test_absent_policy_cache_is_missing_evidence_not_a_synthetic_policy(tmp_path):
    report = inventory.inspect_policy_inventory(policy_path=tmp_path / "not-downloaded.onnx")
    assert report["policy"]["status"] == report["artifactReplay"]["status"] == "missing"
    assert report["policy"]["inspection"] is None
    assert report["artifactReplay"]["caseCount"] == 0
    assert report["unresolved"]["trainingCheckpointParity"] == "not_available"
    assert report["unresolved"]["policyLicenseSpdx"] is None
    assert report["physicalAcceptance"] is False and report["executionAuthority"] == "none"
    assert report["body"]["topology"] == "floating_base"
    assert len(report["body"]["jointOrder"]) == 14


def test_changed_policy_bytes_are_rejected_before_any_inference(tmp_path, monkeypatch):
    path = tmp_path / "wrong.onnx"
    path.write_bytes(b"not the pinned ONNX policy")
    monkeypatch.setattr(inventory, "PinnedPolicy", lambda *a, **k: pytest.fail("invalid bytes must not reach ONNX Runtime"))
    report = inventory.inspect_policy_inventory(policy_path=path)
    assert report["policy"]["status"] == report["artifactReplay"]["status"] == "failed"
    assert report["artifactReplay"]["caseCount"] == 0
    assert "SHA-256 mismatch" in report["artifactReplay"]["detail"]


@pytest.mark.parametrize("name", [inventory.PROFILE, inventory.GOLDEN, "src/seedcore/robotics/microduck_contract.py"])
def test_changed_profile_goldens_or_encoder_requires_reviewed_repin(tmp_path, name):
    for source in [inventory.PIN_FILE, inventory.PROFILE, inventory.GOLDEN, "src/seedcore/robotics/microduck_contract.py"]:
        target = tmp_path / source
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(inventory.ROOT / source, target)
    changed = tmp_path / name
    changed.write_bytes(changed.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="inventory source pin mismatch"):
        inventory.inspect_policy_inventory(root=tmp_path)


def test_bounded_reader_rejects_oversized_artifacts(tmp_path):
    path = tmp_path / "large"
    path.write_bytes(b"x" * 33)
    with pytest.raises(ValueError, match="byte bound"):
        inventory.read_bounded(path, 32)


def test_cached_policy_replay_and_inspection_do_not_claim_training_or_browser_parity(monkeypatch):
    pytest.importorskip("onnxruntime")
    profile = json.loads((inventory.ROOT / inventory.PROFILE).read_bytes())
    if not (inventory.ROOT / profile["policy"]["local_cache"]).is_file():
        pytest.skip("No pinned policy cache; strict verifier requires --require-artifact-replay")
    # Native MuJoCo stepping must not be a dependency or a side effect of preflight.
    try:
        import mujoco
        monkeypatch.setattr(mujoco, "mj_step", lambda *a: pytest.fail("preflight must never step a model"))
    except ImportError:
        pass
    first = inventory.inspect_policy_inventory()
    second = inventory.inspect_policy_inventory()
    assert first == second
    assert first["artifactReplay"]["status"] == "verified"
    assert first["artifactReplay"]["caseCount"] == 16
    assert first["policy"]["inspection"]["inputs"][0]["shape"] == [1, 61]
    assert first["policy"]["inspection"]["outputs"][0]["shape"] == [1, 14]
    assert first["policy"]["inspection"]["metadata"]["run_path"] == "None"
    assert first["unresolved"]["trainingCheckpointParity"] == "not_available"
    assert first["unresolved"]["browserInferenceTiming"] == "not_run"
