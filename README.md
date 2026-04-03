# SeedCore
CI is active for `push` to `main`, `pull_request`, and manual dispatch
(`.github/workflows/unit-tests.yml`).

## Zero-Trust Runtime for High-Consequence AI Actions

AI agents are becoming operational, but governance has not kept pace. Enterprises are under pressure to automate, yet they still need reliable ways to control what high-consequence AI actions are allowed to do, prove why an action was permitted, and contain failures before they become liabilities.

SeedCore is a deterministic, zero-trust runtime for high-consequence AI actions. It evaluates governed requests in real time through a synchronous, stateless-at-decision-time Policy Decision Point (PDP) over a pinned PKG snapshot and bounded request context; advisory AI can propose, but governance issues a short-lived `ExecutionToken` only when the decision is `allow`.

All outcomes (`allow` / `deny` / `quarantine` / `escalate`) are recorded with replayable, auditable evidence. SeedCore is not another model layer; it is the runtime that makes high-consequence AI action safe enough to execute.

Decision record: [ADR 0001 - Keep the PDP Stateless and Synchronous at Decision Time](docs/architecture/adr/adr-0001-pdp-hot-path.md).

## 2026 Product Focus

For the current execution phase, SeedCore is intentionally constrained to one
must-win product workflow:

- **Agent-Governed Restricted Custody Transfer**

This is now the repository's clearest milestone and roadmap anchor: Slice 1
live sign-off for the canonical Restricted Custody Transfer wedge was closed on
**March 30, 2026**, and Q2 **Window A host-first closure** completed on
**April 2, 2026**. PKG–RCT **contract alignment** through Phase 4 is in the tree:
activation hardening, publish-time validation, explicit **triple-hash** binding
(policy bundle + decision graph + state) on receipts, and opt-in **strict replay**
that rejects policy-only verification when signed artifacts omit those binds (see
[pkg snapshot / RCT alignment](docs/development/pkg_snapshot_rct_alignment_research.md)).

For the live roadmap and closure details, see:

- [current next steps](docs/development/current_next_steps.md)
- [2026 execution plan](docs/development/seedcore_2026_execution_plan.md)
- [Q2 product spec](docs/development/q2_2026_audit_trail_ui_spec.md)

That means the near-term product boundary is:

- external agent request
- governed runtime decision (`allow` / `deny` / `quarantine` / `escalate`)
- transaction-specific execution authority
- device- and scope-bound accountability
- replayable evidence and verification surface
- forensic-block and replay linkage

This keeps the work focused on the layer SeedCore can uniquely own:
governed admissibility and proof, not generalized model intelligence.

Supporting documents:

- [current next steps](docs/development/current_next_steps.md)
- [2026 execution plan](docs/development/seedcore_2026_execution_plan.md)
- [positioning narrative](docs/development/seedcore_positioning_narrative.md)
- [agent action gateway contract (v1 draft)](docs/development/agent_action_gateway_contract.md)

## Current Codebase Snapshot

Based on the current repository state, SeedCore is already organized around the three trust problems that most agent systems leave unresolved:

1. **Verifiable authority boundary**
2. **Policy enforcement layer**
3. **Trusted chain of custody**

Recent changes reinforced that direction in two concrete areas:

1. **HAL transition attestation and receipt verification**
2. **Execution token TTL, revocation, and emergency stop controls**

Implemented in this repo (high-level):

- Trust-critical receipt signing routed through TPM/KMS/Ed25519/HMAC paths based on policy and environment.
- Short-lived `ExecutionToken` authority with TTL enforcement, revocation, and an operator-triggered emergency cutoff at the HAL boundary.
- Replay-verifiable evidence bundles plus offline verification via the `seedcore-verify` kernel/CLI.
- Q2 verification surface (operator console + verification API) under `/api/v1/verification/*`.
- Hot-path observability under `/api/v1/pdp/hot-path/status` plus Prometheus text at `/api/v1/pdp/hot-path/metrics`.
- PKG RCT contract surfaces: snapshot manifests and contract artifacts; **opt-in** activation hardening (`SEEDCORE_PKG_RCT_ACTIVATION_ENFORCE`, `SEEDCORE_PKG_RCT_ACTIVATION_PREFLIGHT`), **opt-in** publish validation before snapshot activate (`SEEDCORE_PKG_RCT_PUBLISH_VALIDATE`), and **opt-in** strict replay verification (`SEEDCORE_RCT_REPLAY_STRICT_TRIPLE_HASH`) with host helper `scripts/host/verify_rct_replay_strict.py`.

Restricted-custody trust hardening supports explicit `trust_proof` material, enabling offline verification against artifacts and a trust bundle (TPM fixture path included).

## Trust Challenges

### 1. Verifiable Authority Boundary

SeedCore already has a concrete authority artifact: `ExecutionToken`.

Current implementation:

- the coordinator derives `ActionIntent` and issues signed `ExecutionToken` objects
- HAL validates token signature, expiry, and endpoint constraints before actuation
- HAL transition receipts can prove which endpoint executed a governed action
- the robot-sim and HAL boundary now reject revoked tokens and emergency-stopped token populations

Operational notes:

- Local modes may use software-backed signing; production trust anchors are selected via signer/provenance policy and environment.
- Fleet-scale TPM rollout, device provisioning, and production operating drills are documented in [TPM Fleet Rollout Runbook](docs/development/tpm_fleet_rollout_runbook.md).

### 2. Policy Enforcement Layer

SeedCore already has a real policy layer instead of prompt-only guardrails.

Current implementation:

- PKG evaluation runs through the `ops/pkg` stack with OPA WASM support
- coordinator execution follows a PKG-first flow and enforces a PKG-mandatory gate for action tasks
- routing hints are extracted from PKG proto-plans rather than trusted from cognitive output alone
- policy snapshots can be reloaded manually through the existing PKG management path
- policy snapshots can be hot-activated fleet-wide through `POST /api/v1/pkg/snapshots/{snapshot_version}/activate` (optional publish-time RCT checks when `SEEDCORE_PKG_RCT_PUBLISH_VALIDATE` is set)
- edge policy consumers can resolve desired versions through `POST /api/v1/pkg/ota/heartbeat` and subscribe to `GET /api/v1/pkg/ota/stream`
- compiled authz graph can be **dry-run compiled** for publish gates without swapping the active graph (`AuthzGraphManager.compile_snapshot_index`)

### 3. Trusted Chain of Custody

SeedCore already has the beginnings of a governed custody ledger.

Current implementation:

- evidence bundles include `intent_ref`, execution timing, telemetry, and execution receipts; policy receipts and bundles can carry **`policy_snapshot_hash`**, **`decision_graph_snapshot_hash`**, and **`state_binding_hash`** for replay-grade binding
- HAL-backed transitions can carry signed `transition_receipt` payloads with nonce-based replay detection
- governed closure persists receipt hash, nonce, transition sequence, endpoint identity, and authority source
- forensic sealing captures a pre-contact evidence structure for edge-side custody events, with hardened-mode support for trust-anchor-backed `hal_capture` signing on attested endpoints

Operational model:

- Custody closure persists receipt hashes, nonces, transition sequence, endpoint identity, and authority source; replay-visible mismatch outcomes are surfaced for quarantine/rollback investigation.
- Optional external transparency anchoring is supported for selected high-value receipts; always-on anchoring policy is documented in later rollout runbooks.

**Execution boundary**

```text
AI Judgment -> Agent Accountability -> Zero-Trust Policy -> Robotic Embodiment -> Immutable Custody
```

## What SeedCore Is

SeedCore is not a chatbot wrapper or a generic tool-calling layer. It is a governed runtime that converts advisory AI output into policy-checked execution.

In the current repository baseline, **AI judgment** lives in the cognitive and coordinator planning stack. That layer can interpret, enrich, and route work, but it does not authorize high-stakes execution.

The current baseline provides:

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
- **Researchers / Architects**: read *Target Architecture*, [Design Notes](docs/design-notes.md), and [Architecture Overview](docs/architecture/overview/architecture.md)

## Why SeedCore Exists

Most AI systems are built to generate text, images, or recommendations. Physical operations need a harder contract:

- actions must be authorized before execution
- agents must be accountable for every controlled handoff
- actuators must behave as policy subjects, not autonomous peers
- provenance and custody evidence must survive failures and disputes
- exception paths must default to quarantine rather than graceful drift into execution

SeedCore fills that gap by keeping AI advisory and moving execution authority into explicit runtime policy.

The "North Star" for SeedCore is the creation of a **Genuine Environment for Autonomous Trade**—a zero-trust, autonomous runtime where physical actions are instantly converted into irrefutable digital truths. This allows AI agents and robots to transact on behalf of humans with absolute certainty, governed by four technical pillars:

1.  **Persistent Twin & Settlement Track:** Append-only history and strict versioning for digital twins.
2.  **Physical-to-Digital Delivery (The Evidence Loop):** Cryptographically sealed evidence chains (ActionIntent -> ExecutionToken -> EvidenceBundle).
3.  **Autonomous Verification:** Machine-to-machine trust using the Rust `seedcore-verify` kernel to validate replay chains without human intervention.
4.  **Delegated Authority:** DID-style delegation and multi-party governance for high-value trades.

For a detailed breakdown of this vision, see the [North Star: Autonomous Trade Environment](docs/development/north_star_autonomous_trade_environment.md).

## Target Architecture

The target direction for SeedCore is a zero-trust custody runtime built around one strict principle:

> The model can propose. The Agent is accountable. The PDP decides. The robot executes. The evidence closes the loop.

This direction depends on five core contracts.

### 1. Actor Authority and the PDP Decision Boundary

- The **Policy Decision Point (PDP)** remains stateless at decision time and synchronous for final authorization.
- `evaluate_intent` should return either a signed `ExecutionToken` or a deny result in one call.
- The PDP does not persist per-intent mutable state in the decision function.
- The PDP validates each `ActionIntent` against an active PKG snapshot and policy contract.
- Stateful supporting systems assemble and persist surrounding context: approvals, custody/telemetry summaries, snapshot rollout state, and governed receipts.
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

This is the minimum evidence needed to explain why a custody transition was proposed, what policy allowed it, who or what executed it, and what state the physical good was in at completion.

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
| Stateless PDP at decision time | PKG evaluation path, coordinator policy logic, `src/seedcore/coordinator/core/execute.py` | Keep a synchronous `evaluate_intent` boundary that returns `ExecutionToken` or deny while surrounding systems handle snapshot/context assembly and replay persistence |
| Governed execution | `PlanExecutor`, `OrganismService`, routing layer | Dispatch only tokenized actions to robotic or controlled endpoints |
| Evidence and custody | `FactManagerService`, `StateService`, telemetry stack | Persist `EvidenceBundle`, enable playback, and update custody ledger only after validation |

## Rare Asset and High-Trust Workflows

The runtime is aimed at environments where a mistaken release is materially expensive:

- rare and precious lots with provenance requirements
- enterprise labs and vaults with zone and seal controls
- distributed partner networks that need replayable custody evidence

In these environments, the default action is quarantine, not graceful degradation.

## Recommended Next Steps

The detailed next-step plan now lives in [docs/development/current_next_steps.md](/Users/ningli/project/seedcore/docs/development/current_next_steps.md).

That document is the better source of truth because the implementation and
verification state is moving faster than the architecture overview in this root
README.

The recommended language-boundary evolution for that next stage lives in
[docs/development/language_evolution_map.md](/Users/ningli/project/seedcore/docs/development/language_evolution_map.md).

The concrete Rust workspace proposal for that same track lives in
[docs/development/rust_workspace_proposal.md](/Users/ningli/project/seedcore/docs/development/rust_workspace_proposal.md).

In short, the highest-priority remaining work is:

- hardware-backed signer and device-trust hardening
- transaction-specific authority scope for Restricted Custody Transfer
- forensic-block and replay-chain promotion across runtime surfaces
- dual-authorization and rollout/activation hardening across runtime surfaces
- first red-team validation via MITM coordinate redirect on the canonical wedge

For the 2026 productized execution sequence, use:

- [SeedCore 2026 Execution Plan](docs/development/seedcore_2026_execution_plan.md)
- [Agent Action Gateway Contract](docs/development/agent_action_gateway_contract.md)
- [Hot-Path Shadow To Enforce Breakdown](docs/development/hot_path_shadow_to_enforce_breakdown.md)

## Architecture Overview

SeedCore currently uses:

- **Ray Serve** for service orchestration
- **Ray Actors** for governed agent and execution runtime behavior
- **Postgres / Redis / Neo4j** for state, memory, telemetry, and policy foundations

Operational role by substrate:

| Substrate | Operational role |
| --- | --- |
| Confluent Kafka | Event backbone for intent, telemetry, and policy outcome streams |
| Ray + Kubernetes | Distributed execution for compiled authz graph and shard-aware hot-path routing |
| Redis | Token revocation and emergency cutoff propagation |
| Cloud KMS | Hardware-backed signing for policy and transition artifacts |
| Durable forensic store | Long-lived persistence for signed forensic blocks and replay evidence |

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

- [Architecture Overview](docs/architecture/overview/architecture.md)
- [Design Notes](docs/design-notes.md)
- [Zero-Trust Custody and Digital-Twin Runtime](docs/architecture/overview/zero_trust_custody_digital_twin_runtime.md)
- [Source Registration Architecture](docs/development/source_registration_architecture.md)
- [End-to-End Governance Demo Contract](docs/development/end_to_end_governance_demo_contract.md)
- [Policy Gate Matrix](docs/development/policy_gate_matrix.md)
- [Evidence Bundle Example](docs/development/evidence_bundle_example.json)

## Physical Proof Pilot & Demo Architecture

SeedCore is currently capable of running a 100% verifiable "Digital Twin of Trust" pilot, enabling a single robot or sensor stack to manage a narrow physical-goods workflow (e.g., high-value lab samples or secure hardware storage) with zero manual intervention.

The next-step pilot direction is narrower and stronger:

- keep the demo centered on **Restricted Custody Transfer**
- treat the flow as a **Forensic Handshake** from request -> decision -> scoped
  execution -> forensic closure
- use the first red-team drill, **MITM coordinate redirect**, to prove that
  scope mismatch becomes `deny` or `quarantine` rather than silent drift

### Core Closed-Loop Flow

```text
Tracking Event -> Policy Decision -> Execution Token -> Edge Actuator -> Signed Evidence Bundle
```

The current repo baseline fully supports the physical custody chain:
- **Governed Ingress:** Multi-modal sensor ingestion via `source-registrations` and `tracking-events`.
- **State Projection:** Projection from append-only tracking events into a live `SourceRegistration` digital twin.
- **Stateless-at-decision-time PDP:** Deterministic `ActionIntent` derivation and synchronous final authorization over pinned snapshot + bounded context.
- **Short-Lived Execution Tokens:** Signed `ExecutionToken` issuance on allow paths, currently capped to a short TTL for endpoint use.
- **HAL Bridge (`robot_sim`):** Token expiry, revocation, and emergency-stop checks enforced at the simulator/actuator boundary.
- **Hardware-Attested Execution:** restricted-custody and hardened attested HAL paths use trust-anchor-backed `ecdsa_p256_sha256`; non-restricted development paths can still use Ed25519/HMAC software modes unless hardened mode is enabled.
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

## Quick Start

### Host-Mode Local Runtime (Recommended For Day-To-Day Development)

For local macOS or laptop development, use the host-mode helpers under [deploy/local/README.md](/Users/ningli/project/seedcore/deploy/local/README.md). They avoid the full Kind/Kubernetes footprint and are the best path for routine runtime bring-up and verification.

Typical startup sequence:

```bash
brew services start postgresql@17
brew services start redis
PGUSER=$(whoami) bash deploy/local/init-full-db-direct.sh
bash deploy/local/run-api.sh
bash deploy/local/run-hal.sh
bash deploy/local/run-task-stack.sh start
```

Core local endpoints:

- API: `http://127.0.0.1:8002`
- HAL: `http://127.0.0.1:8003`
- Serve apps: `http://127.0.0.1:8000`

Focused RFC-phase verification:

```bash
bash scripts/host/verify_authz_graph_rfc_phases.sh
```

This verifier currently checks the staged authz-graph rollout through:

- Phase 0: baseline hardening
- Phase 1: decision-centric ontology and release/provenance wedge
- Phase 2: multihop authority traversal
- Phase 3: first-class constraints and explanation payloads
- Phase 4: decision-graph vs enrichment-graph split
- Phase 5: shard-aware Ray authz cache routing

Current focused suite result:

- `51 passed`

### Gemini CLI Extension

SeedCore now includes a Gemini CLI extension scaffold that exposes the read-only
`seedcore.*` MCP tools from this repository.

This path assumes:

- you run Gemini from an activated Python environment that can import
  `seedcore`
- the Python `mcp` dependency is installed in that same environment
- the local SeedCore runtime is started separately

Install the extension from a local checkout:

```bash
gemini extensions install .
```

Or install it from GitHub:

```bash
gemini extensions install https://github.com/NeilLi/seedcore
```

Verify that Gemini sees the extension:

```bash
/extensions list
```

The extension launches the checked-in MCP server entrypoint at
[`scripts/gemini/run_seedcore_mcp.py`](/Users/ningli/project/seedcore/scripts/gemini/run_seedcore_mcp.py)
and should make these tools available in Gemini:

- `seedcore.health`
- `seedcore.readyz`
- `seedcore.pkg.status`
- `seedcore.pkg.authz_graph_status`
- `seedcore.hotpath.status`
- `seedcore.hotpath.metrics`
- `seedcore.hotpath.verify_shadow`
- `seedcore.hotpath.benchmark`
- `seedcore.verification.queue`
- `seedcore.verification.transfer_review`
- `seedcore.verification.workflow_projection`
- `seedcore.verification.workflow_verification_detail`
- `seedcore.verification.workflow_replay`
- `seedcore.verification.runbook_lookup`
- `seedcore.evidence.verify`

The extension does not start SeedCore for you. Bring up the runtime first using
the host-mode steps above or the full guide in
[deploy/local/README.md](/Users/ningli/project/seedcore/deploy/local/README.md).

Useful checks after runtime bring-up:

```bash
curl http://127.0.0.1:8002/health
curl http://127.0.0.1:8002/readyz
```

If Gemini installs the extension but the `seedcore.*` tools do not appear or
fail immediately, see:

- [GEMINI.md](/Users/ningli/project/seedcore/GEMINI.md)
- [gemini-tools.md](/Users/ningli/project/seedcore/skills/using-seedcore/references/gemini-tools.md)
- [gemini-troubleshooting.md](/Users/ningli/project/seedcore/skills/using-seedcore/references/gemini-troubleshooting.md)

### Rust + TypeScript Proof Surface Quick Check

Run the Rust kernel test baseline:

```bash
cargo test --workspace --manifest-path rust/Cargo.toml
```

Build and run the Rust verifier summary path:

```bash
cargo build -p seedcore-verify --manifest-path rust/Cargo.toml
rust/target/debug/seedcore-verify summarize-transfer --dir rust/fixtures/transfers/allow_case
```

Typecheck and build the TypeScript trust surface workspace:

```bash
npm --prefix ts install
npm --prefix ts run typecheck
npm --prefix ts run build
```

Run the TS verification API and proof surface locally:

```bash
npm --prefix ts run serve:verification-api
```

```bash
npm --prefix ts run serve:proof-surface
```

Proof pages:

- `http://127.0.0.1:7072/transfer?dir=rust/fixtures/transfers/allow_case`
- `http://127.0.0.1:7072/asset?dir=rust/fixtures/transfers/allow_case`

### Kind + Kubernetes

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
curl http://localhost:8002/api/v1/pkg/authz-graph/status

# Hot activate a snapshot (fleet-wide)
curl -X POST http://localhost:8002/api/v1/pkg/snapshots/rules@8.0.0/activate \
  -H "Content-Type: application/json" \
  -d '{"actor":"ops","reason":"rollout","target":"router","region":"global","publish_update":true}'

# Edge heartbeat + desired policy resolution
curl -X POST http://localhost:8002/api/v1/pkg/ota/heartbeat \
  -H "Content-Type: application/json" \
  -d '{"device_id":"edge-1","device_type":"door","region":"global","snapshot_id":7,"version":"rules@7.0.0"}'
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
SEEDCORE_HARDENED_RESTRICTED_CUSTODY_MODE=false
SEEDCORE_SIGNER_PROVIDER_RECEIPT=
SEEDCORE_SIGNER_PROVIDER_EXECUTION=
SEEDCORE_RECEIPT_REQUIRED_TRUST_ANCHOR=tpm2
SEEDCORE_HAL_CAPTURE_REQUIRED_TRUST_ANCHOR=
SEEDCORE_TPM2_REQUIRE_HARDWARE=true
SEEDCORE_TPM2_ALLOW_SOFTWARE_FALLBACK=false
SEEDCORE_TPM2_KEY_ID=
SEEDCORE_TPM2_PERSISTENT_HANDLE=
SEEDCORE_TPM2_PUBLIC_KEY_B64=
SEEDCORE_PDP_USE_ACTIVE_AUTHZ_GRAPH=false
SEEDCORE_PDP_BREAK_GLASS_REQUIRE_DETERMINISTIC_PROCEDURE=true
SEEDCORE_PDP_BREAK_GLASS_HIGH_RISK_SCORE=0.85
SEEDCORE_PDP_BREAK_GLASS_OCPS_THRESHOLD=0.70
SEEDCORE_PDP_BREAK_GLASS_REASON_CODES=safety_incident,custody_breach,service_continuity,regulatory_hold
SEEDCORE_HAL_ADMIN_TOKEN=change-me
SEEDCORE_EVIDENCE_ED25519_PRIVATE_KEY_B64=
SEEDCORE_EVIDENCE_ED25519_KEY_ID=
SEEDCORE_HAL_RECEIPT_PUBLIC_KEYS_JSON=
SEEDCORE_HAL_RECEIPT_TRUST_EMBEDDED_PUBLIC_KEY=false
SEEDCORE_VERIFY_BIN=/usr/local/bin/seedcore-verify
```

HAL signing posture:

- restricted-custody and hardened attested HAL paths should use `ecdsa_p256_sha256` with `SEEDCORE_SIGNER_PROVIDER_RECEIPT` / `SEEDCORE_SIGNER_PROVIDER_EXECUTION` and `SEEDCORE_RECEIPT_REQUIRED_TRUST_ANCHOR`
- enable `SEEDCORE_HARDENED_RESTRICTED_CUSTODY_MODE=true` to force attested `transition_receipt` and `hal_capture` signing away from software fallback modes
- for strict physical TPM posture keep `SEEDCORE_TPM2_REQUIRE_HARDWARE=true` and `SEEDCORE_TPM2_ALLOW_SOFTWARE_FALLBACK=false`
- software-backed Ed25519 mode remains available for non-restricted development via `SEEDCORE_EVIDENCE_ED25519_PRIVATE_KEY_B64`
- publish trusted verification keys with `SEEDCORE_HAL_RECEIPT_PUBLIC_KEYS_JSON`; only enable `SEEDCORE_HAL_RECEIPT_TRUST_EMBEDDED_PUBLIC_KEY=true` in controlled local setups
- use [TPM Fleet Rollout Runbook](docs/development/tpm_fleet_rollout_runbook.md) for provisioning/drill requirements before production claims

Execution token enforcement is now designed for fast expiry and immediate operator intervention:

- `SEEDCORE_EXECUTION_TOKEN_TTL_SECONDS` caps issued token lifetime at the PDP and HAL boundary
- `SEEDCORE_EXECUTION_TOKEN_CRL_TTL_SECONDS` controls how long per-token revocation entries stay in Redis
- `SEEDCORE_PDP_USE_ACTIVE_AUTHZ_GRAPH` enables automatic PDP use of the active compiled authorization graph from the PKG manager
- `SEEDCORE_HAL_ADMIN_TOKEN` protects HAL admin revocation and emergency-stop endpoints when set

High-risk break-glass hardening (deterministic procedure mode):

- `SEEDCORE_PDP_BREAK_GLASS_REQUIRE_DETERMINISTIC_PROCEDURE=true` enforces deterministic claims on high-risk break-glass attempts
- `SEEDCORE_PDP_BREAK_GLASS_HIGH_RISK_SCORE` defines the cognitive/twin risk threshold for strict procedure enforcement
- `SEEDCORE_PDP_BREAK_GLASS_OCPS_THRESHOLD` defines the OCPS drift threshold for strict procedure enforcement
- `SEEDCORE_PDP_BREAK_GLASS_REASON_CODES` defines the allowed `reason_code` set for high-risk break-glass tokens

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
- `Agent Actions`
  - `POST /api/v1/agent-actions/evaluate`
  - `GET /api/v1/agent-actions/requests/{request_id}`
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
  - `GET /api/v1/pkg/authz-graph/status`
  - `POST /api/v1/pkg/reload`
  - `POST /api/v1/pkg/snapshots/{snapshot_version}/activate`
  - `POST /api/v1/pkg/authz-graph/refresh`
  - `POST /api/v1/pkg/ota/heartbeat`
  - `GET /api/v1/pkg/ota/stream`
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

### TypeScript Verification Surface (Optional Local Services)

- Verification API: `http://127.0.0.1:7071`
  - `GET /health`
  - `GET /api/v1/transfers/summary?dir=...`
  - `GET /api/v1/transfers/proof?dir=...`
  - `GET /api/v1/assets/proof?dir=...`
- Proof surface: `http://127.0.0.1:7072`
  - `GET /`
  - `GET /transfer?dir=...`
  - `GET /asset?dir=...`

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
