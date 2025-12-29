import json
from confluent_kafka import Consumer, KafkaException  # pyright: ignore[reportMissingImports]


class KafkaConsumer:
    def __init__(self, conf: dict, topics: list[str]):
        self._consumer = Consumer(conf)
        self._consumer.subscribe(topics)

    def poll(self, timeout: float = 1.0) -> dict | None:
        msg = self._consumer.poll(timeout)

        if msg is None:
            return None

        if msg.error():
            raise KafkaException(msg.error())

        event = json.loads(msg.value().decode("utf-8"))
        self._consumer.commit(msg)
        return event

    def close(self) -> None:
        self._consumer.close()
