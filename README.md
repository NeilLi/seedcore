# SeedCore

[![Unit Tests](https://github.com/NeilLi/seedcore/actions/workflows/unit-tests.yml/badge.svg)](https://github.com/NeilLi/seedcore/actions/workflows/unit-tests.yml)

### Reasoning Infrastructure for the Physical World

SeedCore is an **AI-native orchestration and execution system** that allows large reasoning models (such as **Gemini 3**) to safely plan, execute, and adapt actions in **real-world environments**.

SeedCore does **not** treat AI as a chatbot or UI feature.
It treats **reasoning as infrastructure**.

Reasoning models *decide what should happen*.
SeedCore ensures it *can happen*, *should happen*, and *actually happens* — safely, audibly, and adaptively.

---

## What SeedCore Is

SeedCore is a **closed-loop reasoning → execution platform** that connects abstract AI planning to concrete physical systems.

It provides:

- execution guarantees
- policy enforcement
- capability binding
- feedback-driven replanning
- distributed, auditable control

SeedCore turns real environments into **Intelligent Centers**: programmable systems that can handle **creative, ambiguous, high-surprise requests** without sacrificing safety or control.

---

## Who This Repository Is For

- **Evaluators / Reviewers**
  Read: *Why SeedCore Exists*, *Closed-Loop Execution*, *Vision*
- **System Builders / Contributors**
  Read: *Quick Start*, *Architecture Overview*, *Deployment*
- **Researchers / Architects**
  Read: *Planes of Control*, *Design Notes*, *Advanced Architecture*

---

## Why SeedCore Exists

Most AI systems stop at **generation**:

- text
- images
- recommendations

But real environments require **agency**:

- tools must be authorized
- policies must be enforced
- robots and infrastructure must act
- failures must be handled
- intent must persist across time

SeedCore fills this gap.

> **Reasoning models reason.**
> **SeedCore executes.**

Together, they form a closed loop:

```
Intent → Reasoning → Plan → Execution → Feedback → Replanning
```

Remove the reasoning model → no planning or adaptation.
Remove SeedCore → reasoning cannot safely reach the real world.

---

## How SeedCore Works (High Level)

SeedCore is built on **Ray**, **Ray Serve**, and modern distributed-systems principles.
It **strictly separates thinking from doing**.

### 🧠 Reasoning Models — Planning Supervisor

Large reasoning models (e.g. Gemini 3) are used as **planners**, not controllers.

They:

- interpret multimodal intent
- reason across constraints and context
- decompose intent into **Task Graphs (DAGs)**
- propose replans when execution drifts

**They never call tools, devices, or APIs directly.**

### 🧩 SeedCore — Orchestration & Agency Layer

SeedCore provides the infrastructure required to turn plans into safe execution:

- **TaskPayload v2.5+** — stable execution envelope
- **High-surprise detection** — decide fast path vs deep reasoning
- **Policy Knowledge Graph (PKG)** — deny-by-default authorization
- **PlanExecutor** — step-level execution, dependency tracking, retries
- **JIT agent materialization** — capabilities spawned on demand
- **RBAC & tool boundaries** — enforced at runtime
- **Telemetry & provenance** — full audit trail
- **Holon Memory** — hierarchical state across sessions and devices

Every AI decision is **executable, auditable, and reversible**.

---

## Closed-Loop Execution (Core Loop)

```
1. Intent
   High-ambiguity request arrives via TaskPayload v2.5+

2. Surprise Detection
   Decide reflex execution vs deep reasoning

3. Planning
   Gemini 3 produces a structured task plan (DAG or steps)

4. Policy Enforcement
   PKG authorizes every step (deny-by-default)

5. Execution
   PlanExecutor materializes agents and executes steps

6. Feedback
   Telemetry and failures are captured

7. Replanning
   Reasoning model adapts plan if reality diverges
```

This loop enables **Industrialized Intelligence** — AI that can operate in the physical world, not just describe it.

---

## Core Architectural Planes

SeedCore uses a **Planes of Control** architecture to isolate concerns and reduce coupling.

```
Intelligence Plane  →  Control Plane  →  Execution Plane  →  Infrastructure Plane
        ↑                                                        ↓
        └────────────────── Feedback & Drift ──────────────────┘
```

### 🧠 Intelligence Plane

- Reasoning interfaces
- Context hydration
- Model connectors (Gemini 3, others)

### 🎮 Control Plane

- Surprise detection
- Policy enforcement (PKG)
- Plan → Execute → Audit orchestration
- Planner + PlanExecutor coordination

### ⚡ Execution Plane

- Distributed agent runtime
- Capability registry
- RBAC-enforced tool execution
- Telemetry emission

### ⚙️ Infrastructure Plane

- Drift detection
- Regime classification
- Structural reasoning (HGNN)
- Health, energy, and performance monitoring

---

## Key Capabilities

- **Reasoning-Aware Orchestration**
  Deep reasoning only when needed
- **High-Surprise Handling**
  Creative requests become structured plans
- **Policy-First Execution**
  No action without authorization
- **Dynamic Capability Materialization**
  Agents and skills spawned just-in-time
- **Memory & Continuity**
  Holon Memory preserves intent across failures

---

## Vision

SeedCore demonstrates a future where:

- reasoning models provide **intellect**
- SeedCore provides **agency**
- physical environments become **adaptive systems**
- AI moves from **generation → execution**

SeedCore is **model-agnostic** and can integrate with any reasoning-capable model that supports planning and replanning.

> This is not a demo app.
> This is reasoning infrastructure.

---

## 🚀 Quick Start (Kubernetes + KubeRay)

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

## 🏗️ Architecture Overview

SeedCore uses:

- **Ray Serve** for service orchestration
- **Ray Actors** for agent execution
- **Postgres / Redis / Neo4j** for state, memory, and policy

For deep technical details see:

- *Advanced Architecture*
- *Design Notes*
- *Architecture Migration Summary*

---

## 🔧 Configuration (Key)

```env
SEEDCORE_STAGE=dev
RAY_ADDRESS=ray://seedcore-svc-head-svc:10001
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

The release pipeline runs a dedicated unit-test workflow on every pull request and main-branch push.

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
