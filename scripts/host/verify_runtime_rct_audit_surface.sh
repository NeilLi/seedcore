#!/usr/bin/env bash
# Generate a local runtime RCT audit row and prove replay + verification API runtime reads.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

API_BASE="${SEEDCORE_API:-http://127.0.0.1:8002}"
RUNTIME_API_BASE="${SEEDCORE_RUNTIME_API_BASE:-${API_BASE}/api/v1}"
VERIFICATION_API_BASE="${SEEDCORE_VERIFICATION_API_BASE:-http://127.0.0.1:7071}"
COUNT="${SEEDCORE_RUNTIME_RCT_AUDIT_COUNT:-1}"
TMP_JSON="$(mktemp -t seedcore-runtime-rct-audit.XXXXXX.json)"
trap 'rm -f "${TMP_JSON}"' EXIT

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[FAIL] missing required binary: $1" >&2
    exit 1
  fi
}

json_get() {
  local url="$1"
  curl -fsS "$url"
}

check_jq() {
  local name="$1"
  local expr="$2"
  local payload="$3"
  if jq -e "$expr" <<<"${payload}" >/dev/null; then
    echo "[PASS] ${name}"
  else
    echo "[FAIL] ${name}" >&2
    return 1
  fi
}

require_bin curl
require_bin jq

echo "== Generate local runtime RCT audit row =="
python scripts/host/generate_runtime_rct_audit.py \
  --api-base "${API_BASE}" \
  --count "${COUNT}" >"${TMP_JSON}"
cat "${TMP_JSON}"

AUDIT_ID="$(jq -r '.items[0].audit_id // .audit_id // empty' "${TMP_JSON}")"
if [[ -z "${AUDIT_ID}" || "${AUDIT_ID}" == "null" ]]; then
  echo "[FAIL] generator did not return audit_id" >&2
  exit 1
fi

echo "== Runtime replay checks for ${AUDIT_ID} =="
REPLAY="$(json_get "${RUNTIME_API_BASE}/replay?audit_id=${AUDIT_ID}&projection=internal")"
check_jq "runtime replay resolves generated audit id" '.view.audit_record.audit_record_id? // .view.audit_record.id | type == "string"' "${REPLAY}"
check_jq "runtime replay includes evidence bundle" '.view.evidence_bundle.evidence_bundle_id | type == "string"' "${REPLAY}"

echo "== Verification API runtime read checks =="
QUEUE="$(json_get "${VERIFICATION_API_BASE}/api/v1/verification/transfers/queue?source=runtime&audit_id=${AUDIT_ID}")"
check_jq "verification runtime queue returns one item" '.items | length == 1' "${QUEUE}"

DETAIL="$(json_get "${VERIFICATION_API_BASE}/api/v1/verification/workflows/${AUDIT_ID}/verification-detail?source=runtime")"
check_jq "verification runtime detail contract" '.contract_version == "seedcore.verification_detail.v1"' "${DETAIL}"

VREPLAY="$(json_get "${VERIFICATION_API_BASE}/api/v1/verification/workflows/${AUDIT_ID}/replay?source=runtime")"
check_jq "verification runtime replay contract" '.contract_version == "seedcore.verification_replay.v1"' "${VREPLAY}"

RUNBOOK="$(json_get "${VERIFICATION_API_BASE}/api/v1/verification/runbook/lookup?reason_code=policy_denied")"
check_jq "verification runbook lookup contract" '.contract_version == "seedcore.verification_runbook_lookup.v1"' "${RUNBOOK}"

echo "== Productized verification surface protocol =="
SEEDCORE_AUDIT_ID="${AUDIT_ID}" \
SEEDCORE_RUNTIME_API_BASE="${RUNTIME_API_BASE}" \
SEEDCORE_VERIFICATION_API_BASE="${VERIFICATION_API_BASE}" \
bash scripts/host/verify_productized_surface.sh

echo "Runtime RCT audit surface passed for audit_id=${AUDIT_ID}"
