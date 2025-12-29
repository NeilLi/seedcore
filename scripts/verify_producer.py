import os
import time
from seedcore.infra.kafka.producer import KafkaProducer


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
    # Kafka producer config
    # -------------------------------------------------------------------------
    conf = {
        "bootstrap.servers": required_vars["CONFLUENT_BOOTSTRAP_SERVERS"],
        "security.protocol": "SASL_SSL",
        "sasl.mechanisms": "PLAIN",
        "sasl.username": required_vars["CONFLUENT_API_KEY"],
        "sasl.password": required_vars["CONFLUENT_API_SECRET"],
        "client.id": "seedcore-verify-producer",
    }

    producer = KafkaProducer(conf)

    # Send verification event
    producer.send(
        topic=required_vars["TOPIC_EVENTS_RAW"],
        event={
            "organ": "environment_intelligence",
            "signal": "occupancy_spike",
            "value": 0.92,
            "ts": time.time(),
        },
    )
    
    # Ensure message is delivered
    producer.flush(timeout=5.0)
    print("✅ Event sent successfully")


if __name__ == "__main__":
    main()
