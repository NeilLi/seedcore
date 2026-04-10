# Local Host-Mode Helpers

This folder holds host-native SeedCore bring-up scripts for macOS/Linux development.

Use these when you want to run SeedCore directly on your machine without Kubernetes:

- `init-full-db-direct.sh`
- `run-api.sh`
- `run-hal.sh`
- `run-ray-head.sh`
- `run-serve-app.py`
- `run-bootstrap.sh`
- `run-ray-stack.sh`
- `run-task-stack.sh`

## Rust verifier binary (recommended)

The API/HAL host scripts will auto-detect a local Rust verifier binary at:

- `rust/target/release/seedcore-verify`
- `rust/target/debug/seedcore-verify`

Build it once before running local flows:

```bash
cargo build -p seedcore-verify --manifest-path rust/Cargo.toml
```

These scripts are intentionally separate from the main `deploy/` entrypoints because they are:

- localhost-oriented
- best-effort developer workflows
- not the canonical Kubernetes deployment path

`host-env.sh` and `run-api.sh` set `SEEDCORE_HOT_PATH_DEPLOYMENT_ROLE` to **`host`** by default so `/api/v1/pdp/hot-path/status` and `/api/v1/pdp/hot-path/metrics` agree on the `deployment_role` label (see `scripts/host/verify_hot_path_observability.sh`). Kubernetes and Helm use **`kubernetes`**, Ray head **`ray`**, Docker image / `docker/env.example` **`docker`**.

## Local Kafka (optional streams)

For intent / telemetry / policy-outcome transport parity with production posture, see `docs/development/local_kafka_streams_schedule.md`.

Bring up a single KRaft broker:

```bash
docker compose -f deploy/local/docker-compose.kafka.yml up -d
bash deploy/local/init-kafka-topics.sh
```

Set up local Python client (`confluent-kafka`) in the repo virtualenv:

```bash
bash deploy/local/setup-kafka-python.sh
```

Common environment variables:

- `KAFKA_BOOTSTRAP_SERVERS` — default `127.0.0.1:9092`
- `KAFKA_SECURITY_PROTOCOL` — default `PLAINTEXT` (local only)
- `SEEDCORE_KAFKA_POLICY_OUTCOME_ENABLE` — set to `1` to emit redacted PDP hot-path outcomes to `seedcore.policy_outcome.v1`
- `SEEDCORE_KAFKA_READYZ_CHECK` — set to `1` to include broker reachability in `GET /readyz`
- `SEEDCORE_KAFKA_BRIDGE_APPEND_FILE` — set to `1` when running the streams bridge to append JSONL under `artifacts/kafka_streams/bridge.jsonl`

Passive consumer (subscribes to all three topics, structured logs; optional file append):

```bash
python -m seedcore.infra.kafka.bridge
```

Delegated intent ingress worker (consumes `seedcore.intent.v1`, runs owner-context preflight, then forwards to `/api/v1/agent-actions/evaluate`):

```bash
python -m seedcore.infra.kafka.intent_ingress
```

Smoke produce/consume (requires topics and a running broker):

```bash
./.venv/bin/python scripts/kafka/smoke_kafka_streams.py
```

Kafka integration tests (real broker, opt-in):

```bash
SEEDCORE_RUN_KAFKA_INTEGRATION=1 ./.venv/bin/pytest -q tests/test_kafka_local_integration.py
```

External assistant Kafka contract:

- See [kafka_delegated_intent_ingress.md](/Users/ningli/project/seedcore/docs/development/kafka_delegated_intent_ingress.md)

## Restart Sequence

### Lean local mode

Start the backing services first:

```bash
brew services start postgresql@17
brew services start redis
```

Initialize the database if needed:

```bash
bash deploy/local/init-full-db-direct.sh
```

Then start the API and HAL in separate terminals:

```bash
bash deploy/local/run-api.sh
```

```bash
bash deploy/local/run-hal.sh
```

Quick checks:

```bash
curl http://127.0.0.1:8002/health
curl http://127.0.0.1:8003/status
```

Hot-path checks:

```bash
python scripts/host/verify_rct_hot_path_shadow.py
python scripts/host/benchmark_rct_hot_path.py --requests 40 --warmup 4 --concurrency 4
```

Parity mismatch drill (shadow promotion gate): truncates the JSONL ring, fills the promotion window with clean `allow_case` runs, restarts the API with `SEEDCORE_HOT_PATH_PARITY_DRILL_STABLE_DENY=1` (stable path forced deny while the hot path still allows), then posts one more evaluation. Expect a `parity_ok: false` line in the log, `promotion_eligible` / `enforce_ready` false on `GET .../pdp/hot-path/status`, and the sliding window to reflect the mismatch (not a full “reset” of unrelated history). The script **SIGKILLs any TCP listener on `PORT` (default 8002)** until the port is free, then starts its own `uvicorn`; if another API keeps respawning on that port, use `PORT=8012` (and matching `BASE_URL`) or stop the other supervisor first.

```bash
bash scripts/host/drill_hot_path_parity_mismatch.sh
```

### Experimental host-Ray mode

Use this only when you need local Ray/Serve/bootstrap behavior.

Start local services:

```bash
brew services start postgresql@17
brew services start redis
```

Start Neo4j for semantic memory (matches `deploy/local/host-env.sh` defaults
`NEO4J_USER=neo4j`, `NEO4J_PASSWORD=password`):

```bash
docker start seedcore-neo4j || \
docker run -d --name seedcore-neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password \
  neo4j:5
```

Start the API and HAL in separate terminals:

```bash
bash deploy/local/run-api.sh
```

```bash
bash deploy/local/run-hal.sh
```

Start the Ray head in a dedicated terminal:

```bash
bash deploy/local/run-ray-head.sh foreground
```

Deploy the organism Serve app in another terminal:

```bash
python deploy/local/run-serve-app.py organism
```

Bootstrap the organism:

```bash
BOOTSTRAP_MODE=organism bash deploy/local/run-bootstrap.sh
```

Bootstrap one dispatcher with graph dispatchers disabled:

```bash
BOOTSTRAP_MODE=dispatchers DISPATCHER_COUNT=1 ENABLE_GRAPH_DISPATCHERS=false SEEDCORE_GRAPH_DISPATCHERS=0 bash deploy/local/run-bootstrap.sh
```

### Task execution stack

Use this when you want queued tasks to execute locally through `/pipeline/route-and-execute`.

It starts:

- Ray head
- Serve `organism`
- Serve `coordinator`
- organism bootstrap
- one queue dispatcher

Start:

```bash
bash deploy/local/run-task-stack.sh start
```

Status:

```bash
bash deploy/local/run-task-stack.sh status
```

Stop:

```bash
bash deploy/local/run-task-stack.sh stop
```

Quick checks:

```bash
curl http://127.0.0.1:8000/organism/health
curl http://127.0.0.1:8000/organism/init-status
curl http://127.0.0.1:8000/-/routes
```

### Shutdown

Stop the local runtime:

```bash
bash deploy/local/run-ray-head.sh stop
brew services stop postgresql@17
brew services stop redis
docker stop seedcore-neo4j
```
