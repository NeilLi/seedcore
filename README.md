# SeedCore

Unit-test workflow is currently set to manual runs only.

## Zero-Trust Runtime for Governed Agents and Robotic Endpoints

SeedCore is the zero-trust runtime that sits between AI judgment, Governed Agents, actuator endpoints, operators, and high-value physical assets. Every action is denied by default until identity, policy, provenance, custody, and execution conditions are verified.

It is designed for sealed inventory, high-value lots, vault workflows, lab handling, and partner handoffs where chain-of-custody matters as much as automation speed.

**Execution boundary**

```text
AI Judgment -> Agent Accountability -> Zero-Trust Policy -> Robotic Embodiment -> Immutable Custody
```

## What SeedCore Is

SeedCore is not a chatbot wrapper and not a tool-calling shortcut for a model. It is the governed runtime that turns advisory AI output into controlled enterprise execution.

In the current baseline, **AI judgment** executes on the cognitive core and coordinator planning stack. That layer can interpret, reason, and route, but it is not an authorizer.

It provides:

- deny-by-default authorization before movement or release
- governed dispatch through accountable agents
- policy-bound robotic and operator execution
- playback-grade telemetry and black-box forensics
- quarantine, rollback, and recovery paths that preserve custody state

## Judgment and Accountability Split

SeedCore now treats orchestration and authorization as separate layers:

- **`TaskPayload`** is the judgment envelope. It carries AI/cognitive routing, multimodal context, and execution planning inputs.
- **`ActionIntent`** is the accountability contract. It is the narrow policy object submitted by the accountable Agent to the PDP.
- The router may select an Agent, but it does not authorize execution.
- Physical or high-stakes actions remain deny-by-default until the PDP returns a signed `ExecutionToken`.

## Who This Repository Is For

- **Evaluators / Reviewers**: read *Why SeedCore Exists*, *Next-Stage Architecture*, and *Runtime Surfaces*
- **System Builders / Contributors**: read *Repository Upgrade Path*, *Quick Start*, and *Architecture Overview*
- **Researchers / Architects**: read *Next-Stage Architecture*, *Design Notes*, and *Advanced Architecture*

## Why SeedCore Exists

Most AI systems are built to generate text, images, or recommendations. Physical operations need a harder contract:

- actions must be authorized before execution
- agents must be accountable for every controlled handoff
- actuators must behave as policy subjects, not autonomous peers
- provenance and custody evidence must survive failures and disputes
- exception paths must default to quarantine rather than graceful drift into execution

SeedCore fills that gap. AI remains advisory. The runtime governs whether anything is allowed to happen at all.

## Next-Stage Architecture

The next stage of SeedCore is a zero-trust custody runtime with one strict principle:

> The model can propose. The Agent is accountable. The PDP decides. The robot executes. The evidence closes the loop.

This revision formalizes four contracts.

### 1. Actor Authority and the Stateless PDP

- The **Policy Decision Point (PDP)** must be stateless and synchronous.
- `evaluate_intent` must return either a signed `ExecutionToken` or a deny result in a single call.
- The PDP must not store per-intent state.
- The PDP validates the incoming `ActionIntent` only against the active Policy Knowledge Graph (PKG) snapshot and its current policy contract.
- AI is advisory only. In the current baseline this judgment runs on the cognitive core and coordinator planning stack. It may produce an `AdvisoryPlan`, but it does not authorize execution.
- The Agent is the accountable actor that formulates `ActionIntent`, presents evidence, receives `EvidenceBundle`, and closes the custody loop.

### 2. Updated `ActionIntent` Contract

To prevent replay attacks and keep execution bound to the active policy contract, every action intent must include a TTL and contract version.

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

To support playback and black-box forensics, the execution evidence envelope must include:

- `intent_ref`: link to the authorized `ActionIntent`
- `executed_at`: precise ISO-8601 timestamp of physical completion
- `telemetry_snapshot`: multimodal state from vision, sensors, GPS, and zone checks
- `execution_receipt`: cryptographic proof from the actuator or controlled endpoint

This is the minimum evidence required to explain why a custody transition was proposed, what policy allowed it, who or what executed it, and what state the asset was in at completion.

### 4. Corrected State Transition Flow

```text
Ingress: Event -> AI
Formulation: AI -> AdvisoryPlan -> Agent
Governance: Agent -> ActionIntent -> PDP -> ExecutionToken
Actuation: ExecutionToken -> Robot -> EvidenceBundle
Validation and Closing: EvidenceBundle -> Agent -> Validation -> Custody_Ledger_Updated
```

The Agent remains the central point of accountability for closing the custody loop.

### 5. TaskPayload to ActionIntent Mapping

For governed physical execution, the accountable Agent derives `ActionIntent` from `TaskPayload` using the following minimum mapping:

- `interaction.assigned_agent_id` is the source for `principal.agent_id`
- `multimodal.location_context` maps to `resource.target_zone`
- the Agent injects `action.security_contract.version` from its own `RoleProfile`
- optional `ttl_seconds` hints must be converted into a mandatory absolute `valid_until`

`TaskPayload` remains the judgment envelope. `ActionIntent` remains the authorization contract.

## Runtime Surfaces

SeedCore is organized around five governed surfaces that keep AI useful without allowing unverified release or movement.

### Event Ingress

Telemetry, provenance scans, operator requests, voice, images, and sensor signals enter as control inputs rather than side channels around the model.

### Policy Layer

The policy layer decides what is allowed before the runtime touches inventory, vaults, zones, or actuators. Role boundaries, release windows, provenance rules, seal status, and lockouts are runtime policy, not prompt hints.

### Execution Routing

SeedCore routes work to the right Governed Agent based on privilege, capability, and risk. The Agent translates approved intent into verified contracts for robotic endpoints, edge systems, or human approvers.

### Playback and Audit

Every custody transition should be replayable from source registration through final release, quarantine, or rollback.

### Exception Recovery

Broken seals, identity mismatches, out-of-zone movement, or missing evidence should route to lock, quarantine, alternate handling, or escalation before loss propagates.

## Repository Upgrade Path

The revised architecture can reuse most of the current SeedCore building blocks. The main change is tightening contracts between them.

| Next-stage contract | Existing components to reuse | Upgrade direction |
| --- | --- | --- |
| Event ingress | `EventizerService`, `OpsGateway` | Normalize telemetry, source claims, and operator input into governed ingress events |
| Advisory planning | Cognitive services, coordinator planning flow | Keep AI advisory and emit `AdvisoryPlan` rather than implicit authority |
| Stateless PDP | PKG evaluation path, coordinator policy logic, `src/seedcore/coordinator/core/execute.py` | Refactor policy evaluation into a synchronous `evaluate_intent` boundary that returns `ExecutionToken` or deny without persisting intent state |
| Governed execution | `PlanExecutor`, `OrganismService`, routing layer | Dispatch only tokenized actions to robotic or controlled endpoints |
| Evidence and custody | `FactManagerService`, `StateService`, telemetry stack | Persist `EvidenceBundle`, enable playback, and update custody ledger only after validation |

## Rare Asset and High-Trust Workflows

The runtime is aimed at environments where a mistaken release is materially expensive:

- rare and precious lots with provenance requirements
- enterprise labs and vaults with zone and seal controls
- distributed partner networks that need replayable custody evidence

In these environments, the default action is quarantine, not graceful degradation.

## Architecture Overview

SeedCore currently uses:

- **Ray Serve** for service orchestration
- **Ray Actors** for governed agent and execution runtime behavior
- **Postgres / Redis / Neo4j** for state, memory, telemetry, and policy foundations

The current repository already contains most of the primitives needed for the next-stage design:

- coordinator services for planning and policy gating
- PKG infrastructure for active policy evaluation
- organism services for execution routing
- ops services for ingress, facts, and state

For deep technical details see:

- *Advanced Architecture*
- *Design Notes*
- *Architecture Migration Summary*

---

## Quick Start (Kubernetes + KubeRay)

### Prerequisites

- Kubernetes tooling: `kubectl`, `kind`, `helm`
- Docker
- 16GB+ RAM, 4+ CPU cores recommended
- Linux with Docker support

### Option 1: Automated Deployment (Recommended)

```bash
git clone https://github.com/NeilLi/seedcore.git
cd seedcore

cp docker/env.example docker/.env

./deploy/deploy-all.sh
```

### Verify Installation

```bash
# Ray dashboard
curl http://localhost:8265/api/version

# API health
curl http://localhost:8002/health

# Ray Serve services
curl http://localhost:8000/cognitive/health
curl http://localhost:8000/pipeline/health
curl http://localhost:8000/organism/health
```

---

## 🔧 Configuration (Key)

```env
SEEDCORE_STAGE=dev
RAY_ADDRESS=ray://seedcore-svc-stable-svc:10001
POSTGRES_HOST=postgresql
REDIS_HOST=redis-master
NEO4J_HOST=neo4j
```

---

## 📊 Monitoring

- Ray Dashboard: `localhost:8265`
- Logs:

```bash
kubectl logs -l app=seedcore-api -n seedcore-dev -f
```

---

## 📚 API Summary

### Ray Serve (Port 8000)

| Service     | Path         | Role                 | Stability |
| ----------- | ------------ | -------------------- | --------- |
| Cognitive   | `/cognitive` | Reasoning / Planning | Alpha     |
| Coordinator | `/pipeline`  | Control Plane        | Alpha     |
| Organism    | `/organism`  | Execution Plane      | Alpha     |
| State       | `/ops/state` | State aggregation    | Stable    |

### Standalone API (Port 8002)

- `/health`
- `/readyz`
- `/healthz/runtime`

---

## ✅ Unit Tests (CI)

The unit-test workflow is configured for manual runs only (no automatic push/PR triggers).

- Workflow file: `.github/workflows/unit-tests.yml`
- Local run:

```bash
pytest -q
```

---

## 🔗 Related Projects & Reference Implementations

SeedCore is the core reasoning-and-execution infrastructure. The following repositories are optional companion projects used for demonstration, testing, and policy development:

- **Hotel Simulator** — [github.com/NeilLi/hotel-simulator](https://github.com/NeilLi/hotel-simulator)  
  A physical-world environment simulator used to demonstrate closed-loop reasoning, telemetry feedback, and replanning with SeedCore.
- **PKG Simulator** — [github.com/NeilLi/pkg-simulator](https://github.com/NeilLi/pkg-simulator)  
  A standalone Policy Knowledge Graph (PKG) simulator used to author and test execution policies enforced by SeedCore.

These projects are not required to run SeedCore, but they illustrate how SeedCore integrates with real domains and policy systems.

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
