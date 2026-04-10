from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "host" / "capture_hot_path_deployment_baseline.py"
SPEC = importlib.util.spec_from_file_location("capture_hot_path_deployment_baseline", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_capture_baseline_writes_status_metrics_and_latest_artifacts(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    shadow_dir = repo_root / ".local-runtime" / "hot_path_shadow"
    bench_dir = repo_root / ".local-runtime" / "hot_path_benchmarks"
    shadow_dir.mkdir(parents=True)
    bench_dir.mkdir(parents=True)

    (shadow_dir / "a.json").write_text(json.dumps({"shadow": 1}), encoding="utf-8")
    (bench_dir / "b.json").write_text(json.dumps({"bench": 2}), encoding="utf-8")

    monkeypatch.setattr(MODULE, "_json_get", lambda url: {"runtime_ready": False, "observability": {"alert_level": "critical"}})
    monkeypatch.setattr(MODULE, "_text_get", lambda url: "# HELP seedcore_hot_path_runtime_ready ...")

    output_path = MODULE.capture_baseline(
        runtime_api_base="http://127.0.0.1:8002/api/v1",
        repo_root=repo_root,
        output_root=repo_root / ".local-runtime" / "hot_path_baselines",
    )

    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"]["runtime_ready"] is False
    assert payload["metrics_text"].startswith("# HELP")
    assert payload["latest_shadow_artifact"]["payload"] == {"shadow": 1}
    assert payload["latest_benchmark_artifact"]["payload"] == {"bench": 2}
