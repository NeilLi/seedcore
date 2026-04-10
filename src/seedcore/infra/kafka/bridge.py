from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from seedcore.infra.kafka.config import consumer_conf, kafka_consumer_group_id
from seedcore.infra.kafka.consumer import KafkaConsumer
from seedcore.infra.kafka.topics import ALL_STREAM_TOPICS_V1

logger = logging.getLogger(__name__)

_DEFAULT_ARTIFACTS_DIR = "artifacts/kafka_streams"


def _artifacts_log_path() -> Path:
    raw = os.getenv("SEEDCORE_KAFKA_BRIDGE_LOG_DIR", _DEFAULT_ARTIFACTS_DIR).strip()
    return Path(raw)


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _format_record(topic: str, event: dict[str, Any]) -> dict[str, Any]:
    return {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "topic": topic,
        "event": event,
    }


def run_streams_bridge(
    *,
    log_file: TextIO | None = None,
    append_file_path: Path | None = None,
) -> None:
    """
    Subscribe to all three stream topics; log structured lines and optionally append JSONL.
    Read-only: does not mutate PKG, PDP config, or twin state.
    """
    conf = consumer_conf(group_id=kafka_consumer_group_id("seedcore-streams-bridge"))
    consumer = KafkaConsumer(conf, list(ALL_STREAM_TOPICS_V1))

    append_fp: TextIO | None = None
    if append_file_path is not None:
        append_file_path.parent.mkdir(parents=True, exist_ok=True)
        append_fp = append_file_path.open("a", encoding="utf-8")

    stop = False

    def _handle_sig(_sig, _frame) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    logger.info("streams bridge subscribed: %s", ", ".join(ALL_STREAM_TOPICS_V1))

    try:
        while not stop:
            msg = consumer.poll_raw(timeout=1.0)
            if msg is None:
                continue
            topic = msg.topic()
            try:
                event = consumer.decode(msg)
            except json.JSONDecodeError as e:
                logger.warning("skip non-json topic=%s err=%s", topic, e)
                consumer.commit(msg)
                continue
            line = _format_record(topic, event)
            logger.info("kafka_stream %s", json.dumps(line, default=str))
            if log_file is not None:
                log_file.write(json.dumps(line, default=str) + "\n")
                log_file.flush()
            if append_fp is not None:
                append_fp.write(json.dumps(line, default=str) + "\n")
                append_fp.flush()
            consumer.commit(msg)
    finally:
        consumer.close()
        if append_fp is not None:
            append_fp.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    path = _artifacts_log_path() / "bridge.jsonl"
    if _truthy_env("SEEDCORE_KAFKA_BRIDGE_APPEND_FILE"):
        run_streams_bridge(append_file_path=path)
    else:
        run_streams_bridge()


if __name__ == "__main__":
    main()
