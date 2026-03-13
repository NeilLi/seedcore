# Source Registration Tracking Event Curl Collection

This collection uses the stable fixtures under `examples/source_registration_tracking_events/`.

## Happy path

```bash
export SEEDCORE_API="${SEEDCORE_API:-http://127.0.0.1:8002}"
export API_V1_BASE="${SEEDCORE_API}/api/v1"
export FIXTURE_DIR="examples/source_registration_tracking_events"

registration_json="$(
  curl -sS -X POST "${API_V1_BASE}/source-registrations" \
    -H "Content-Type: application/json" \
    --data @"${FIXTURE_DIR}/happy_path.create_registration.json"
)"
export REGISTRATION_ID="$(echo "${registration_json}" | jq -r '.id')"

jq -c '.[]' "${FIXTURE_DIR}/happy_path.tracking_events.json" | while read -r event; do
  curl -sS -X POST "${API_V1_BASE}/tracking-events" \
    -H "Content-Type: application/json" \
    -d "$(echo "${event}" | jq --arg registration_id "${REGISTRATION_ID}" '. + {registration_id: $registration_id}')" \
    | jq '{id, event_type, projected_at}'
done

curl -sS "${API_V1_BASE}/source-registrations/${REGISTRATION_ID}" | jq '{
  id,
  status,
  artifact_types: [.artifacts[].artifact_type],
  measurement_types: [.measurements[].measurement_type]
}'

curl -sS -X POST "${API_V1_BASE}/source-registrations/${REGISTRATION_ID}/submit" | jq .
curl -sS "${API_V1_BASE}/source-registrations/${REGISTRATION_ID}/verdict" | jq .
```

## Deny path

```bash
export SEEDCORE_API="${SEEDCORE_API:-http://127.0.0.1:8002}"
export API_V1_BASE="${SEEDCORE_API}/api/v1"
export FIXTURE_DIR="examples/source_registration_tracking_events"

registration_json="$(
  curl -sS -X POST "${API_V1_BASE}/source-registrations" \
    -H "Content-Type: application/json" \
    --data @"${FIXTURE_DIR}/deny_path.create_registration.json"
)"
export REGISTRATION_ID="$(echo "${registration_json}" | jq -r '.id')"

jq -c '.[]' "${FIXTURE_DIR}/deny_path.tracking_events.json" | while read -r event; do
  curl -sS -X POST "${API_V1_BASE}/tracking-events" \
    -H "Content-Type: application/json" \
    -d "$(echo "${event}" | jq --arg registration_id "${REGISTRATION_ID}" '. + {registration_id: $registration_id}')" \
    | jq '{id, event_type, projected_at}'
done

curl -sS -X POST "${API_V1_BASE}/source-registrations/${REGISTRATION_ID}/submit" | jq .
curl -sS "${API_V1_BASE}/source-registrations/${REGISTRATION_ID}/verdict" | jq .
```

## One-command seed

```bash
./scripts/host/seed_source_registration_decision_input.sh happy
./scripts/host/seed_source_registration_decision_input.sh deny
```
