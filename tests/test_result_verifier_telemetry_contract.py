from __future__ import annotations

from pathlib import Path

import pytest

from seedcore.coordinator.metrics.tracker import MetricsTracker


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_COUNTERS = {
    "result_verifier_jobs_enqueued_total",
    "result_verifier_jobs_processed_total",
    "result_verifier_pass_total",
    "result_verifier_quarantine_total",
    "result_verifier_integrity_fail_total",
    "result_verifier_quarantine_mutations_total",
    "result_verifier_fail_closed_orphan_total",
    "result_verifier_non_rct_skipped_total",
    "result_verifier_stale_processing_requeued_total",
    "result_verifier_retry_total",
    "result_verifier_terminal_fail_total",
    "result_verifier_job_millis_total",
    "result_verifier_job_seconds_total",
}

REQUIRED_GAUGES = {
    "result_verifier_watermark_lag_seconds",
}


def test_result_verifier_telemetry_keys_are_always_present() -> None:
    tracker = MetricsTracker()
    snapshot = tracker.get_metrics()

    missing = (REQUIRED_COUNTERS | REQUIRED_GAUGES) - snapshot.keys()
    assert missing == set()

    for key in REQUIRED_COUNTERS | REQUIRED_GAUGES:
        assert isinstance(snapshot[key], (int, float)), key

    assert snapshot["result_verifier_job_millis_total"] == 0
    assert snapshot["result_verifier_job_seconds_total"] == 0.0
    assert snapshot["result_verifier_watermark_lag_seconds"] == 0.0


def test_result_verifier_trigger_metrics_convert_and_update() -> None:
    tracker = MetricsTracker()

    tracker.increment_counter("result_verifier_job_millis_total", 1250)
    tracker.set_gauge("result_verifier_watermark_lag_seconds", 7.5)

    snapshot = tracker.get_metrics()

    assert snapshot["result_verifier_job_millis_total"] == 1250
    assert snapshot["result_verifier_job_seconds_total"] == pytest.approx(1.25)
    assert snapshot["result_verifier_watermark_lag_seconds"] == pytest.approx(7.5)


def test_result_verifier_telemetry_is_referenced_by_alerting_assets() -> None:
    recording_rules = (ROOT / "config" / "prometheus-recording-rules.yaml").read_text()
    dashboard = (ROOT / "config" / "grafana-dashboard.json").read_text()

    assert "result_verifier_job_seconds_total" in recording_rules
    assert "result_verifier_job_millis_total / 1000" in recording_rules
    assert "coordinator:result_verifier_cpu_pressure_ratio" in recording_rules

    assert "Result Verifier CPU Pressure Ratio" in dashboard
    assert "coordinator:result_verifier_cpu_pressure_ratio" in dashboard
    assert "Result Verifier Watermark Lag (s)" in dashboard
    assert "result_verifier_watermark_lag_seconds" in dashboard
