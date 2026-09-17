# Delegated Intent Over Kafka

This document describes how an external AI assistant, such as an OpenAI agent,
can emit a delegated action request into SeedCore through Kafka without making
Kafka the policy source of truth.

## Principle

Kafka carries **delegated intent transport**.
SeedCore still makes the authoritative decision through the existing API path:

1. external assistant publishes delegated intent to `seedcore.intent.v1`
2. SeedCore Kafka ingress consumes the event
3. ingress calls `/api/v1/owner-context/preflight`
4. ingress calls `/api/v1/agent-actions/evaluate`
5. SeedCore emits downstream decision observability through `seedcore.policy_outcome.v1`

Kafka is transport and observability only. Final policy truth remains in the
SeedCore runtime.

## Runtime

Run the delegated intent ingress worker:

```bash
python -m seedcore.infra.kafka.intent_ingress
```

Useful environment variables:

- `SEEDCORE_API` default `http://127.0.0.1:8002`
- `SEEDCORE_KAFKA_CONSUMER_GROUP` optional shared consumer group override
- `SEEDCORE_KAFKA_INTENT_INGRESS_PREFLIGHT_REQUIRED` default `true`
- `SEEDCORE_KAFKA_INTENT_INGRESS_NO_EXECUTE` default `false`
- `SEEDCORE_KAFKA_INTENT_INGRESS_APPEND_FILE` set to `1` to append JSONL under `artifacts/kafka_streams/delegated_intent_ingress.jsonl`

When preflight is required and returns `ok: false`, the ingress worker treats
the event as terminally rejected and does not call the evaluate API.

## Payload Contract

Topic:

```text
seedcore.intent.v1
```

Kafka envelope:

- `event_id`
- `occurred_at`
- `schema_version`
- `producer`
- `payload`

Delegated intent payload schema:

- `stream = "intent"`
- `payload_schema_version = "seedcore.intent.delegated.v0"`
- `request_id`
- `workflow_id` optional
- `correlation_id` optional
- `assistant_namespace` optional
- `owner_context_preflight`
- `gateway_request`
- `metadata` optional

`gateway_request` is a strict `seedcore.agent_action_gateway.v1` request.
That means the external producer should send the same contract SeedCore already
accepts over HTTP, just wrapped in the Kafka envelope.

## Example Producer

Python example for an external assistant gateway:

```python
import json
from datetime import datetime, timedelta, timezone

from confluent_kafka import Producer

from seedcore.infra.kafka.delegated_intent import (
    DelegatedIntentPayload,
    build_delegated_intent_envelope,
)

now = datetime.now(timezone.utc)

payload = DelegatedIntentPayload.model_validate(
    {
        "stream": "intent",
        "payload_schema_version": "seedcore.intent.delegated.v0",
        "request_id": "req-kafka-delegated-001",
        "workflow_id": "wf-kafka-delegated-001",
        "correlation_id": "corr-kafka-delegated-001",
        "assistant_namespace": "openai-agents",
        "owner_context_preflight": {
            "owner_id": "did:seedcore:owner:abc",
            "assistant_id": "agent:openai-assistant-01",
            "delegation_id": "deleg-001",
            "declared_value_usd": 1200.0,
            "required_modalities": ["telemetry"],
            "available_modalities": ["telemetry"],
            "observed_provenance_level": "verified",
            "risk_score": 0.1,
        },
        "gateway_request": {
            "contract_version": "seedcore.agent_action_gateway.v1",
            "request_id": "req-kafka-delegated-001",
            "requested_at": now.isoformat(),
            "idempotency_key": "idem-kafka-delegated-001",
            "policy_snapshot_ref": "snapshot:pkg-delegated-v1",
            "principal": {
                "agent_id": "agent:openai-assistant-01",
                "role_profile": "TRANSFER_COORDINATOR",
                "session_token": "session-123",
                "owner_id": "did:seedcore:owner:abc",
                "delegation_ref": "delegation:deleg-001",
                "hardware_fingerprint": {
                    "fingerprint_id": "hw-fp-001",
                    "public_key_fingerprint": "pk-fp-001",
                },
            },
            "workflow": {
                "type": "restricted_custody_transfer",
                "action_type": "TRANSFER_CUSTODY",
                "valid_until": (now + timedelta(minutes=5)).isoformat(),
            },
            "asset": {
                "asset_id": "asset:lot-8841",
                "product_ref": "product:sku-8841",
                "from_custodian_ref": "principal:facility_mgr_001",
                "to_custodian_ref": "principal:outbound_mgr_002",
                "from_zone": "vault_a",
                "to_zone": "handoff_bay_3",
                "provenance_hash": "sha256:asset-proof-8841",
                "declared_value_usd": 1200.0,
            },
            "approval": {
                "approval_envelope_id": "approval-transfer-001",
            },
            "authority_scope": {
                "scope_id": "scope-transfer-001",
                "asset_ref": "asset:lot-8841",
                "product_ref": "product:sku-8841",
                "facility_ref": "facility:bangkok-01",
                "expected_from_zone": "vault_a",
                "expected_to_zone": "handoff_bay_3",
            },
            "telemetry": {
                "observed_at": now.isoformat(),
                "freshness_seconds": 5,
                "max_allowed_age_seconds": 60,
                "current_zone": "vault_a",
                "evidence_refs": ["evidence:telemetry-001"],
            },
            "security_contract": {
                "hash": "sha256:security-contract-001",
                "version": "rules@transfer-v1",
            },
            "options": {
                "debug": False,
                "no_execute": False,
            },
        },
    }
)

event = build_delegated_intent_envelope(payload, producer="openai-agent-gateway")

producer = Producer({"bootstrap.servers": "127.0.0.1:9092"})
producer.produce("seedcore.intent.v1", value=json.dumps(event).encode("utf-8"))
producer.flush(10.0)
```

The ingress worker expects the standard SeedCore envelope on the wire.

## Operational Notes

- Use `request_id` and `idempotency_key` as stable replay-safe identifiers.
- Use `delegation_ref` from the identity API rather than inventing ad hoc scope IDs.
- Treat `owner_context_preflight` as a trust and delegation gate, not as a final decision.
- Keep secrets out of Kafka payloads. Use references, hashes, and delegated IDs.

## Validation

Focused unit coverage for this ingress path lives in:

- [tests/test_kafka_delegated_intent.py](/Users/ningli/project/seedcore/tests/test_kafka_delegated_intent.py)
