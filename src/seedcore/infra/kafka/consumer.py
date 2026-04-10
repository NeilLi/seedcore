# src/seedcore/infra/kafka/consumer.py
import json

try:
    from confluent_kafka import Consumer, KafkaException  # pyright: ignore[reportMissingImports]
except Exception as _confluent_import_error:  # pragma: no cover - exercised in envs without Kafka client
    Consumer = None  # type: ignore[assignment]

    class KafkaException(RuntimeError):
        pass
else:
    _confluent_import_error = None


def _new_consumer(conf: dict):
    if Consumer is None:
        raise RuntimeError(
            "confluent_kafka is required for Kafka consumer usage"
        ) from _confluent_import_error
    return Consumer(conf)

class KafkaConsumer:
    def __init__(self, conf: dict, topics: list[str]):
        self._consumer = _new_consumer(conf)
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
