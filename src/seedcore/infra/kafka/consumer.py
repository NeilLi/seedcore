# src/seedcore/infra/kafka/consumer.py
import json
from confluent_kafka import Consumer, KafkaException  # pyright: ignore[reportMissingImports]

class KafkaConsumer:
    def __init__(self, conf: dict, topics: list[str]):
        self._consumer = Consumer(conf)
        self._consumer.subscribe(topics)

    def poll_raw(self, timeout: float = 1.0):
        msg = self._consumer.poll(timeout)
        if msg is None:
            return None
        if msg.error():
            raise KafkaException(msg.error())
        return msg

    def decode(self, msg) -> dict:
        return json.loads(msg.value().decode("utf-8"))

    def commit(self, msg) -> None:
        self._consumer.commit(message=msg, asynchronous=False)

    def close(self) -> None:
        self._consumer.close()
