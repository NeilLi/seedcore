# SeedCore

[![Unit Tests](https://github.com/NeilLi/seedcore/actions/workflows/unit-tests.yml/badge.svg)](https://github.com/NeilLi/seedcore/actions/workflows/unit-tests.yml)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

## Governed Execution and Trust Runtime for Autonomous Systems

Agent frameworks decide **what to do**. Prompt guardrails control **what is said**. SeedCore controls **what is allowed to execute**.

SeedCore is a zero-trust execution and proof runtime for high-consequence autonomous workflows. It sits between advisory AI intent and real-world execution, then checks identity, delegation, policy scope, asset state, hardware or custody boundaries, and evidence requirements before execution authority can exist.

Unlike a model guardrail, tool-calling wrapper, or heuristic security detector, SeedCore is a deterministic execution gate:

- rejects ambient or implicit authority
- mints short-lived, scoped `ExecutionToken`s only after policy admits an `ActionIntent`
- preserves signed receipts, transition evidence, and replayable bundles for post-hoc verification

The core principle is simple:

```text
AI intent should not automatically become execution authority.
The model can propose. The Agent is accountable. The PDP decides.
The actuator executes. The evidence closes the loop.
```

## Current Status

SeedCore already has an implemented and contract-tested baseline for the trust-runtime slice: Agent Action Gateway v1, `ExecutionToken` lifecycle, stateless PDP evaluation, evidence bundles, replay verification, Rust proof-kernel paths, and a coordinator-embedded `RESULT_VERIFIER` for Restricted Custody Transfer (RCT) enforcement.

The current product focus is narrower and deliberately commercial: package that baseline into an **Agent-Governed Restricted Custody Transfer** workflow, with a collectible rare-shoe custody handoff as the first legible vertical scene.

Important boundaries:

- The rare-shoe scene is an active verticalization of the existing RCT runtime, not a sneaker marketplace.
- SeedCore proves governed custody movement and evidence integrity; it does not assert legal ownership transfer in v0.
- Host-mode local runtime verification is green end-to-end for the RCT wedge: the Agent Action Gateway can generate a replayable runtime audit row, the verification API can read queue/detail/replay/runbook views from it, and the productized verification surface protocol passes locally.
- Remote Kind/Kubernetes hot-path validation is green for API, Ray, HAL, ingress, Redis resilience, and hot-path observability. Full live verification-surface signoff in that topology still depends on capturing runtime audit rows there.

Read the current execution docs:

- [Development docs index](docs/development/README.md)
- [Current next steps](docs/development/current_next_steps.md)
- [2026 execution plan](docs/development/seedcore_2026_execution_plan.md)
- [Kube topology validation Q2 signoff](docs/development/kube_topology_validation_q2_signoff.md)
- [Rare-shoe RCT demo spec](docs/development/rare_shoes_collecting_transfer_demo_spec.md)

## Trust Runtime, Not Traditional Cybersecurity

SeedCore uses zero-trust language, but it is not primarily a perimeter-defense product. Traditional cybersecurity protects environments by detecting threats, hardening boundaries, or blocking suspicious behavior. SeedCore governs execution **inside** an environment: it decides whether a proposed action is admissible, issues bounded authority when policy allows it, and produces proof explaining what happened afterward.

```text
Cybersecurity protects the environment.
SeedCore governs execution within it.
```

| Feature | Traditional cybersecurity | SeedCore Trust Runtime |
| --- | --- | --- |
| Primary goal | Detect threats, reduce attack success, harden perimeters | Govern admissible action and produce replayable proof |
| Primary question | "Is this malicious or suspicious?" | "Is this action admissible under policy and authority?" |
| Decision core | Heuristic, anomaly-based, or signature-driven | Synchronous, stateless Policy Decision Point (PDP) |
| Runtime output | Alerts, blocks, detections, logs | Signed tokens, transition receipts, forensic bundles |
| Success metric | Breaches prevented or detected | Cryptographic verifiability and replayability of state transitions |

For the canonical category framing, see [Trust Runtime Category Distinction](docs/development/trust_runtime_category_distinction.md).

## Commercial Wedge: Restricted Custody Transfer

The must-win product wedge is **Agent-Governed Restricted Custody Transfer (RCT)**: a governed path where digital transaction identity is bound to physical custody, scope, and evidence before SeedCore issues execution authority.

The current commerce-shaped integration maps Shopify-Sandbox-style fields into the gateway and proof surface:

```text
product_ref + order_ref + quote_ref + declared_value_usd + economic_hash
```

The first commercial scene is **Collectible Rare-Shoe Custody Handoff**. Rare shoes make the trust failures obvious: counterfeit risk, stale authentication, swapped assets, condition drift, replay attacks, and opaque custody. The same proof pattern is relevant to luxury logistics, regulated parts, lab samples, robotics handoff, and other high-value physical workflows.

```text
Seller / consignor
  -> Authenticator signs provenance, condition, and NFC/scan evidence
  -> Buyer or buyer agent expresses intent
  -> SeedCore PDP evaluates authority, policy, scope, and evidence
  -> Courier or edge operator receives bounded execution authority
  -> RESULT_VERIFIER replays the chain and closes or quarantines the case
```

Commercial actors stay explicit:

- **Seller / consignor** submits the physical asset for registration and sale.
- **Authenticator** provides authentication, condition grade, and evidence refs.
- **Marketplace / listing partner** provides `product_ref`, `quote_ref`, `order_ref`, and value context.
- **Buyer and buyer agent** express commercial intent, but cannot authorize custody alone.
- **Courier / edge operator** executes only inside scoped, time-bounded authority.
- **Verifier** replays the evidence chain and surfaces verified, rejected, review, or quarantine outcomes.

## Implemented Runtime Capabilities

SeedCore's current baseline includes the technical primitives needed for governed execution:

- **Stateless PDP and compiled authz graph**: deterministic evaluation of `ActionIntent` against policy, OPA/WASM support, and ReBAC graph paths.
- **Short-lived `ExecutionToken`s**: bounded capability artifacts with TTL, frozen constraints, execution preconditions, Redis CRL revocation, and local development fallbacks.
- **Coordinator-embedded `RESULT_VERIFIER`**: a background runtime that polls `digital_twin_event_journal`, persists verifier jobs and outcomes, reuses the replay path, calls the Rust proof kernel, and fail-closes RCT state on terminal mismatch.
- **Replayable evidence bundles**: policy receipts, execution tokens, transition receipts, telemetry refs, and source-preserving replay bundles for independent verification.
- **Hardware-anchored telemetry path**: signed transition receipts and telemetry envelopes, with TPM/KMS-backed signing posture for attested deployments and software-backed signing for local development.
- **Operator-readable verification surface**: versioned `/api/v1/verification/*` endpoints plus TypeScript UI surfaces for queue, audit trail, asset forensics, replay, and runbook lookup.

Key architecture references:

- [Architecture overview](docs/architecture/overview/architecture.md)
- [Agent Action Gateway contract](docs/development/agent_action_gateway_contract.md)
- [Agentic delegation control plane](docs/development/agentic_delegation_control_plane.md)
- [ExecutionToken lifecycle management](docs/development/execution_token_lifecycle_management.md)
- [Policy gate matrix](docs/development/policy_gate_matrix.md)
- [Hardware-anchored telemetry MVP contract](docs/development/hardware_anchored_telemetry_mvp_contract.md)
- [ADR 0004: Coordinator-Embedded RESULT_VERIFIER](docs/architecture/adr/adr-0004-result-verifier-runtime.md)
- [ADR 0005: Replayable Evidence for Governed State Transitions](docs/architecture/adr/adr-0005-replayable-evidence-governed-state-transitions.md)

## Operator Verification Console

SeedCore exposes a four-screen TypeScript operator surface backed by the verification API. The goal is to make cryptographic and policy outcomes legible without weakening the proof boundary.

| Screen | Purpose | Backing surface |
| --- | --- | --- |
| Screen 1: Anomaly-first queue | Filter by status and prefixes such as `envelope:`, `approval:`, and `request:` | `/api/v1/verification/transfers/queue`, operator `/queue` |
| Screen 2: Side-by-side audit trail | Compare transaction request, PDP authority, and physical closure | `/api/v1/verification/transfers/review` and audit-trail endpoints |
| Screen 3: Asset forensics | Inspect custody state, telemetry refs, signer provenance, and transition receipts | `/api/v1/verification/assets/forensics` |
| Screen 4: Replay and verification | Show replay detail, failure reasons, and runbook lookup links | `/api/v1/verification/workflows/{workflow_id}/verification-detail`, `/replay`, `/runbook/lookup` |

The operator console also provides a deterministic legibility layer: case verdicts, trust-gap counts, missing prerequisites, and runbook links derived from structured verification payloads.

## Architecture at a Glance

SeedCore is designed as a distributed execution fabric rather than a single-model application.

| Layer | Role |
| --- | --- |
| Ray Serve and Ray Actors | Long-lived accountable actors, service orchestration, and distributed runtime behavior |
| Postgres | Durable audit rows, verifier jobs, evidence state, and transaction records |
| Redis | Token revocation, emergency cutoff propagation, and hot-path runtime support |
| Neo4j | Graph-backed policy and authorization relationships |
| Rust `seedcore-verify` | Offline and embedded proof-kernel verification paths |
| TypeScript verification apps | Operator console, proof surface, and verification API |

The governed state transition is:

```text
Event -> AI advisory plan -> Agent -> ActionIntent -> PDP
  -> ExecutionToken or PolicyDeny
  -> Actuator / edge path
  -> EvidenceBundle and transition receipts
  -> Replay / RESULT_VERIFIER
  -> verified, rejected, review_required, or quarantined state
```

## Quick Start

### Host-Mode Local Runtime

For macOS or laptop development, use the host-mode helpers in [deploy/local/README.md](deploy/local/README.md). They avoid the full Kind/Kubernetes footprint and are the best path for routine bring-up.

Prerequisites:

- PostgreSQL 17
- Redis
- Python virtual environment with project dependencies installed

Typical startup:

```bash
brew services start postgresql@17
brew services start redis

PGUSER=$(whoami) bash deploy/local/init-full-db-direct.sh

bash deploy/local/run-api.sh
bash deploy/local/run-hal.sh
bash deploy/local/run-task-stack.sh start
```

Local endpoints:

- API ingress: `http://127.0.0.1:8002`
- HAL bridge: `http://127.0.0.1:8003`
- Ray Serve / actor apps: `http://127.0.0.1:8000`
- Live API docs: `http://127.0.0.1:8002/docs`

Focused host verification:

```bash
bash scripts/host/verify_authz_graph_rfc_phases.sh
bash scripts/host/verify_q2_verification_contracts.sh
```

### Kind + Kubernetes

Prerequisites: `kubectl`, `kind`, `helm`, Docker, `envsubst` (macOS: `gettext`), and enough local resources for the cluster.

```bash
cp docker/env.example docker/.env
./deploy/deploy-all.sh
./deploy/port-forward.sh
```

Useful deployment flags include `--skip-build`, `--skip-hal`, `--skip-ingress`, `--worker-replicas N`, and `--deploy-verification-api`.

Verify the core runtime after port-forwarding:

```bash
curl http://localhost:8002/health
curl http://localhost:8002/readyz
curl http://localhost:8002/api/v1/pdp/hot-path/status
curl http://localhost:8002/api/v1/pdp/hot-path/metrics
```

### Rust Proof Kernel and TypeScript Surfaces

```bash
cargo test --workspace --manifest-path rust/Cargo.toml
cargo build -p seedcore-verify --manifest-path rust/Cargo.toml

npm --prefix ts install
npm --prefix ts run typecheck
npm --prefix ts run build

npm --prefix ts run serve:verification-api    # http://127.0.0.1:7071
npm --prefix ts run serve:proof-surface       # http://127.0.0.1:7072
npm --prefix ts run serve:operator-console    # http://127.0.0.1:7073
```

Offline transfer proof example:

```bash
cargo run -q --manifest-path rust/Cargo.toml -p seedcore-verify -- \
  summarize-transfer --dir rust/fixtures/transfers/allow_case
```

### Gemini CLI Extension

SeedCore ships a Gemini CLI extension scaffold that exposes read-only `seedcore.*` MCP tools. Bring up the runtime first, then install the extension:

```bash
gemini extensions install .
```

Confirm tools with `/extensions list`. For details, see [GEMINI.md](GEMINI.md), [gemini-tools.md](skills/using-seedcore/references/gemini-tools.md), and [gemini-troubleshooting.md](skills/using-seedcore/references/gemini-troubleshooting.md).

## Testing

```bash
.venv/bin/pytest
npm --prefix ts run test
cargo test --workspace --manifest-path rust/Cargo.toml
```

The CI workflow is defined in [.github/workflows/unit-tests.yml](.github/workflows/unit-tests.yml).

## License

SeedCore is licensed under the Apache-2.0 License. See [LICENSE](LICENSE).
