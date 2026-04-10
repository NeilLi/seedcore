#!/usr/bin/env bash
# Host-level alert-rule verification against realistic /pdp/hot-path/status payloads.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

python -m pytest -q \
  tests/test_pdp_hot_path_router.py::test_pdp_hot_path_metrics_exposes_prometheus_text \
  tests/test_pdp_hot_path_router.py::test_pdp_hot_path_status_reports_runtime_readiness_and_mode \
  tests/test_pdp_hot_path_router.py::test_pdp_hot_path_quarantines_when_compiled_graph_is_stale

echo "Hot-path alert-rule verification checks passed."
