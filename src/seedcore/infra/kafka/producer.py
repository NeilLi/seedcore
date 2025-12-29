import json
from confluent_kafka import Producer  # pyright: ignore[reportMissingImports]


class KafkaProducer:
    def __init__(self, conf: dict):
        self._producer = Producer(conf)

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
