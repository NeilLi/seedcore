#!/usr/bin/env bash
# Live check: ensure /pdp/hot-path/status and /pdp/hot-path/metrics are consistent.
#
# Requires a running SeedCore runtime API (default http://127.0.0.1:8002/api/v1).
# Optional: export SEEDCORE_HOT_PATH_DEPLOYMENT_ROLE if the server omits
# observability.deployment_role in JSON (otherwise the JSON value is used).
#
# Deployment wiring for this label: deploy/k8s (kubernetes), ray-head (ray),
# host-env/run-api (host), docker/Dockerfile + docker/env.example (docker).
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
from collections import defaultdict
status = json.loads(os.environ["STATUS_JSON"])
metrics = os.environ["METRICS_TEXT"]

obs = status.get("observability") or {}
role_raw = obs.get("deployment_role")
if role_raw is None or str(role_raw).strip() == "":
    role = str(os.getenv("SEEDCORE_HOT_PATH_DEPLOYMENT_ROLE", "unset"))
else:
    role = str(role_raw)

metric_line = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{([^}]*)\})?\s+([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)$')
metrics_by_name_and_role: dict[tuple[str, str | None], float] = {}
roles_by_metric: dict[str, set[str]] = defaultdict(set)
raw_lines_by_metric: dict[str, list[str]] = defaultdict(list)

for raw in metrics.splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    parsed = metric_line.match(line)
    if not parsed:
        continue
    name, labels, value = parsed.groups()
    labels_map: dict[str, str] = {}
    if labels:
        for part in labels.split(","):
            key, _, raw_value = part.partition("=")
            key = key.strip()
            if not key:
                continue
            label_value = raw_value.strip().strip('"')
            labels_map[key] = label_value
    deployment_role = labels_map.get("deployment_role")
    if deployment_role is not None:
        roles_by_metric[name].add(deployment_role)
    raw_lines_by_metric[name].append(line)
    metrics_by_name_and_role[(name, deployment_role)] = float(value)

def gauge_value(name: str) -> float:
    found = metrics_by_name_and_role.get((name, role))
    if found is not None:
        return found
    roles = sorted(roles_by_metric.get(name) or [])
    nearby = raw_lines_by_metric.get(name) or []
    nearby_text = "; ".join(nearby[:3]) if nearby else "none"
    raise AssertionError(
        f"missing metrics gauge {name} deployment_role={role}; "
        f"available_roles={roles}; sample_lines={nearby_text}"
    )

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

assert gauge_value("seedcore_hot_path_authz_graph_ready") == (
    1.0 if bool(status.get("authz_graph_ready")) else 0.0
)
assert gauge_value("seedcore_hot_path_latency_slo_met") == (
    1.0 if bool(status.get("latency_slo_met")) else 0.0
)
assert gauge_value("seedcore_hot_path_runtime_ready") == (1.0 if bool(status.get("runtime_ready")) else 0.0)
assert gauge_value("seedcore_hot_path_parity_ok_total") == float(status.get("parity_ok") or 0)
assert gauge_value("seedcore_hot_path_mismatched_total") == float(status.get("mismatched") or 0)

lat = status.get("latency_ms") if isinstance(status.get("latency_ms"), dict) else {}
p99 = lat.get("p99") if isinstance(lat, dict) else None
if p99 is not None:
    assert gauge_value("seedcore_hot_path_latency_p99_ms") == float(p99)

print("Hot-path observability OK (status <-> metrics consistent).")
PY
