#!/usr/bin/env bash
# Live check: ensure /pdp/hot-path/status and /pdp/hot-path/metrics are consistent.
#
# Requires a running SeedCore runtime API (default http://127.0.0.1:8002/api/v1).
# Optional: SEEDCORE_HOT_PATH_DEPLOYMENT_ROLE should match what the server is wired with.
set -euo pipefail

RUNTIME_API_BASE="${SEEDCORE_RUNTIME_API_BASE:-http://127.0.0.1:8002/api/v1}"

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[FAIL] missing required binary: $1" >&2
    exit 1
  fi
}

require_bin curl

STATUS_JSON="$(curl -fsS "${RUNTIME_API_BASE}/pdp/hot-path/status")"
METRICS_TEXT="$(curl -fsS "${RUNTIME_API_BASE}/pdp/hot-path/metrics")"

STATUS_JSON="${STATUS_JSON}" METRICS_TEXT="${METRICS_TEXT}" python - <<'PY'
import json
import os
import re
status = json.loads(os.environ["STATUS_JSON"])
metrics = os.environ["METRICS_TEXT"]

obs = status.get("observability") or {}
role = obs.get("deployment_role") or os.getenv("SEEDCORE_HOT_PATH_DEPLOYMENT_ROLE", "unset")
role = str(role)

def gauge_value(name: str) -> float:
    pat = rf'^{re.escape(name)}{{deployment_role="{re.escape(role)}"}}\\s+([0-9.]+)\\s*$'
    m = re.search(pat, metrics, flags=re.MULTILINE)
    if not m:
        raise AssertionError(f"missing metrics gauge {name} deployment_role={role}")
    return float(m.group(1))

alert_level = str(obs.get("alert_level") or "ok").strip().lower()
expected_alert = {"critical": 2, "warning": 1, "ok": 0}.get(alert_level, 0)
assert gauge_value("seedcore_hot_path_alert_level") == expected_alert

expected_rb = 1.0 if bool(status.get("rollback_triggered")) else 0.0
assert gauge_value("seedcore_hot_path_rollback_triggered") == expected_rb

expected_graph_fresh = 1.0 if bool(status.get("graph_freshness_ok")) else 0.0
assert gauge_value("seedcore_hot_path_graph_freshness_ok") == expected_graph_fresh

expected_total = float(status.get("total") or 0)
assert gauge_value("seedcore_hot_path_total_runs") == expected_total

expected_recent_mm = float(status.get("recent_mismatch_count") or 0)
assert gauge_value("seedcore_hot_path_recent_mismatch_count") == expected_recent_mm

ga = status.get("graph_age_seconds")
if ga is not None:
    actual = gauge_value("seedcore_hot_path_graph_age_seconds")
    assert abs(actual - float(ga)) < 1e-6

print("Hot-path observability OK (status <-> metrics consistent).")
PY

