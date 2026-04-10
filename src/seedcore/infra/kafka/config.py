from __future__ import annotations

import os
from typing import Any


def kafka_bootstrap_servers() -> str:
    return os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092").strip()


def kafka_security_protocol() -> str:
    return os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT").strip().upper() or "PLAINTEXT"


def kafka_producer_service_name() -> str:
    return os.getenv("SEEDCORE_KAFKA_PRODUCER_NAME", "seedcore-api").strip() or "seedcore-api"


def kafka_consumer_group_id(default: str = "seedcore-streams-bridge") -> str:
    return os.getenv("SEEDCORE_KAFKA_CONSUMER_GROUP", default).strip() or default


def base_client_conf() -> dict[str, Any]:
    return {
        "bootstrap.servers": kafka_bootstrap_servers(),
        "security.protocol": kafka_security_protocol(),
    }


def producer_conf(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    conf = {
        **base_client_conf(),
        "client.id": kafka_producer_service_name(),
    }
    if extra:
        conf.update(extra)
    return conf


def consumer_conf(*, group_id: str | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    conf = {
        **base_client_conf(),
        "group.id": group_id or kafka_consumer_group_id(),
        "enable.auto.commit": False,
        "auto.offset.reset": "earliest",
    }
    if extra:
        conf.update(extra)
    return conf
