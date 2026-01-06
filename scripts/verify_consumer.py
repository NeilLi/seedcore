import os
from seedcore.infra.kafka.consumer import KafkaConsumer


def main() -> None:
    # -------------------------------------------------------------------------
    # Validate environment
    # -------------------------------------------------------------------------
    required_vars = {
        "CONFLUENT_BOOTSTRAP_SERVERS": os.getenv("CONFLUENT_BOOTSTRAP_SERVERS"),
        "CONFLUENT_API_KEY": os.getenv("CONFLUENT_API_KEY"),
        "CONFLUENT_API_SECRET": os.getenv("CONFLUENT_API_SECRET"),
        "TOPIC_EVENTS_RAW": os.getenv("TOPIC_EVENTS_RAW", "seedcore.events.raw"),
    }

    missing = [k for k, v in required_vars.items() if not v]
    if missing:
        raise ValueError(f"Missing environment variables: {', '.join(missing)}")

    # -------------------------------------------------------------------------
    # Kafka consumer config
    # -------------------------------------------------------------------------
    conf = {
        "bootstrap.servers": required_vars["CONFLUENT_BOOTSTRAP_SERVERS"],
        "security.protocol": "SASL_SSL",
        "sasl.mechanisms": "PLAIN",
        "sasl.username": required_vars["CONFLUENT_API_KEY"],
        "sasl.password": required_vars["CONFLUENT_API_SECRET"],
        "group.id": "seedcore-verify-consumer",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
        "client.id": "seedcore-verify-consumer",
    }

    consumer = KafkaConsumer(conf, topics=[required_vars["TOPIC_EVENTS_RAW"]])

    print("👂 Waiting for messages... (Ctrl+C to exit)")

    try:
        while True:
            msg = consumer.poll_raw(timeout=1.0)

            if msg is None:
                continue

            event = consumer.decode(msg)
            print(f"📥 Received event:\n    {event}")

    except KeyboardInterrupt:
        print("\n🛑 Consumer stopped by user")

    finally:
        consumer.close()


if __name__ == "__main__":
    main()
