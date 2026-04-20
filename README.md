# SeedCore

CI is active for `push` to `main`, `pull_request`, and manual dispatch
(`.github/workflows/unit-tests.yml`).

## Zero-Trust Runtime for High-Consequence AI Actions

AI agents are becoming operational, but governance has not kept pace.
Enterprises are under pressure to automate, yet they still need reliable
ways to control what high-consequence AI actions are allowed to do, prove
why an action was permitted, and contain failures before they become
liabilities.

SeedCore is a deterministic, zero-trust runtime for high-consequence AI
actions. It evaluates governed requests in real time through a
synchronous, stateless-at-decision-time **Policy Decision Point (PDP)**
over a pinned PKG snapshot and bounded request context. Advisory AI can
propose; governance issues a short-lived `ExecutionToken` only when the
decision is `allow`.

All outcomes (`allow` / `deny` / `quarantine` / `escalate`) are recorded
with replayable, auditable evidence. SeedCore is not another model layer;
it is the runtime that makes high-consequence AI action safe enough to
execute.

The long ambition is large: become the trust substrate between frontier
models and real-world execution. The execution strategy is deliberately
narrow: win one high-trust vertical workflow first, make it operationally
credible, and expand from a hardened proof boundary rather than from a
broad platform claim.

## Core Principle

> The model can propose. The Agent is accountable. The PDP decides. The
> robot executes. The evidence closes the loop.

This is the one-line statement of SeedCore's authority and accountability
model. Everything in the runtime — from the `ActionIntent` contract to
the `EvidenceBundle`, from the authz graph to the `RESULT_VERIFIER` — is
a materialization of this principle.

## Trust Runtime, Not A Cybersecurity Product

SeedCore uses zero-trust language but is not a traditional cybersecurity
product. Cybersecurity systems protect environments by detecting threats,
hardening perimeters, or blocking suspicious behavior. SeedCore governs
execution *within* an environment: it decides whether a high-consequence
action is admissible, issues bounded authority when policy allows it, and
produces replayable proof that explains exactly why the action was
allowed.

- Deterministic, policy-driven execution rather than heuristic threat
  detection.
- Signed receipts, transition evidence, and replayable forensic bundles
  rather than alerts or perimeter blocks.
- The PDP is synchronous and stateless at decision time; it evaluates
  admissibility against current policy, not whether an actor "looks
  malicious."
- Memory is a bounded supporting subsystem for context and salience, not
  a threat-intelligence plane or an alternate authority path.

For the canonical category framing, see
[trust runtime category distinction](docs/development/trust_runtime_category_distinction.md).

## Where SeedCore Sits

SeedCore is designed to sit between powerful ecosystems, not to replace
them.

- Model providers supply reasoning, planning, and multimodal
  intelligence.
- Identity and cloud platforms supply first-mile operator identity and
  access control.
- Edge and robotics platforms supply the physical execution substrate,
  perception stack, and trusted hardware boundary.
- SeedCore provides the governed admissibility and proof layer between
  those worlds: who was allowed to act, under which exact policy and
  scope, on which device or custody boundary, with what evidence before
  and after execution.

> External systems can authenticate who reached the system and run the
> physical AI stack. SeedCore decides what is admissible, issues bounded
> authority, and proves what happened afterward.

## What SeedCore Is, And Isn't

SeedCore is a governed runtime that converts advisory AI output into
policy-checked execution. It binds identity, policy, hardware scope, and
replayable evidence into one execution boundary.

It is **not** a chatbot wrapper, a tool-calling layer, a cybersecurity
detection product, an identity provider, a model provider, a robotics
SDK, or a generic workflow orchestrator.

In the current repository baseline, **AI judgment** lives in the
cognitive and coordinator planning stack. That layer can interpret,
enrich, and route work, but it does not authorize high-stakes execution.

The current baseline provides:

- deny-by-default authorization before movement or release
- governed dispatch through accountable agents
- policy-bound robotic and operator execution
- playback-grade telemetry and black-box forensics
- quarantine, rollback, and recovery paths that preserve custody state

## Judgment and Authority Split

SeedCore separates orchestration from authorization:

- **`TaskPayload`** is the judgment envelope — routing, multimodal
  context, planning inputs.
- **`ActionIntent`** is the accountability contract — the narrower policy
  object submitted to the PDP by the accountable agent.
- Routing may select an agent; routing does not grant authority.
- High-stakes actions remain deny-by-default until the PDP returns a
  signed `ExecutionToken`.

For the full contract shape (including TTL, `security_contract`, and
`TaskPayload → ActionIntent` mapping), see
[agent action gateway contract](docs/development/agent_action_gateway_contract.md).

## 2026 Product Focus

For the current execution phase, SeedCore is intentionally constrained to
one must-win product workflow:

- **Agent-Governed Restricted Custody Transfer (RCT)**

Read that wedge in commerce terms: a governed path where **digital
transaction identity** (for example order, quote, line item, declared
value) is bound to **physical custody and scope** before SeedCore issues
bounded execution authority, and where closure produces **replayable
proof** suitable for high-trust fulfillment. This is not a general
robotics stack and not a perimeter-security product.

The root README describes the active product boundary. The detailed
dated rollout, status, and next-step plan live in the development docs:

- [development docs index](docs/development/README.md)
- [current next steps](docs/development/current_next_steps.md)
- [2026 execution plan](docs/development/seedcore_2026_execution_plan.md)
- [Q2 product spec](docs/development/q2_2026_audit_trail_ui_spec.md)
- [hot-path shadow to enforce breakdown](docs/development/hot_path_shadow_to_enforce_breakdown.md)
- [kube topology validation Q2 signoff](docs/development/kube_topology_validation_q2_signoff.md)

## Current Capability Baseline

The repository currently implements the three unresolved trust gaps in
agent execution — **verifiable authority boundary**, **policy enforcement
layer**, and **trusted chain of custody** — with the following live
surfaces:

- **Authority boundary**: short-lived `ExecutionToken` issuance with TTL,
  revocation, and HAL emergency-stop enforcement at the actuator edge.
- **Policy layer**: PKG evaluation through `ops/pkg` with OPA WASM
  support, PKG-mandatory gate for action tasks, hot-activation of
  snapshots, compiled authz graph with dry-run publish gates, and edge
  OTA heartbeat/stream for desired-version resolution.
- **Chain of custody**: `EvidenceBundle` with `policy_snapshot_hash`,
  `decision_graph_snapshot_hash`, and `state_binding_hash` for
  replay-grade binding; HAL-backed `transition_receipt` with
  nonce-based replay detection; forensic sealing on attested endpoints.
- **Result verification**: `RESULT_VERIFIER` P0 is embedded in the
  Coordinator runtime, verifies source-preserving replay bundles in the
  Rust kernel, writes authoritative fail-closed lockout/quarantine
  state on replay mismatch in the RCT slice, and revokes the specific
  execution token in the Redis CRL on terminal fail-closed outcomes.
- **Trust proofs**: restricted-custody flows support explicit
  `trust_proof` material for offline artifact and trust-bundle
  verification via the Rust `seedcore-verify` kernel.
- **Signing posture**: TPM/KMS-backed signing for trust-critical
  receipts on attested endpoints; software-backed Ed25519/HMAC remain
  available for local development.

For implementation detail and rollout posture, see
[current next steps](docs/development/current_next_steps.md) and the
[development docs index](docs/development/README.md).

## Architecture at a Glance

### Substrate

- **Ray Serve** for service orchestration
- **Ray Actors** for governed agent and execution runtime behavior
- **Postgres / Redis / Neo4j** for state, memory, telemetry, and policy
  foundations

| Substrate | Operational role |
| --- | --- |
| Confluent Kafka | Event backbone for intent, telemetry, and policy outcome streams |
| Ray + Kubernetes | Distributed execution for compiled authz graph and shard-aware hot-path routing |
| Redis | Token revocation and emergency cutoff propagation |
| Cloud KMS | Hardware-backed signing for policy and transition artifacts |
| Durable forensic store | Long-lived persistence for signed forensic blocks and replay evidence |

Ray is used because SeedCore is an execution runtime, not a single-model
application. It gives SeedCore a practical control plane for long-lived
accountable actors, distributed scheduling across heterogeneous
environments, coordinated policy evaluation and execution routing, and
a gradual expansion from centralized cloud orchestration toward
edge/local inference without rebuilding the control plane later.

### Governed state transition flow

```text
Ingress:            Event       -> AI
Formulation:        AI          -> AdvisoryPlan  -> Agent
Governance:         Agent       -> ActionIntent  -> PDP -> ExecutionToken
Actuation:          ExecutionToken -> Robot      -> EvidenceBundle
Validation/Closing: EvidenceBundle -> Agent      -> Validation -> Custody_Ledger_Updated
```

The accountable agent remains the central actor that closes the custody
loop; the PDP, the actuator, and the verifier are deterministic gates
around that agent.

For the full architectural picture, see:

- [Architecture Overview](docs/architecture/overview/architecture.md)
- [Design Notes](docs/design-notes.md)
- [Zero-Trust Custody and Digital-Twin Runtime](docs/architecture/overview/zero_trust_custody_digital_twin_runtime.md)
- [Source Registration Architecture](docs/development/source_registration_architecture.md)
- [Policy Gate Matrix](docs/development/policy_gate_matrix.md)
- [Evidence Bundle Example](docs/development/evidence_bundle_example.json)

## Decision Records (ADRs)

- [ADR 0001 — Keep the PDP Stateless and Synchronous at Decision Time](docs/architecture/adr/adr-0001-pdp-hot-path.md)
- [ADR 0002 — Use Google IAP as the First-Mile Identity Gate for Non-Public SeedCore Ingress](docs/architecture/adr/adr-0002-iap-edge-identity.md)
- [ADR 0003 — Adopt an IGX Thor Trusted Edge Profile for High-Regulation SeedCore Deployments](docs/architecture/adr/adr-0003-igx-thor-trusted-edge-profile.md)
- [ADR 0004 — Coordinator-Embedded RESULT_VERIFIER With Journal Polling and Fail-Closed Twin Mutation](docs/architecture/adr/adr-0004-result-verifier-runtime.md)
- [ADR 0005 — Preserve Replayable Evidence for Governed Digital Twin State Transitions](docs/architecture/adr/adr-0005-replayable-evidence-governed-state-transitions.md)

## Physical Proof Pilot

SeedCore currently runs a verifiable "Digital Twin of Trust" pilot where
a single robot or sensor stack manages a narrow physical-goods workflow
with zero manual intervention.

```text
Tracking Event -> Policy Decision -> Execution Token -> Edge Actuator -> Signed Evidence Bundle
```

The next-step pilot keeps the demo centered on **Restricted Custody
Transfer**, treats the flow as a **Forensic Handshake**
(request → decision → scoped execution → forensic closure), and uses the
first red-team drill — **MITM coordinate redirect** — to prove that
scope mismatch becomes `deny` or `quarantine` rather than silent drift.

An automated serial runner reproduces the full end-to-end custody loop:

```bash
python scripts/host/run_closed_loop_demo.py
```

Outputs are generated under `demo-output/`. Key implementation
boundaries:

- `src/seedcore/api/routers/source_registrations_router.py`
- `src/seedcore/ops/source_registration/projector.py`
- `src/seedcore/coordinator/core/governance.py`
- `src/seedcore/hal/drivers/robot_sim_driver.py`
- `src/seedcore/ops/evidence/builder.py`
- `src/seedcore/models/evidence_bundle.py`

## Who This Repository Is For

- **Evaluators / Reviewers** — read *Zero-Trust Runtime*, *Core
  Principle*, *Architecture at a Glance*, and the ADRs.
- **System Builders / Contributors** — read *Quick Start*, the
  [development docs index](docs/development/README.md), and
  [deploy/local/README.md](deploy/local/README.md).
- **Researchers / Architects** — read [Design Notes](docs/design-notes.md),
  [Architecture Overview](docs/architecture/overview/architecture.md),
  and the ADR set above.

## Quick Start

### Host-Mode Local Runtime (recommended for day-to-day development)

For macOS or laptop development, use the host-mode helpers under
[deploy/local/README.md](deploy/local/README.md). They avoid the full
Kind/Kubernetes footprint and are the best path for routine runtime
bring-up and verification.

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

Focused authz-graph RFC-phase verification:

```bash
bash scripts/host/verify_authz_graph_rfc_phases.sh
```

### Kind + Kubernetes

Prerequisites: `kubectl`, `kind`, `helm`, Docker, `envsubst` (macOS:
`gettext`), and 16 GB+ RAM / 4+ CPU.

```bash
git clone https://github.com/NeilLi/seedcore.git
cd seedcore
cp docker/env.example docker/.env
./deploy/deploy-all.sh
```

`deploy-all.sh` builds the image (unless `--skip-build`), creates or
reuses a local `kind` cluster, deploys PostgreSQL/MySQL/Redis/Neo4j,
applies migrations, then deploys Ray, the SeedCore API, bootstrap jobs,
ingress, and the HAL bridge. Useful flags: `--skip-build`, `--skip-hal`,
`--skip-ingress`, `--worker-replicas N`.

After the cluster is up, forward the standard ports:

```bash
./deploy/port-forward.sh
```

Verify:

```bash
curl http://localhost:8002/health
curl http://localhost:8002/readyz
curl http://localhost:8002/api/v1/pkg/status
```

Full deployment walkthroughs, environment variable reference, and HAL
signing posture live in
[deploy/local/README.md](deploy/local/README.md) and
[docs/development/tpm_fleet_rollout_runbook.md](docs/development/tpm_fleet_rollout_runbook.md).

### Rust + TypeScript Proof Surface

```bash
cargo test --workspace --manifest-path rust/Cargo.toml
cargo build -p seedcore-verify --manifest-path rust/Cargo.toml
rust/target/debug/seedcore-verify summarize-transfer --dir rust/fixtures/transfers/allow_case

npm --prefix ts install
npm --prefix ts run typecheck
npm --prefix ts run build
npm --prefix ts run serve:verification-api   # :7071
npm --prefix ts run serve:proof-surface      # :7072
```

### Gemini CLI Extension

SeedCore ships a Gemini CLI extension scaffold that exposes the
read-only `seedcore.*` MCP tools:

```bash
gemini extensions install .
```

The extension does not start SeedCore for you. Bring up the runtime
first, then confirm tools are visible via `/extensions list` in Gemini.
For the full tool catalog and troubleshooting, see
[GEMINI.md](GEMINI.md),
[gemini-tools.md](skills/using-seedcore/references/gemini-tools.md), and
[gemini-troubleshooting.md](skills/using-seedcore/references/gemini-troubleshooting.md).

## Runtime Surfaces

Governed API surfaces (versioned under `/api/v1`):

- **Tasks** — submission, status, governance, cancel, logs
- **Agent Actions** — external gateway evaluate + request lookup
- **Source Registrations & Tracking Events** — custody ingress
- **Facts / Advisory** — control-plane facts and advisory outputs
- **PKG** — snapshot status, activation, OTA heartbeat/stream,
  authz-graph refresh, async evaluate, snapshot compare/compile
- **Capabilities** — capability registration

Actuator surface (HAL bridge, `:8003`): `GET /status`, `GET /state`,
`POST /actuate`, `POST /forensic-seal`, and admin execution-token
revocation / E-STOP endpoints. `POST /actuate` accepts an
`execution_token` payload and returns a `transition_receipt` on governed
actuation; expired, over-TTL, or revoked tokens are rejected.

Observability: Ray Serve at `:8000`, Ray Dashboard at `:8265`. Logs:

```bash
kubectl logs -l app=seedcore-api -n seedcore-dev -f
```

For the full endpoint reference, use the live OpenAPI docs at
`http://localhost:8002/docs` after bring-up, or see the routers under
`src/seedcore/api/routers/`.

## Testing

Unit-test workflow: `.github/workflows/unit-tests.yml`.

```bash
pytest -q
```

## Contributing

1. Fork the repo
2. Create a feature branch
3. Test locally (host-mode) and in Kubernetes where relevant
4. Submit a PR

## License

See [`LICENSE`](LICENSE).

## Support

- See [`docs/`](docs/) — particularly [`docs/development/`](docs/development/)
- Review [`deploy/`](deploy/)
- Open a GitHub issue
