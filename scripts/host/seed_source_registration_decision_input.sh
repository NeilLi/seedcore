#!/usr/bin/env bash

set -euo pipefail

BASE_URL="${SEEDCORE_API:-http://127.0.0.1:8002}"
API_V1_BASE="${BASE_URL}/api/v1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE_DIR="$(cd "${SCRIPT_DIR}/../../examples/source_registration_tracking_events" && pwd)"
SCENARIO="${1:-happy}"
POLL_ATTEMPTS="${POLL_ATTEMPTS:-20}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-1}"

if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required but not installed" >&2
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "jq is required but not installed" >&2
    exit 1
fi

case "${SCENARIO}" in
    happy)
        CREATE_FILE="${FIXTURE_DIR}/happy_path.create_registration.json"
        EVENTS_FILE="${FIXTURE_DIR}/happy_path.tracking_events.json"
        ;;
    deny)
        CREATE_FILE="${FIXTURE_DIR}/deny_path.create_registration.json"
        EVENTS_FILE="${FIXTURE_DIR}/deny_path.tracking_events.json"
        ;;
    *)
        echo "usage: $0 [happy|deny]" >&2
        exit 1
        ;;
esac

echo "Scenario: ${SCENARIO}"
echo "API base: ${API_V1_BASE}"
echo "Create payload: ${CREATE_FILE}"
echo "Tracking events: ${EVENTS_FILE}"
echo

create_response="$(
    curl -sS \
        -X POST "${API_V1_BASE}/source-registrations" \
        -H "Content-Type: application/json" \
        --data @"${CREATE_FILE}"
)"
registration_id="$(echo "${create_response}" | jq -r '.id')"

if [[ -z "${registration_id}" || "${registration_id}" == "null" ]]; then
    echo "failed to create source registration" >&2
    echo "${create_response}" | jq .
    exit 1
fi

echo "Created registration:"
echo "${create_response}" | jq '{id, lot_id, producer_id, status}'
echo

event_count=0
while IFS= read -r event; do
    event_count=$((event_count + 1))
    event_request="$(echo "${event}" | jq --arg registration_id "${registration_id}" '. + {registration_id: $registration_id}')"
    event_response="$(
        curl -sS \
            -X POST "${API_V1_BASE}/tracking-events" \
            -H "Content-Type: application/json" \
            -d "${event_request}"
    )"
    echo "Projected tracking event ${event_count}:"
    echo "${event_response}" | jq '{id, event_type, source_kind, projected_at}'
done < <(jq -c '.[]' "${EVENTS_FILE}")

echo
echo "Projected registration state before submit:"
curl -sS "${API_V1_BASE}/source-registrations/${registration_id}" | jq '{
    id,
    status,
    artifact_count: (.artifacts | length),
    measurement_count: (.measurements | length),
    artifacts: [.artifacts[].artifact_type],
    measurements: [.measurements[].measurement_type]
}'
echo

submit_response="$(
    curl -sS \
        -X POST "${API_V1_BASE}/source-registrations/${registration_id}/submit"
)"
task_id="$(echo "${submit_response}" | jq -r '.task_id')"

echo "Submit response:"
echo "${submit_response}" | jq .
echo

echo "Polling for verdict (attempts=${POLL_ATTEMPTS}, interval=${POLL_INTERVAL_SECONDS}s)..."
attempt=1
while [[ ${attempt} -le ${POLL_ATTEMPTS} ]]; do
    verdict_body_file="$(mktemp)"
    verdict_status="$(
        curl -sS \
            -o "${verdict_body_file}" \
            -w "%{http_code}" \
            "${API_V1_BASE}/source-registrations/${registration_id}/verdict"
    )"
    if [[ "${verdict_status}" == "200" ]]; then
        echo "Verdict available on attempt ${attempt}:"
        jq . "${verdict_body_file}"
        rm -f "${verdict_body_file}"
        echo
        echo "Summary:"
        echo "  registration_id=${registration_id}"
        echo "  task_id=${task_id}"
        exit 0
    fi
    rm -f "${verdict_body_file}"
    sleep "${POLL_INTERVAL_SECONDS}"
    attempt=$((attempt + 1))
done

echo "No verdict available yet for registration ${registration_id} after ${POLL_ATTEMPTS} attempts."
echo "Task id: ${task_id}"
