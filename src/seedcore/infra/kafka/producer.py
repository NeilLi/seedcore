import json
import logging

try:
    from confluent_kafka import Producer  # pyright: ignore[reportMissingImports]
except Exception as _confluent_import_error:  # pragma: no cover - exercised in envs without Kafka client
    Producer = None  # type: ignore[assignment]
else:
    _confluent_import_error = None

logger = logging.getLogger(__name__)


def _new_producer(conf: dict):
    if Producer is None:
        raise RuntimeError(
            "confluent_kafka is required for Kafka producer usage"
        ) from _confluent_import_error
    return Producer(conf)


class KafkaProducer:
    def __init__(self, conf: dict):
        self._producer = _new_producer(conf)

    def _delivery_report(self, err, msg) -> None:
        if err is not None:
            raise RuntimeError(f"Kafka delivery failed: {err}")

    def send(self, topic: str, event: dict) -> None:
        """
        Send a single event to Kafka.
        Non-blocking; delivery is handled asynchronously.
        """
        self._producer.produce(
            topic=topic,
            value=json.dumps(event).encode("utf-8"),
            on_delivery=self._delivery_report,
        )
        # Serve delivery callbacks
        self._producer.poll(0)

    def flush(self, timeout: float = 5.0) -> None:
        """
        Block until all outstanding messages are delivered.
        """
        self._producer.flush(timeout)

    def close(self) -> None:
        self.flush()


class KafkaProducerBestEffort:
    """
    Fire-and-forget JSON producer: delivery failures are logged, never raised.
    Use for optional observability paths so a down broker cannot break the hot path.
    """

    def __init__(self, conf: dict):
        self._producer = _new_producer(conf)

    def _delivery_report(self, err, msg) -> None:
        if err is not None:
            topic = "?"
            try:
                if msg is not None:
                    topic = msg.topic()
            except Exception:
                pass
            logger.warning("Kafka best-effort delivery failed: %s topic=%s", err, topic)

    def send(self, topic: str, event: dict) -> None:
        try:
            self._producer.produce(
                topic=topic,
                value=json.dumps(event).encode("utf-8"),
                on_delivery=self._delivery_report,
            )
            self._producer.poll(0)
        except Exception as e:
            logger.warning("Kafka best-effort publish dropped before enqueue: %s topic=%s", e, topic)

    def flush(self, timeout: float = 0.5) -> None:
        self._producer.flush(timeout)

    def close(self) -> None:
        self.flush()
