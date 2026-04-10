#!/usr/bin/env python3
"""
Producer/consumer smoke for local Kafka (Phase 0–1 acceptance).
Requires broker at KAFKA_BOOTSTRAP_SERVERS and topics from deploy/local/init-kafka-topics.sh.
"""
from __future__ import annotations

import json
import os
import sys
import time

# Allow running without installation when PYTHONPATH=src
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


def _matches_smoke_message(body: object, *, topic: str, suffix: str) -> bool:
    if not isinstance(body, dict):
        return False
    payload = body.get("payload")
    if not isinstance(payload, dict):
        return False
    return (
        payload.get("kind") == "smoke"
        and payload.get("topic") == topic
        and payload.get("suffix") == suffix
    )


def main() -> int:
    from seedcore.infra.kafka.config import (
        consumer_conf,
        kafka_producer_service_name,
        producer_conf,
    )
    from seedcore.infra.kafka.consumer import KafkaConsumer
    from seedcore.infra.kafka.envelope import build_stream_envelope
    from seedcore.infra.kafka.producer import KafkaProducer
    from seedcore.infra.kafka.topics import ALL_STREAM_TOPICS_V1

    producer = KafkaProducer(producer_conf())
    suffix = str(int(time.time()))
    for topic in ALL_STREAM_TOPICS_V1:
        env = build_stream_envelope(
            {"kind": "smoke", "topic": topic, "suffix": suffix},
            producer=kafka_producer_service_name(),
        )
        producer.send(topic, env)
    producer.flush(10.0)
    producer.close()

    group = f"seedcore-smoke-{suffix}"
    consumer = KafkaConsumer(
        consumer_conf(group_id=group, extra={"enable.auto.commit": True}),
        list(ALL_STREAM_TOPICS_V1),
    )
    seen: set[tuple[str, str]] = set()
    deadline = time.monotonic() + 30.0
    try:
        while time.monotonic() < deadline and len(seen) < len(ALL_STREAM_TOPICS_V1):
            msg = consumer.poll_raw(timeout=2.0)
            if msg is None:
                continue
            body = consumer.decode(msg)
            topic = msg.topic()
            if _matches_smoke_message(body, topic=topic, suffix=suffix):
                seen.add(topic)
    finally:
        consumer.close()

    if len(seen) < len(ALL_STREAM_TOPICS_V1):
        print("smoke failed: expected one message per topic", file=sys.stderr)
        print(f"got {seen!r}", file=sys.stderr)
        return 1
    print("smoke ok:", json.dumps(sorted(seen), default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
