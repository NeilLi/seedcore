#!/usr/bin/env bash
# Create SeedCore stream topics (Phase 1 local Kafka schedule).
# Requires: docker compose -f deploy/local/docker-compose.kafka.yml up -d
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${ROOT}/deploy/local/docker-compose.kafka.yml"
CONTAINER="${KAFKA_CONTAINER_NAME:-seedcore-kafka}"
REPLICATION="${KAFKA_TOPIC_REPLICATION_FACTOR:-1}"

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "Container ${CONTAINER} not found. Start Kafka first:" >&2
  echo "  docker compose -f deploy/local/docker-compose.kafka.yml up -d" >&2
  exit 1
fi

kafka_topics() {
  docker exec "$CONTAINER" /opt/kafka/bin/kafka-topics.sh "$@"
}

create_topic() {
  local name="$1"
  kafka_topics --bootstrap-server localhost:9092 \
    --create --if-not-exists \
    --topic "$name" \
    --replication-factor "$REPLICATION" \
    --partitions "${KAFKA_TOPIC_PARTITIONS:-3}"
}

create_topic "seedcore.intent.v1"
create_topic "seedcore.telemetry.v1"
create_topic "seedcore.policy_outcome.v1"

echo "Topics ready:"
kafka_topics --bootstrap-server localhost:9092 --list
