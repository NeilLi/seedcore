from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from seedcore.infra.kafka.config import base_client_conf, consumer_conf, producer_conf
from seedcore.infra.kafka.consumer import KafkaConsumer
from seedcore.infra.kafka.envelope import build_stream_envelope
from seedcore.infra.kafka.policy_outcome import publish_pdp_hot_path_policy_outcome_best_effort
from seedcore.infra.kafka.producer import KafkaProducer
from seedcore.infra.kafka.topics import TOPIC_POLICY_OUTCOME_V1
from seedcore.models.action_intent import (
    ActionIntent,
    IntentAction,
    IntentEnvironment,
    IntentPrincipal,
    IntentResource,
    SecurityContract,
)
from seedcore.models.pdp_hot_path import (
    HotPathAssetContext,
    HotPathDecisionView,
    HotPathEvaluateRequest,
    HotPathEvaluateResponse,
    HotPathTelemetryContext,
)

pytestmark = pytest.mark.kafka_integration


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _require_enabled() -> None:
    if not _truthy_env("SEEDCORE_RUN_KAFKA_INTEGRATION"):
        pytest.skip(
            "Kafka local integration tests are opt-in. "
            "Set SEEDCORE_RUN_KAFKA_INTEGRATION=1 to run."
        )


def _require_confluent() -> None:
    try:
        import confluent_kafka  # noqa: F401
    except Exception as exc:  # pragma: no cover - environment-specific
        pytest.skip(f"confluent_kafka unavailable: {exc}")


def _wait_for_matching_message(
    consumer: KafkaConsumer,
    *,
    matcher,
    timeout_sec: float = 20.0,
) -> dict:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        msg = consumer.poll_raw(timeout=1.0)
        if msg is None:
            continue
        body = consumer.decode(msg)
        if matcher(body):
            return body
    raise AssertionError("timed out waiting for matching Kafka message")


@pytest.fixture(scope="module")
def _kafka_topics_ready():
    _require_enabled()
    _require_confluent()
    from confluent_kafka.admin import AdminClient, NewTopic  # pyright: ignore[reportMissingImports]

    admin = AdminClient(base_client_conf())
    try:
        metadata = admin.list_topics(timeout=5.0)
    except Exception as exc:
        pytest.fail(f"Kafka broker unreachable for local integration tests: {exc}")

    existing = set(metadata.topics.keys())
    to_create = []
    for topic in (TOPIC_POLICY_OUTCOME_V1,):
        if topic not in existing:
            to_create.append(NewTopic(topic, num_partitions=3, replication_factor=1))
    if to_create:
        futures = admin.create_topics(to_create)
        for topic, fut in futures.items():
            try:
                fut.result(10.0)
            except Exception as exc:
                # Topic may already be created by a parallel test/command.
                if "TOPIC_ALREADY_EXISTS" not in str(exc):
                    pytest.fail(f"failed creating topic {topic}: {exc}")


def test_local_kafka_roundtrip_envelope(_kafka_topics_ready):
    suffix = f"it-{uuid4().hex}"
    group_id = f"seedcore-it-roundtrip-{suffix}"

    consumer = KafkaConsumer(
        consumer_conf(
            group_id=group_id,
            extra={
                "enable.auto.commit": True,
                "auto.offset.reset": "latest",
            },
        ),
        [TOPIC_POLICY_OUTCOME_V1],
    )
    # Give group assignment a moment before produce.
    consumer.poll_raw(timeout=0.2)

    producer = KafkaProducer(producer_conf())
    try:
        event = build_stream_envelope(
            {"kind": "integration", "stream": "policy_outcome", "suffix": suffix},
            producer="seedcore-it",
        )
        producer.send(TOPIC_POLICY_OUTCOME_V1, event)
        producer.flush(10.0)
        found = _wait_for_matching_message(
            consumer,
            matcher=lambda body: (
                isinstance(body, dict)
                and isinstance(body.get("payload"), dict)
                and body["payload"].get("suffix") == suffix
            ),
            timeout_sec=20.0,
        )
    finally:
        producer.close()
        consumer.close()

    assert found["producer"] == "seedcore-it"
    assert found["payload"]["kind"] == "integration"
    assert found["payload"]["stream"] == "policy_outcome"
    assert found["payload"]["suffix"] == suffix


def test_policy_outcome_publisher_emits_redacted_payload(_kafka_topics_ready, monkeypatch: pytest.MonkeyPatch):
    import seedcore.infra.kafka.policy_outcome as policy_outcome

    suffix = f"it-redacted-{uuid4().hex}"
    group_id = f"seedcore-it-policy-{suffix}"

    if policy_outcome._producer is not None:
        policy_outcome._producer.close()
    policy_outcome._producer = None
    policy_outcome._producer_init_failed = False

    monkeypatch.setenv("SEEDCORE_KAFKA_POLICY_OUTCOME_ENABLE", "1")
    monkeypatch.setenv("SEEDCORE_KAFKA_PRODUCER_NAME", "seedcore-it-policy")

    consumer = KafkaConsumer(
        consumer_conf(
            group_id=group_id,
            extra={
                "enable.auto.commit": True,
                "auto.offset.reset": "latest",
            },
        ),
        [TOPIC_POLICY_OUTCOME_V1],
    )
    consumer.poll_raw(timeout=0.2)

    now = datetime.now(timezone.utc)
    request = HotPathEvaluateRequest(
        request_id=f"req-{suffix}",
        requested_at=now,
        policy_snapshot_ref="snapshot:pkg-prod-kafka-it",
        action_intent=ActionIntent(
            intent_id=f"intent-{suffix}",
            timestamp=now.isoformat(),
            valid_until=(now + timedelta(seconds=60)).isoformat(),
            principal=IntentPrincipal(
                agent_id="agent:it",
                role_profile="TRANSFER_COORDINATOR",
                session_token="session-it",
            ),
            action=IntentAction(
                type="TRANSFER_CUSTODY",
                operation="MOVE",
                security_contract=SecurityContract(
                    hash="sha256:it-policy",
                    version="rules@it",
                ),
            ),
            resource=IntentResource(
                asset_id="asset:it-001",
                provenance_hash="sha256:it-provenance",
            ),
            environment=IntentEnvironment(),
        ),
        asset_context=HotPathAssetContext(asset_ref="asset:it-001"),
        telemetry_context=HotPathTelemetryContext(observed_at=now.isoformat()),
    )
    response = HotPathEvaluateResponse(
        request_id=request.request_id,
        decided_at=now,
        latency_ms=9,
        decision=HotPathDecisionView(
            allowed=True,
            disposition="allow",
            reason_code="restricted_custody_transfer_allowed",
            reason="restricted_custody_transfer_allowed",
            policy_snapshot_ref="snapshot:pkg-prod-kafka-it",
            policy_snapshot_hash="sha256:it-snapshot",
        ),
        trust_gaps=[],
    )

    try:
        publish_pdp_hot_path_policy_outcome_best_effort(request, response)
        found = _wait_for_matching_message(
            consumer,
            matcher=lambda body: (
                isinstance(body, dict)
                and isinstance(body.get("payload"), dict)
                and body["payload"].get("request_id") == request.request_id
            ),
            timeout_sec=20.0,
        )
    finally:
        consumer.close()
        if policy_outcome._producer is not None:
            policy_outcome._producer.close()
        policy_outcome._producer = None
        policy_outcome._producer_init_failed = False

    payload = found["payload"]
    assert payload["request_id"] == request.request_id
    assert payload["intent_id"] == request.action_intent.intent_id
    assert payload["policy_snapshot_hash"] == "sha256:it-snapshot"
    assert payload["stream"] == "policy_outcome"
    assert payload["reason_code"] == "restricted_custody_transfer_allowed"
    # Redaction guard: payload must not leak receipt/signer/token material.
    assert "execution_token" not in payload
    assert "governed_receipt" not in payload
    assert "signer_provenance" not in payload
