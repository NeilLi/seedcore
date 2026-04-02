from __future__ import annotations

import importlib.util
import json
from pathlib import Path


_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "host" / "benchmark_rct_hot_path.py"
_SPEC = importlib.util.spec_from_file_location("benchmark_rct_hot_path", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_run_benchmark_writes_summary_artifact(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        _MODULE,
        "_prepare_case_payloads",
        lambda base_url: ("snapshot:test", [("allow_case", {"request_id": "template"})]),
    )
    status_payloads = iter(
        [
            {"total": 10, "mismatched": 1, "parity_ok": 9},
            {
                "mode": "shadow",
                "total": 12,
                "mismatched": 1,
                "parity_ok": 11,
                "graph_age_seconds": 2,
                "authz_graph_ready": True,
                "graph_freshness_ok": True,
                "enforce_ready": False,
                "active_snapshot_version": "snapshot:test",
            },
        ]
    )
    monkeypatch.setattr(_MODULE, "_get_json", lambda url: next(status_payloads))
    monkeypatch.setattr(
        _MODULE,
        "_post_json",
        lambda url, payload: {
            "latency_ms": 7,
            "decision": {
                "disposition": "allow",
                "reason_code": "restricted_custody_transfer_allowed",
            },
        },
    )

    summary = _MODULE.run_benchmark(
        base_url="http://127.0.0.1:8002/api/v1",
        total_requests=2,
        warmup_requests=1,
        concurrency=1,
        artifact_root=tmp_path,
        request_delay_ms=0.0,
        jitter_ms_max=0.0,
    )

    artifact_path = Path(summary["artifact_path"])
    assert artifact_path.exists()
    persisted = json.loads(artifact_path.read_text())
    assert persisted["total_requests"] == 2
    assert persisted["success_count"] == 2
    assert persisted["mismatch_count"] == 0
    assert persisted["parity_ok_delta"] == 2
    assert persisted["disposition_counts"]["allow"] == 2
    assert persisted["top_reason_codes"][0]["reason_code"] == "restricted_custody_transfer_allowed"
    assert persisted["request_delay_ms"] == 0.0
    assert persisted["jitter_ms_max"] == 0.0


def test_run_benchmark_accepts_delay_and_jitter_metadata(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        _MODULE,
        "_prepare_case_payloads",
        lambda base_url: ("snapshot:test", [("allow_case", {"request_id": "template"})]),
    )
    status_payloads = iter(
        [
            {"total": 0, "mismatched": 0, "parity_ok": 0},
            {
                "mode": "shadow",
                "total": 1,
                "mismatched": 0,
                "parity_ok": 1,
                "graph_age_seconds": 0,
                "authz_graph_ready": True,
                "graph_freshness_ok": True,
                "enforce_ready": False,
                "active_snapshot_version": "snapshot:test",
            },
        ]
    )
    monkeypatch.setattr(_MODULE, "_get_json", lambda url: next(status_payloads))
    monkeypatch.setattr(
        _MODULE,
        "_post_json",
        lambda url, payload: {
            "latency_ms": 1,
            "decision": {"disposition": "allow", "reason_code": "restricted_custody_transfer_allowed"},
        },
    )
    summary = _MODULE.run_benchmark(
        base_url="http://127.0.0.1:8002/api/v1",
        total_requests=1,
        warmup_requests=0,
        concurrency=1,
        artifact_root=tmp_path,
        request_delay_ms=2.0,
        jitter_ms_max=1.0,
    )
    assert summary["request_delay_ms"] == 2.0
    assert summary["jitter_ms_max"] == 1.0
