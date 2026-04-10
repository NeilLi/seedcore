#!/usr/bin/env bash
# Prepare local Python environment for SeedCore Kafka development.
#
# Usage:
#   bash deploy/local/setup-kafka-python.sh
#   VENV_PATH=/path/to/venv bash deploy/local/setup-kafka-python.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_PATH="${VENV_PATH:-${ROOT}/.venv}"

if [[ ! -d "${VENV_PATH}" ]]; then
  echo "Creating virtualenv at ${VENV_PATH}"
  python3 -m venv "${VENV_PATH}"
fi

PY="${VENV_PATH}/bin/python"

echo "Installing/refreshing Kafka test dependencies in ${VENV_PATH}"
"${PY}" -m pip install --upgrade pip
"${PY}" -m pip install "confluent-kafka>=2.0.0" "pytest>=8.2"

echo "Verifying confluent_kafka import"
"${PY}" - <<'PY'
import confluent_kafka
print("confluent_kafka:", confluent_kafka.__version__)
PY

cat <<EOF

Kafka Python setup complete.
Next steps:
  1) docker compose -f deploy/local/docker-compose.kafka.yml up -d
  2) bash deploy/local/init-kafka-topics.sh
  3) ${PY} scripts/kafka/smoke_kafka_streams.py
  4) SEEDCORE_RUN_KAFKA_INTEGRATION=1 ${VENV_PATH}/bin/pytest -q tests/test_kafka_local_integration.py

EOF
