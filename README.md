# SeedCore

Unit-test workflow is currently set to manual runs only.

## Zero-Trust Runtime for Governed Agents and Robotic Endpoints

SeedCore is a zero-trust runtime for governed AI-assisted operations. It sits between AI judgment, accountable agents, controlled endpoints, operators, and high-value physical or commercial assets. Actions that can affect custody, release, or external systems are denied by default until identity, policy, provenance, and execution conditions are verified.

The current focus is narrow and practical: prove one governed end-to-end workflow for release-style custody actions, with clear policy decisions, tokenized execution, and replayable evidence.

## Current Codebase Snapshot

Based on the current repository state, SeedCore is already organized around the three trust problems that most agent systems leave unresolved:

1. **Verifiable authority boundary**
2. **Policy enforcement layer**
3. **Trusted chain of custody**

Recent changes reinforced that direction in two concrete areas:

1. **HAL transition attestation and receipt verification**
2. **Execution token TTL, revocation, and emergency stop controls**

The current baseline now includes:

- HAL transition receipts that prefer Ed25519 signatures and fall back to HMAC only when asymmetric key material is not configured
- evidence bundles that bind transition receipt hashes into execution receipts for governed closure and replay checks
- short-lived execution tokens with explicit TTL enforcement at both PDP issuance time and HAL validation time
- Redis-backed token revocation and an operator-triggered emergency cutoff path at the HAL boundary
- PKG-first routing where action execution remains behind a policy-produced proto-plan rather than LLM-only actuation

This means the repository is no longer just describing zero-trust ideas. It already contains the runtime seams needed to make authority, policy, and custody inspectable in code.

## Trust Challenges

### 1. Verifiable Authority Boundary

SeedCore already has a concrete authority artifact: `ExecutionToken`.

Current implementation:

- the coordinator derives `ActionIntent` and issues signed `ExecutionToken` objects
- HAL validates token signature, expiry, and endpoint constraints before actuation
- HAL transition receipts can prove which endpoint executed a governed action
- the robot-sim and HAL boundary now reject revoked tokens and emergency-stopped token populations

Current gap profile:

- Ed25519 private keys are still delivered through environment or Kubernetes secret injection rather than a hardware-backed signer
- revocation exists, but it is Redis-backed operational control rather than hardware-rooted remote attestation
- the forensic sealer path still contains mocked signing behavior and should not be treated as production-grade device attestation yet

### 2. Policy Enforcement Layer

SeedCore already has a real policy layer instead of prompt-only guardrails.

Current implementation:

- PKG evaluation runs through the `ops/pkg` stack with OPA WASM support
- coordinator execution follows a PKG-first flow and enforces a PKG-mandatory gate for action tasks
- routing hints are extracted from PKG proto-plans rather than trusted from cognitive output alone
- policy snapshots can be reloaded manually through the existing PKG management path

Current gap profile:

- policy rollout is still operationally heavy; the current update flow restarts pods rather than streaming hot updates fleet-wide
- OCPS drift thresholds remain useful routing signals, but high-risk break-glass policy should keep moving toward deterministic, explainable procedures
- compliance distribution to edge runtimes is not yet an always-on OTA policy stream

### 3. Trusted Chain of Custody

SeedCore already has the beginnings of a governed custody ledger.

Current implementation:

- evidence bundles include `intent_ref`, execution timing, telemetry, and execution receipts
- HAL-backed transitions can carry signed `transition_receipt` payloads with nonce-based replay detection
- governed closure persists receipt hash, nonce, transition sequence, endpoint identity, and authority source
- forensic sealing captures a pre-contact evidence structure for edge-side custody events

Current gap profile:

- the primary custody trail still depends on SeedCore-managed stores; it is not yet anchored into an immutable external transparency log
- `ExecutionReceipt.previous_receipt_hash` exists in the model, but a full external tamper-evident receipt chain is not yet the default system of record
- inter-agent and cognitive handoff custody is not yet represented with the same signed transition contract used for HAL actuation

**Execution boundary**

```text
AI Judgment -> Agent Accountability -> Zero-Trust Policy -> Robotic Embodiment -> Immutable Custody
```

## What SeedCore Is

SeedCore is not a chatbot wrapper or a generic tool-calling layer. It is a governed runtime that converts advisory AI output into policy-checked execution.

In the current repository baseline, **AI judgment** lives in the cognitive and coordinator planning stack. That layer can interpret, enrich, and route work, but it does not authorize high-stakes execution.

The current baseline is being shaped to provide:

- deny-by-default authorization before movement or release
- governed dispatch through accountable agents
- policy-bound robotic and operator execution
- playback-grade telemetry and black-box forensics
- quarantine, rollback, and recovery paths that preserve custody state

## Judgment and Accountability Split

SeedCore separates orchestration from authorization:

- **`TaskPayload`** is the judgment envelope. It carries routing, multimodal context, and planning inputs.
- **`ActionIntent`** is the accountability contract. It is the narrower policy object submitted to the PDP by the accountable agent.
- Routing may select an agent, but routing does not grant authority.
- Physical or otherwise high-stakes actions remain deny-by-default until the PDP returns a signed `ExecutionToken`.

## Who This Repository Is For

- **Evaluators / Reviewers**: read *Why SeedCore Exists*, *Target Architecture*, and *Runtime Surfaces*
- **System Builders / Contributors**: read *Repository Upgrade Path*, *Quick Start*, and *Architecture Overview*
- **Researchers / Architects**: read *Target Architecture*, *Design Notes*, and *Advanced Architecture*

## Why SeedCore Exists

Most AI systems are built to generate text, images, or recommendations. Physical operations need a harder contract:

- actions must be authorized before execution
- agents must be accountable for every controlled handoff
- actuators must behave as policy subjects, not autonomous peers
- provenance and custody evidence must survive failures and disputes
- exception paths must default to quarantine rather than graceful drift into execution

SeedCore fills that gap by keeping AI advisory and moving execution authority into explicit runtime policy.

## Target Architecture

The target direction for SeedCore is a zero-trust custody runtime built around one strict principle:

> The model can propose. The Agent is accountable. The PDP decides. The robot executes. The evidence closes the loop.

This direction depends on five core contracts.

### 1. Actor Authority and the Stateless PDP

- The **Policy Decision Point (PDP)** should remain stateless and synchronous.
- `evaluate_intent` should return either a signed `ExecutionToken` or a deny result in one call.
- The PDP should not store per-intent state.
- The PDP should validate each `ActionIntent` against the active Policy Knowledge Graph (PKG) snapshot and policy contract.
- AI remains advisory. In the current baseline, judgment runs in the cognitive and coordinator planning stack, but that layer does not authorize execution.
- The accountable agent formulates `ActionIntent`, presents evidence, receives `EvidenceBundle`, and closes the custody loop.

### 2. Updated `ActionIntent` Contract

To reduce replay risk and bind execution to an explicit policy contract, each action intent should include a TTL and contract version.

```jsonc
{
  "intent_id": "string (UUID)",
  "timestamp": "string (ISO-8601)",
  "valid_until": "string (ISO-8601)",
  "principal": {
    "agent_id": "string",
    "role_profile": "string",
    "session_token": "string"
  },
  "action": {
    "type": "enum",
    "options": [
      "PICK",
      "PLACE",
      "SCAN",
      "SEAL",
      "TRANSPORT",
      "RELEASE",
      "LOCK",
      "QUARANTINE"
    ],
    "parameters": "object",
    "security_contract": {
      "hash": "string",
      "version": "string"
    }
  },
  "resource": {
    "asset_id": "string",
    "target_zone": "string",
    "provenance_hash": "string"
  }
}
```

### 3. Enhanced `EvidenceBundle` Telemetry

For playback and black-box forensics, the execution evidence envelope should include:

- `intent_ref`: link to the authorized `ActionIntent`
- `executed_at`: precise ISO-8601 timestamp of physical completion
- `telemetry_snapshot`: multimodal state from vision, sensors, GPS, and zone checks
- `execution_receipt`: cryptographic proof from the actuator or controlled endpoint

The current implementation now also supports a nested `transition_receipt` for HAL-backed actuation. That receipt carries the endpoint identity, hardware UUID, token binding, execution timestamp, and receipt nonce, and is verified before governed custody closure.

This is the minimum evidence needed to explain why a custody transition was proposed, what policy allowed it, who or what executed it, and what state the asset was in at completion.

### 4. Corrected State Transition Flow

```text
Ingress: Event -> AI
Formulation: AI -> AdvisoryPlan -> Agent
Governance: Agent -> ActionIntent -> PDP -> ExecutionToken
Actuation: ExecutionToken -> Robot -> EvidenceBundle
Validation and Closing: EvidenceBundle -> Agent -> Validation -> Custody_Ledger_Updated
```

The accountable agent remains the central actor for closing the custody loop.

### 5. TaskPayload to ActionIntent Mapping

For governed physical execution, the accountable agent derives `ActionIntent` from `TaskPayload` using the following minimum mapping:

- `interaction.assigned_agent_id` is the source for `principal.agent_id`
- `multimodal.location_context` maps to `resource.target_zone`
- the accountable agent injects `action.security_contract.version` from its own `RoleProfile`
- optional `ttl_seconds` hints must be converted into a mandatory absolute `valid_until`

`TaskPayload` remains the judgment envelope. `ActionIntent` remains the authorization contract.

## Runtime Surfaces

SeedCore is organized around five governed surfaces that keep AI useful without allowing unverified release or movement.

### Event Ingress

Telemetry, provenance scans, operator requests, images, voice, and sensor signals enter as governed inputs rather than side channels around the runtime.

### Policy Layer

The policy layer decides what is allowed before the runtime touches inventory, zones, vaults, or controlled endpoints. Role boundaries, release windows, provenance rules, seal status, and lockouts are runtime policy, not prompt hints.

### Execution Routing

SeedCore routes work to the right governed agent based on privilege, capability, and risk. The accountable agent translates approved intent into verified contracts for robotic endpoints, edge systems, or human approvers.

### Playback and Audit

Every custody transition should be replayable from source registration through final release, quarantine, or rollback.

### Exception Recovery

Broken seals, identity mismatches, out-of-zone movement, or missing evidence should route to lock, quarantine, alternate handling, or escalation before loss propagates.

## Repository Upgrade Path

The target architecture can reuse most of the current SeedCore building blocks. The main change is tightening the contracts between them.

| Next-stage contract | Existing components to reuse | Upgrade direction |
| --- | --- | --- |
| Event ingress | `EventizerService`, `OpsGateway` | Normalize telemetry, source claims, and operator input into governed ingress events |
| Advisory planning | Cognitive services, coordinator planning flow | Keep AI advisory and emit a plan or decision input rather than implicit authority |
| Stateless PDP | PKG evaluation path, coordinator policy logic, `src/seedcore/coordinator/core/execute.py` | Tighten policy evaluation around a synchronous `evaluate_intent` boundary that returns `ExecutionToken` or deny without persisting intent state |
| Governed execution | `PlanExecutor`, `OrganismService`, routing layer | Dispatch only tokenized actions to robotic or controlled endpoints |
| Evidence and custody | `FactManagerService`, `StateService`, telemetry stack | Persist `EvidenceBundle`, enable playback, and update custody ledger only after validation |

## Rare Asset and High-Trust Workflows

The runtime is aimed at environments where a mistaken release is materially expensive:

- rare and precious lots with provenance requirements
- enterprise labs and vaults with zone and seal controls
- distributed partner networks that need replayable custody evidence

In these environments, the default action is quarantine, not graceful degradation.

## Recommended Next Steps

The current codebase is already solving the right problems. The next milestone is not inventing a new architecture, but hardening the existing one into an enterprise-grade trust framework.

### Phase 1: Hardening the Boundary (Next 1-2 Months)

Goal: move from software-defined trust to hardware-backed trust.

- move HAL receipt signing out of `.env` and Kubernetes secret delivery into TPM, HSM, or cloud KMS-backed signing
- keep the current short-lived execution token model and expand operator tooling around revocation, E-stop, and observability
- treat Redis-backed revocation as the fast operational control plane, while planning for stronger signer identity guarantees

### Phase 2: Immutable Custody and Auditing (Months 3-4)

Goal: make custody disputes externally auditable.

- anchor `ExecutionReceipt`, `transition_receipt`, and custody-event records into an immutable transparency log or enterprise ledger
- promote `previous_receipt_hash` from a model field into a default end-to-end chained audit trail
- add dual-authorization paths for high-risk actions, such as operator co-sign or independent policy approval

### Phase 3: Dynamic and Distributed Policy (Months 5-6)

Goal: support fleet-wide compliance updates and governed multi-agent operation.

- replace restart-based PKG rollout with hot policy distribution and runtime activation across active services and edge endpoints
- convert high-risk break-glass handling from score thresholds alone into explicit deterministic policy branches
- extend custody receipts beyond Coordinator -> HAL so Agent -> Agent and cognitive handoffs can be traced with the same rigor

## Architecture Overview

SeedCore currently uses:

- **Ray Serve** for service orchestration
- **Ray Actors** for governed agent and execution runtime behavior
- **Postgres / Redis / Neo4j** for state, memory, telemetry, and policy foundations

We use Ray because SeedCore is designed as an execution runtime, not a single-model application. The goal is not to optimize for the smallest possible architecture today, but for the right long-term runtime architecture for governed agent execution. As workflows become more distributed, policy-aware, and model-diverse, the runtime needs a substrate that can coordinate computation, scheduling, stateful actors, and scaling across cloud services, edge deployments, and eventually local inference environments.

Ray fits that direction by giving SeedCore a practical control plane for:

- long-lived accountable actors rather than request-only model calls
- distributed scheduling across heterogeneous runtime environments
- coordination between policy evaluation, execution routing, and stateful workflow steps
- gradual expansion from centralized cloud orchestration toward edge and local inference participation without rebuilding the control plane later

The current repository already contains many of the primitives needed for that target design:

- coordinator services for planning and policy gating
- PKG infrastructure for active policy evaluation
- organism services for execution routing
- ops services for ingress, facts, and state

For deep technical details see:

- *Advanced Architecture*
- *Design Notes*
- *Architecture Migration Summary*
- [Zero-Trust Custody and Digital-Twin Runtime](docs/architecture/overview/zero_trust_custody_digital_twin_runtime.md)
- [Source Registration Architecture](docs/development/source_registration_architecture.md)
- [End-to-End Governance Demo Contract](docs/development/end_to_end_governance_demo_contract.md)
- [Policy Gate Matrix](docs/development/policy_gate_matrix.md)
- [Evidence Bundle Example](docs/development/evidence_bundle_example.json)

## Physical Proof Pilot & Demo Architecture

SeedCore is currently capable of running a 100% verifiable "Digital Twin of Trust" pilot, enabling a single robot or sensor stack to manage a narrow asset workflow (e.g., high-value lab samples or secure hardware storage) with zero manual intervention.

### Core Closed-Loop Flow

```text
Tracking Event -> Policy Decision -> Execution Token -> Edge Actuator -> Signed Evidence Bundle
```

The current repo baseline fully supports the physical custody chain:
- **Governed Ingress:** Multi-modal sensor ingestion via `source-registrations` and `tracking-events`.
- **State Projection:** Projection from append-only tracking events into a live `SourceRegistration` digital twin.
- **Stateless PDP:** Deterministic `ActionIntent` derivation and Policy Decision Point evaluation.
- **Short-Lived Execution Tokens:** Signed `ExecutionToken` issuance on allow paths, currently capped to a short TTL for endpoint use.
- **HAL Bridge (`robot_sim`):** Token expiry, revocation, and emergency-stop checks enforced at the simulator/actuator boundary.
- **Hardware-Attested Execution:** HAL emits transition receipts with Ed25519 signing when configured, with HMAC fallback for local or incomplete setups.
- **Digital Evidence:** Cryptographically signed `EvidenceBundle` construction binds execution receipts and transition receipt hashes for replay, audit, and mathematically undeniable proof.

### Demo Runner
A fully automated serial agent script is available to verify the end-to-end custody loop in a single command. It programmatically triggers the event ingestion, policy gate, and governed physical execution (via `robot_sim`), producing the final evidence artifacts.

```bash
python scripts/host/run_closed_loop_demo.py
```
Outputs are generated in the `demo-output/` folder.

### Key Implementation Boundaries
- `src/seedcore/api/routers/source_registrations_router.py`
- `src/seedcore/ops/source_registration/projector.py`
- `src/seedcore/coordinator/core/governance.py`
- `src/seedcore/hal/drivers/robot_sim_driver.py`
- `src/seedcore/ops/evidence/builder.py`
- `src/seedcore/models/evidence_bundle.py`

---

## Quick Start (Kind + Kubernetes)

### Prerequisites

- Kubernetes tooling: `kubectl`, `kind`, `helm`
- Docker
- `envsubst` available in your shell (`gettext` on macOS)
- 16GB+ RAM, 4+ CPU cores recommended
- macOS or Linux with Docker support

### Full Local Deploy (Recommended)

```bash
git clone https://github.com/NeilLi/seedcore.git
cd seedcore

cp docker/env.example docker/.env

./deploy/deploy-all.sh
```

`deploy/deploy-all.sh` orchestrates the standard local stack in this order:

- builds the SeedCore image unless `--skip-build` is used
- creates or reuses a local `kind` cluster
- deploys PostgreSQL, MySQL, Redis, and Neo4j
- applies database migrations, including source registration and tracking-event tables
- deploys Ray, the SeedCore API, bootstrap jobs, ingress, and the HAL bridge

Useful flags from the deploy script:

- `./deploy/deploy-all.sh --skip-build`
- `./deploy/deploy-all.sh --skip-hal`
- `./deploy/deploy-all.sh --skip-ingress`
- `./deploy/deploy-all.sh --worker-replicas 2`

### Expose Services Locally

After the cluster is up, forward the main services:

```bash
./deploy/port-forward.sh
```

That script forwards the default local ports for:

- SeedCore API: `8002`
- Ray Serve: `8000`
- Ray Dashboard: `8265`
- PostgreSQL: `5432`
- MySQL: `3306`
- Redis: `6379`
- Neo4j: `7474` and `7687`

If you also want local access to the HAL bridge, forward it separately:

```bash
kubectl -n seedcore-dev port-forward svc/seedcore-hal-bridge 8003:8003
```

### Verify Installation

```bash
# API health
curl http://localhost:8002/health
curl http://localhost:8002/readyz

# Ray Serve and dashboard
curl http://localhost:8000/-/healthz
curl http://localhost:8265/api/version

# PKG status
curl http://localhost:8002/api/v1/pkg/status
```

### Demo-Focused Setup Checks

For the governed demo path, these scripts are the fastest sanity checks after deployment:

```bash
python scripts/host/verify_seedcore_architecture.py
bash scripts/host/verify_pdp_boundary.sh
bash scripts/host/seed_source_registration_decision_input.sh
```

---

## Configuration (Key)

```env
PG_DSN=postgresql://postgres:password@postgresql:5432/seedcore
POSTGRES_HOST=postgresql
REDIS_HOST=redis
REDIS_URL=redis://redis:6379/0
NEO4J_HOST=neo4j
RAY_HOST=seedcore-svc-stable-svc
RAY_PORT=10001
RAY_SERVE_URL=http://seedcore-svc-stable-svc:8000
API_PORT=8002
HAL_REQUIRE_EXECUTION_TOKEN=true
SEEDCORE_EXECUTION_TOKEN_TTL_SECONDS=5
SEEDCORE_EXECUTION_TOKEN_CRL_TTL_SECONDS=300
SEEDCORE_HAL_ADMIN_TOKEN=change-me
SEEDCORE_HAL_RECEIPT_PRIVATE_KEY_B64=
SEEDCORE_HAL_RECEIPT_KEY_ID=
SEEDCORE_HAL_RECEIPT_PUBLIC_KEYS_JSON=
SEEDCORE_HAL_RECEIPT_TRUST_EMBEDDED_PUBLIC_KEY=false
```

HAL receipt signing prefers Ed25519:

- set `SEEDCORE_HAL_RECEIPT_PRIVATE_KEY_B64` on the HAL side to sign transition receipts
- publish trusted verification keys with `SEEDCORE_HAL_RECEIPT_PUBLIC_KEYS_JSON`
- only enable `SEEDCORE_HAL_RECEIPT_TRUST_EMBEDDED_PUBLIC_KEY=true` for controlled local setups

Execution token enforcement is now designed for fast expiry and immediate operator intervention:

- `SEEDCORE_EXECUTION_TOKEN_TTL_SECONDS` caps issued token lifetime at the PDP and HAL boundary
- `SEEDCORE_EXECUTION_TOKEN_CRL_TTL_SECONDS` controls how long per-token revocation entries stay in Redis
- `SEEDCORE_HAL_ADMIN_TOKEN` protects HAL admin revocation and emergency-stop endpoints when set

---

## Monitoring

- Ray Dashboard: `localhost:8265`
- Logs:

```bash
kubectl logs -l app=seedcore-api -n seedcore-dev -f
```

---

## API Summary

### SeedCore API (`http://localhost:8002`)

Core health and root endpoints:

- `GET /`
- `GET /health`
- `GET /readyz`

Versioned governed API surface under `/api/v1`:

- `Tasks`
  - `POST /api/v1/tasks`
  - `GET /api/v1/tasks`
  - `GET /api/v1/tasks/{task_id}`
  - `GET /api/v1/tasks/{task_id}/governance`
  - `POST /api/v1/tasks/{task_id}/cancel`
  - `GET /api/v1/tasks/{task_id}/logs`
- `Source Registrations`
  - `POST /api/v1/source-registrations`
  - `GET /api/v1/source-registrations/{registration_id}`
  - `POST /api/v1/source-registrations/{registration_id}/artifacts`
  - `POST /api/v1/source-registrations/{registration_id}/submit`
  - `GET /api/v1/source-registrations/{registration_id}/verdict`
- `Tracking Events`
  - `POST /api/v1/tracking-events`
  - `GET /api/v1/tracking-events`
  - `GET /api/v1/tracking-events/{event_id}`
  - `GET /api/v1/source-registrations/{registration_id}/tracking-events`
- `Control`
  - `GET /api/v1/facts`
  - `GET /api/v1/facts/{fact_id}`
  - `POST /api/v1/facts`
  - `PATCH /api/v1/facts/{fact_id}`
  - `DELETE /api/v1/facts/{fact_id}`
- `Advisory`
  - `POST /api/v1/advisory`
- `PKG`
  - `GET /api/v1/pkg/status`
  - `POST /api/v1/pkg/reload`
  - `POST /api/v1/pkg/evaluate_async`
  - `POST /api/v1/pkg/snapshots/compare`
  - `POST /api/v1/pkg/snapshots/{snapshot_id}/compile-rules`
- `Capabilities`
  - `POST /api/v1/capabilities/register`

### HAL Bridge (`http://localhost:8003`)

The HAL bridge is deployed separately from the main API and exposes the controlled actuator surface:

- `GET /status`
- `GET /state`
- `POST /actuate`
- `POST /forensic-seal`
- `POST /admin/execution-tokens/revoke`
- `POST /admin/execution-tokens/e-stop`
- `DELETE /admin/execution-tokens/e-stop`

`/actuate` now accepts an `execution_token` payload for governed execution. On HAL-backed paths, successful actuation responses can include a `transition_receipt`, and the bridge rejects tokens that are expired, exceed the configured maximum TTL, or have been revoked through Redis-backed control state.

### Ray Serve and Dashboard

- Ray Serve base URL: `http://localhost:8000`
- Ray Dashboard: `http://localhost:8265`

---

## ✅ Unit Tests (CI)

The unit-test workflow is configured for manual runs only (no automatic push/PR triggers).

- Workflow file: `.github/workflows/unit-tests.yml`
- Local run:

```bash
pytest -q
```

---

## 🤝 Contributing

1. Fork the repo
2. Create a feature branch
3. Test via Kubernetes deployment
4. Submit a PR

---

## 📄 License

See `LICENSE`.

---

## 🆘 Support

- See `docs/`
- Review `deploy/`
- Open a GitHub issue
