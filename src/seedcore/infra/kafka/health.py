from __future__ import annotations

import logging
from typing import Any

from seedcore.infra.kafka.config import base_client_conf

logger = logging.getLogger(__name__)


def kafka_ping(*, timeout_sec: float = 2.0) -> bool:
    """
    Lightweight broker reachability check (metadata). Used for optional /readyz wiring.
    Fail-open for publishers: this is only for explicit health gates.
    """
    try:
        from confluent_kafka.admin import AdminClient  # pyright: ignore[reportMissingImports]
    except Exception as e:
        logger.debug("kafka_ping: admin client unavailable: %s", e)
        return False

    conf: dict[str, Any] = {
        **base_client_conf(),
        "socket.timeout.ms": max(100, int(timeout_sec * 1000)),
    }
    try:
        admin = AdminClient(conf)
        admin.list_topics(timeout=timeout_sec)
        return True
    except Exception as e:
        logger.debug("kafka_ping failed: %s", e)
        return False
