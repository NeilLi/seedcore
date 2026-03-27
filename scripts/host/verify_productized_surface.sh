#!/usr/bin/env bash

set -euo pipefail

VERIFICATION_API_BASE="${SEEDCORE_VERIFICATION_API_BASE:-http://127.0.0.1:7071}"
RUNTIME_API_BASE="${SEEDCORE_RUNTIME_API_BASE:-http://127.0.0.1:8002/api/v1}"
DB_NAME="${SEEDCORE_DB_NAME:-seedcore}"

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

json_post() {
  local url="$1"
  local payload="$2"
  curl -fsS -X POST "$url" -H "content-type: application/json" -d "$payload"
}

status_code() {
  local url="$1"
  curl -sS -o /dev/null -w "%{http_code}" "$url"
}

status_code_post() {
  local url="$1"
  local payload="$2"
  curl -sS -o /dev/null -w "%{http_code}" -X POST "$url" -H "content-type: application/json" -d "$payload"
}

find_runtime_audit_id() {
  if [[ -n "${SEEDCORE_AUDIT_ID:-}" ]]; then
    echo "$SEEDCORE_AUDIT_ID"
    return 0
  fi
  if ! command -v psql >/dev/null 2>&1; then
    return 1
  fi
  psql -d "$DB_NAME" -Atc \
    "select id::text from public.governed_execution_audit order by recorded_at desc limit 1;" 2>/dev/null | head -n 1
}

require_bin curl
require_bin jq

echo "== Productized Verification Surface Protocol =="
echo "Verification API: ${VERIFICATION_API_BASE}"
echo "Runtime API:      ${RUNTIME_API_BASE}"

AUDIT_ID="$(find_runtime_audit_id || true)"
if [[ -z "${AUDIT_ID}" ]]; then
  echo "[WARN] No runtime audit_id discovered. Runtime checks will be skipped."
fi

# Phase 1.1 - Receipt integrity checks (runtime)
if [[ -n "${AUDIT_ID}" ]]; then
  replay_payload="$(json_get "${RUNTIME_API_BASE}/replay?audit_id=${AUDIT_ID}&projection=internal")"

  check "phase1.1 receipt includes governed decision hash" \
    jq -e '.view.audit_record.policy_decision.governed_receipt.decision_hash | type == "string"' <<<"${replay_payload}" >/dev/null

  check "phase1.1 receipt includes policy snapshot id" \
    jq -e '.view.audit_record.policy_snapshot | type == "string"' <<<"${replay_payload}" >/dev/null

  check "phase1.1 signer provenance available in forensic view" \
    jq -e '.signature_provenance | length > 0' \
      <<<"$(json_get "${VERIFICATION_API_BASE}/api/v1/assets/forensics?source=runtime&audit_id=${AUDIT_ID}")" >/dev/null

  verify_payload="$(json_post "${RUNTIME_API_BASE}/verify" "{\"audit_id\":\"${AUDIT_ID}\"}")"
  check "phase1.1 runtime verify endpoint executes for receipt id" \
    jq -e '.verified == true or .verified == false' <<<"${verify_payload}" >/dev/null

  # Phase 1.2 - Replay accuracy and business-state rendering
  status_payload="$(json_get "${VERIFICATION_API_BASE}/api/v1/transfers/status?source=runtime&audit_id=${AUDIT_ID}")"
  check "phase1.2 replay status has business-readable state vocabulary" \
    jq -e '.business_state | IN("verified","quarantined","rejected","review_required","verification_failed")' <<<"${status_payload}" >/dev/null
  check "phase1.2 replay status renders non-empty timeline" \
    jq -e '.timeline | length > 0' <<<"${status_payload}" >/dev/null
fi

# Phase 2.1 - Lookup contract enforcement (BFF gate behavior)
check "phase2.1 transfer status rejects subject-only runtime lookup" \
  test "$(status_code "${VERIFICATION_API_BASE}/api/v1/transfers/status?source=runtime&subject_id=asset:demo")" = "422"

# Phase 2.2 - Policy snapshot fidelity
if [[ -n "${AUDIT_ID}" ]]; then
  forensic_payload="$(json_get "${VERIFICATION_API_BASE}/api/v1/assets/forensics?source=runtime&audit_id=${AUDIT_ID}")"
  replay_payload="$(json_get "${RUNTIME_API_BASE}/replay?audit_id=${AUDIT_ID}&projection=internal")"
  forensic_snapshot="$(jq -r '.policy_snapshot_ref' <<<"${forensic_payload}")"
  replay_snapshot="$(jq -r '.view.audit_record.policy_snapshot' <<<"${replay_payload}")"
  check "phase2.2 forensic policy snapshot matches runtime audit snapshot" \
    test "${forensic_snapshot}" = "${replay_snapshot}"
fi

# Phase 3.1 - Prerequisite chain verification (fixture deny)
deny_fixture="rust/fixtures/transfers/deny_missing_approval"
deny_status_payload="$(json_get "${VERIFICATION_API_BASE}/api/v1/transfers/status?source=fixture&dir=${deny_fixture}")"
check "phase3.1 missing prerequisite keeps transfer blocked" \
  jq -e '.transfer_readiness == "blocked"' <<<"${deny_status_payload}" >/dev/null
check "phase3.1 blocker includes missing prerequisite code" \
  jq -e '.blocker_codes | index("missing_dual_approval") != null' <<<"${deny_status_payload}" >/dev/null

# Phase 3.2 - Narrow surface visibility split (partner-proof vs operator-forensics)
proof_payload="$(json_get "${VERIFICATION_API_BASE}/api/v1/assets/proof?source=fixture&dir=rust/fixtures/transfers/allow_case")"
forensic_payload_fixture="$(json_get "${VERIFICATION_API_BASE}/api/v1/assets/forensics?source=fixture&dir=rust/fixtures/transfers/allow_case")"

check "phase3.2 public proof stays narrow (no telemetry refs field)" \
  jq -e 'has("telemetry_refs") | not' <<<"${proof_payload}" >/dev/null
check "phase3.2 operator forensic view carries telemetry refs" \
  jq -e '.telemetry_refs | length >= 1' <<<"${forensic_payload_fixture}" >/dev/null
check "phase3.2 operator forensic view carries custody transition context" \
  jq -e '.custody_transition.from_zone | type == "string"' <<<"${forensic_payload_fixture}" >/dev/null

echo
echo "Checks passed: ${PASS_COUNT}"
echo "Checks failed: ${FAIL_COUNT}"

if [[ ${FAIL_COUNT} -ne 0 ]]; then
  echo "Productized verification surface protocol failed." >&2
  exit 1
fi

echo "Productized verification surface protocol passed."
