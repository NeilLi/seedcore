# Schedule: Local Kafka microservice for intent, telemetry, and policy outcomes

**References:** [North Star: Autonomous Trade Environment](north_star_autonomous_trade_environment.md) (Kafka as transport for intent, telemetry, policy outcome streams), existing Python wrappers in `src/seedcore/infra/kafka/`.

**Principle:** Kafka is **transport and observability**, not a source of policy truth. Authoritative decisions and evidence remain in the SeedCore runtime (PDP, PKG, durable stores). Local Kafka mirrors production posture (Confluent-style cluster) without cloud coupling.

---

## Target topology (local)

| Stream | Suggested topic prefix | Primary producers (early) | Primary consumers (early) |
| :--- | :--- | :--- | :--- |
| **Intent** | `seedcore.intent.v1` | Gateway / coordinator emit (ActionIntent-shaped payloads) | PDP-adjacent evaluator, audit logger, optional verifier |
| **Telemetry** | `seedcore.telemetry.v1` | Edge/host simulators, HAL capture hooks | Forensic integrator, twin promotion pipeline, verifier |
| **Policy outcome** | `seedcore.policy_outcome.v1` | PDP hot-path / post-decision publisher | Operator metrics, replay indexers, quarantine automation |

Use **JSON** payloads in Phase 0–1 (align with existing `KafkaProducer.send`); add **Schema Registry** (local) in Phase 2 if you need evolution discipline.

---

## Phase 0 — Local broker “microservice” (Week 1)

**Goal:** One command brings up Kafka (+ ZooKeeper or KRaft) on `localhost` for dev/CI.

- **Implemented:** `deploy/local/docker-compose.kafka.yml` (Apache Kafka **KRaft**, single broker, **9092** plaintext), `scripts/kafka/smoke_kafka_streams.py`, and env documentation in `deploy/local/README.md` (`KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_SECURITY_PROTOCOL`).
- **Implemented (local Python setup):** `deploy/local/setup-kafka-python.sh` prepares `.venv` with `confluent-kafka` and Kafka test dependencies for local smoke and integration runs.
- **Acceptance:** `kafka-topics.sh` (or container exec) can list topics; producer/consumer smoke from `seedcore` Python using `confluent-kafka` (reuse `KafkaProducer` / `KafkaConsumer`).
- **Out of scope:** TLS, ACLs, multi-broker (defer to “prod-like” track).

---

## Phase 1 — Topics, contracts, and read-only consumers (Week 2)

**Goal:** Create the three topics and consume without changing authoritative paths.

- **Implemented:** `deploy/local/init-kafka-topics.sh`, envelope helper `seedcore.infra.kafka.envelope.build_stream_envelope`, topic constants in `seedcore.infra.kafka.topics`, passive bridge `python -m seedcore.infra.kafka.bridge` (optional JSONL under `artifacts/kafka_streams/` when `SEEDCORE_KAFKA_BRIDGE_APPEND_FILE=1`).
- Create topics (script or compose init):  
  `seedcore.intent.v1`, `seedcore.telemetry.v1`, `seedcore.policy_outcome.v1`  
  Optional: compacted topic for latest intent per key (`cleanup.policy=compact`) — only if you define a stable keying scheme (`intent_id` / `workflow_id`).
- Publish **JSON envelope** convention (minimum):
  - `event_id`, `occurred_at`, `schema_version`, `payload`, `producer` (service name).
- Implement a **thin bridge** (Python module or small CLI):
  - Subscribe to all three topics; log to structured logger or append to file under `artifacts/` for drills.
- **Acceptance:** With runtime in host mode, synthetic events appear in all three topics and are readable by a single consumer process.
- **Invariant:** No consumer mutates PKG, PDP config, or twin state without an explicit later phase.

---

## Phase 2 — Wire one producer path end-to-end (Weeks 3–4)

Pick **one** stream first (recommended: **policy_outcome**) because it is smallest and aligns with north-star “verifier / outcome” monitoring.

### 2a. Policy outcome (recommended first)

- After a synchronous PDP decision (or governed receipt mint), **optionally** publish a redacted outcome event (disposition, reason code, snapshot ref hash, **no** raw secrets).
- Feature flag: `SEEDCORE_KAFKA_POLICY_OUTCOME_ENABLE=1`.
- **Implemented:** PDP **hot path** (`evaluate_pdp_hot_path`) publishes to `seedcore.policy_outcome.v1` via `seedcore.infra.kafka.policy_outcome` when the flag is set (best-effort producer).
- **Acceptance:** Q2 operator or MCP can correlate HTTP/API truth with Kafka timeline for the same `workflow_id` / `audit_id`.

### 2b. Intent (second)

- Publish when ActionIntent is accepted or rejected at the gateway boundary (before or after PDP — document which).
- **Implemented (external ingress path):** `seedcore.infra.kafka.intent_ingress` consumes delegated intent events from `seedcore.intent.v1`, validates `seedcore.intent.delegated.v0` payloads, runs owner-context preflight through the authoritative API surface, and forwards valid events to `/api/v1/agent-actions/evaluate`.
- **Implemented (contract helper):** `seedcore.infra.kafka.delegated_intent.DelegatedIntentPayload` and `build_delegated_intent_envelope` define the external assistant payload/envelope shape used by Kafka producers.
- **Acceptance:** Intent stream count matches gateway logs for a fixture drill.

### 2c. Telemetry (third)

- Publish from edge telemetry envelope path (see `docs/schemas/edge_telemetry_envelope_v0.schema.json`); consider size limits and sampling for local dev.
- **Acceptance:** Verifier or stub consumer can join intent id → telemetry batch by correlation id.

---

## Phase 3 — Microservice boundaries and failure modes (Weeks 5–6)

**Goal:** Treat Kafka as a **component** with explicit degradation.

- Document **fail-closed vs fail-open** for publishing:
  - Default: if Kafka is down, **core path still completes** (HTTP/DB); publisher drops or buffers with bounded queue (prefer drop + metric for local).
  - **Repo default (implemented):** optional publishers are **fail-open** (errors logged; hot path never raises). `/readyz` treats Kafka as **optional** unless `SEEDCORE_KAFKA_READYZ_CHECK=1`, in which case readiness is **fail-closed on Kafka** for deployments that require the broker up.
- Add health: small **`kafka_ping`** or reuse `/readyz` dependency optional flag.
  - **Implemented:** `seedcore.infra.kafka.health.kafka_ping` and `GET /readyz` when `SEEDCORE_KAFKA_READYZ_CHECK=1`.
- **Acceptance:** Kill broker mid-run; RCT / PDP path still passes host acceptance; publisher surfaces clear error without crashing coordinator.

---

## Phase 4 — CI and drills (Week 7+)

- Optional **GitHub Actions** job: compose up Kafka, run smoke producer/consumer + one integration test.
- **Implemented (smoke path):** workflow job `kafka-smoke` in `.github/workflows/unit-tests.yml` (compose up → topic init → `scripts/kafka/smoke_kafka_streams.py`).
- **Implemented (on-demand integration path):** workflow-dispatch flag `run_kafka_local_integration` enables separate job `kafka-local-integration` in `.github/workflows/unit-tests.yml` to run `tests/test_kafka_local_integration.py` against a real broker on demand.
- Align with [north_star_autonomous_trade_environment.md](north_star_autonomous_trade_environment.md) **verifier** story: stub `RESULT_VERIFIER` consumer reads `policy_outcome` + `telemetry` and triggers **quarantine signal** only through existing APIs (not by writing Kafka).

---

## Milestone summary

| Week | Milestone |
| :--- | :--- |
| 1 | Local Kafka compose; smoke produce/consume |
| 2 | Three topics + envelope + passive consumer |
| 3–4 | Policy outcome → intent → telemetry producers (flagged) |
| 5–6 | Degradation semantics + health hooks |
| 7+ | CI smoke + verifier-aligned consumers (API-driven side effects only) |

---

## Dependencies and repo touchpoints

- **Clients:** `src/seedcore/infra/kafka/` — `producer.py` (incl. `KafkaProducerBestEffort`), `consumer.py`, `config.py`, `envelope.py`, `delegated_intent.py`, `topics.py`, `health.py`, `policy_outcome.py`, `bridge.py`, `intent_ingress.py` (`confluent-kafka` in `pyproject.toml`).
- **Deploy:** `deploy/local/docker-compose.kafka.yml`, `deploy/local/init-kafka-topics.sh` (separate from full DB stack).
- **Local setup:** `deploy/local/setup-kafka-python.sh` for repo-local Python client install and verification.
- **Docs:** cross-link from [north_star_autonomous_trade_environment.md](north_star_autonomous_trade_environment.md) “Cluster Service Posture” row to this file for **local** parity.
- **Tests:** `tests/test_kafka_stream_envelope.py`, `tests/test_kafka_streams_runtime.py`, `tests/test_kafka_local_integration.py`, `tests/test_kafka_delegated_intent.py`.

---

## Risks / non-goals (local track)

- **Non-goal:** Making Kafka the system of record for policy or evidence.
- **Risk:** PII or full telemetry in topics — use redaction and topic ACL patterns before any shared cluster.
- **Risk:** Ordering assumptions across topics — design correlation ids; do not rely on global total order.
