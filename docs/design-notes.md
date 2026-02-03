# SeedCore Design Notes — Deep Concepts

This document preserves the conceptual framing and intellectual depth behind SeedCore. It is linked from the main README as **Advanced Architecture** / **Design Notes** for readers who want the full neuro-symbolic and biological-design perspective.

## Cognitive Organism Framing

SeedCore is conceived as a **self-evolving cognitive operating system** that fuses distributed computing with **biological design principles**. It orchestrates a **persistent cognitive organism** — a living runtime that supports:

- real-time adaptation  
- deep structural reasoning  
- autonomous self-repair  

Built on Kubernetes and Ray, SeedCore replaces monolithic control logic with a **Planes of Control** architecture that cleanly separates high-level strategy from low-level execution. It integrates **System 1 (reflexive)** and **System 2 (deliberative)** pipelines: high-velocity events on the fast path, costly reasoning reserved for high-entropy anomalies.

## Intelligence Plane — Neuro-Symbolic Bridge

The Intelligence Plane is a shared **Brain-as-a-Service** layer providing neuro-symbolic reasoning and strategic orchestration. It:

- dynamically allocates **computational profiles (Fast vs Deep)** based on task complexity  
- guarantees thread-safe execution across concurrent requests  
- hydrates context on demand from persistent storage  

This plane bridges **vector-space anomalies** with **semantic graph neighborhoods** via **Hypergraph Neural Networks (HGNN)**, enabling LLMs to reason about structural root causes (e.g. “the cluster is fractured”) rather than only react to raw logs or text.

## Control Plane — Surprise and Governance

The Control Plane is the **strategic cortex**. It:

- ingests stimuli and governs system behavior  
- uses an **Online Change-Point Sentinel (OCPS)** to detect “surprise” via information entropy  
- leverages a **Policy Knowledge Graph (PKG)** for governance  
- drives the **Plan → Execute → Audit** loop  
- decomposes abstract intentions into concrete, executable sub-tasks  

## Execution Plane — Nervous System

The Execution Plane is the **nervous system**: a high-performance, distributed runtime managing a workforce of persistent, stateful agents acting as **local reflex layers**. Agents react to tasks, enforce RBAC, compute local salience scores, and advertise specialization and skills. Global routing, cognitive reasoning, and cross-agent coordination remain the responsibility of the Control and Intelligence planes.

## Infrastructure Plane — Computational Substrate

The Infrastructure Plane exposes the raw “physics and math” of the organism: XGBoost for regime detection, drift detectors for distribution shifts, and the **HGNN inference engine** for structural reasoning.

## Energy-Driven Dynamics

Agents and organs operate under a **metabolic energy budget** (`E_state`), creating feedback loops that naturally dampen runaway processes and reward efficient problem-solving. This **energy-driven dynamics** underpins tiered cognition and resource-aware behavior.

## Tiered Cognition

The system dynamically switches between **Fast Path** (heuristic/reflexive) and **Deep Path** (planner/reasoning) execution based on both semantic urgency and measured drift in incoming signals.

## Relation to the Hackathon README

The main README is optimized for hackathon judges and new contributors: **Gemini 3 reasons, SeedCore executes**. The same architecture is described here in organism and neuro-symbolic terms. The mapping is:

| Hackathon README        | Design Notes / Deep Concepts        |
|-------------------------|-------------------------------------|
| Reasoning Supervisor    | Brain-as-a-Service, HGNN bridge     |
| High-surprise detection | OCPS, information entropy           |
| Policy gate (PKG)       | Policy Knowledge Graph, governance  |
| JIT agents              | Local reflex layers, energy budget  |
| Holon Memory            | Persistent state, context hydration |

For implementation details, runtime registry, TaskPayload v2.5+, and service wiring, see [Architecture Overview](architecture/overview/architecture.md).
