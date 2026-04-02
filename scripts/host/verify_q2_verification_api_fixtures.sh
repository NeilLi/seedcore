#!/usr/bin/env bash
# Live verification API checks (fixtures only): queue, detail, replay, runbook, forensics, lookup.
# Requires verification-api on SEEDCORE_VERIFICATION_API_BASE (default http://127.0.0.1:7071).
set -euo pipefail
VERIFICATION_API_BASE="${SEEDCORE_VERIFICATION_API_BASE:-http://127.0.0.1:7071}"
PASS_COUNT=0
FAIL_COUNT=0

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[FAIL] missing required binary: $1" >&2
    exit 1
  fi
}

check() {
  local name="$1"
  shift
  if "$@"; then
    PASS_COUNT=$((PASS_COUNT + 1))
    echo "[PASS] ${name}"
  else
    FAIL_COUNT=$((FAIL_COUNT + 1))
    echo "[FAIL] ${name}" >&2
  fi
}

json_get() {
  local url="$1"
  curl -fsS "$url"
}

require_bin curl
require_bin jq

echo "== Q2 verification API fixture matrix =="
echo "Verification API: ${VERIFICATION_API_BASE}"

QUEUE="$(json_get "${VERIFICATION_API_BASE}/api/v1/verification/transfers/queue?source=fixture&root=rust/fixtures/transfers")"
check "queue returns items" jq -e '.items | length >= 1' <<<"${QUEUE}" >/dev/null

check "queue row includes trust_alerts" jq -e '.items[0].trust_alerts | type == "array"' <<<"${QUEUE}" >/dev/null

# Screen 2 (transfer review) should return contract-shaped projections.
REVIEW="$(json_get "${VERIFICATION_API_BASE}/api/v1/verification/transfers/review?source=fixture&dir=rust/fixtures/transfers/allow_case")"
check "transfer review includes projections" jq -e '.verification_projection.contract_version == "seedcore.verification_surface_projection.v1"' <<<"${REVIEW}" >/dev/null
check "transfer review includes audit + forensics" jq -e '.transfer_audit_trail.contract_version == "seedcore.verification_surface_projection.v1" and .asset_forensic_projection.contract_version == "seedcore.verification_surface_projection.v1"' <<<"${REVIEW}" >/dev/null

REPLAY="$(json_get "${VERIFICATION_API_BASE}/api/v1/verification/workflows/allow_case/replay?source=fixture&root=rust/fixtures/transfers")"
check "replay contract version" jq -e '.contract_version == "seedcore.verification_replay.v1"' <<<"${REPLAY}" >/dev/null

# Screen 4 detail bundle should include the failure panel and receipt chain.
DETAIL="$(json_get "${VERIFICATION_API_BASE}/api/v1/verification/workflows/allow_case/verification-detail?source=fixture&root=rust/fixtures/transfers")"
check "verification detail contract version" jq -e '.contract_version == "seedcore.verification_detail.v1"' <<<"${DETAIL}" >/dev/null
check "verification detail includes runbook links" jq -e '.failure_panel.runbook_links | length >= 1' <<<"${DETAIL}" >/dev/null

RB="$(json_get "${VERIFICATION_API_BASE}/api/v1/verification/runbook")"
check "runbook index" jq -e '.runbooks | length >= 1' <<<"${RB}" >/dev/null

LOOKUP="$(json_get "${VERIFICATION_API_BASE}/api/v1/verification/runbook/lookup?reason_code=policy_denied")"
check "runbook lookup contract" jq -e '.contract_version == "seedcore.verification_runbook_lookup.v1"' <<<"${LOOKUP}" >/dev/null
check "runbook lookup returns links" jq -e '.runbook_links | length >= 1' <<<"${LOOKUP}" >/dev/null

FORENSICS="$(json_get "${VERIFICATION_API_BASE}/api/v1/verification/assets/forensics?source=fixture&dir=rust/fixtures/transfers/allow_case")"
check "fixture forensics" jq -e '.asset_ref | type == "string"' <<<"${FORENSICS}" >/dev/null

echo "Checks passed: ${PASS_COUNT}  failed: ${FAIL_COUNT}"
if [[ ${FAIL_COUNT} -ne 0 ]]; then
  exit 1
fi
