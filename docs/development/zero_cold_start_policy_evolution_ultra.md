# Zero-Cold-Start Policy Evolution with ULTRA Reference

**Date:** 2026-06-30  
**Status:** Reference Architecture  
**Scope:** Policy Graph Builder, Zero-Shot Authorization Graph Evolution, and GNN Advisory Gating  

---

## 1. Context & Executive Judgment

This note evaluates the applicability of the **ULTRA (Towards Foundation Models for Knowledge Graph Reasoning)** relational-path generalization framework to SeedCore's authorization graph engine and policy evolution roadmap.

### The Verdict:
*   **Adopt in: Policy Graph Builder & Static Analysis.** The mathematical core of ULTRA (modeling relative topological relationships rather than static entity embeddings) is a powerful pattern for zero-shot policy schema evolution, allowing SeedCore to onboard new tenant roles and assets without cold-start retraining.
*   **Restrict from: PDP Hot Path.** The computational overhead of online GNN path-finding violates the hot path's sub-50ms latency SLA.
*   **Doctrine Boundary:** ULTRA link predictions are strictly non-authoritative. They serve as offline advisory proposals or missing edge indicators for operators, and must never bypass PDP evaluation or execution token gating.

---

## 2. The Core Pattern: Inductive Relational Reasoning

Traditional graph neural network (GNN) models fail to generalize to new schemas because they learn static representations tied to specific nodes and relations. When a new role or resource class is added, the model must be retrained.

ULTRA solves this by shifting the learning target:
1.  **Relation-Path Generalization:** Instead of learning representation vectors for absolute entities (e.g., `principal:agent-01`, `role:facility-manager`), the model learns to reason over relative relational paths (e.g., `X -> delegates_to -> Y -> holds_role -> Z`).
2.  **Schema-Independent Backbones:** Because the network generalizes over the relative topology of edge interactions rather than the specific labels, a single pre-trained backbone can predict missing links on completely unseen graphs (zero-shot transfer).

---

## 3. SeedCore Application: Zero-Cold-Start Policy Evolution

For SeedCore's multi-tenant architecture, this capability addresses a major scaling bottleneck:

```text
Tenant Onboarding (New Roles / New Asset Schemas)
  ──► Compile capability/delegation graph topology
  ──► Apply pre-trained ULTRA-style GNN backbone (offline)
  ──► Predict missing delegation paths or potential access gaps (Zero-Shot)
  ──► Propose policy/graph updates for operator approval
```

### Key Integration Lanes:

### A. Zero-Shot Onboarding for Multi-Tenant SaaS
*   **Problem:** When a new enterprise client onboards, they bring custom security roles, organizational hierarchies, and resource definitions. Training a custom policy checking model for each tenant is structurally and operationally prohibitive.
*   **Solution:** A single, lightweight pre-trained relational backbone can analyze the new tenant's delegation graph on day one. It can predict missing authorization links or redundantly permissive paths without requiring custom model checkpoints.

### B. Micro-Model Footprint for Edge Environments
*   **Problem:** Deploying multi-gigabyte models to resource-constrained edge gateways (such as NVIDIA Jetson Orin nodes) introduces severe memory and deployment overhead.
*   **Solution:** By avoiding the storage of massive static entity embedding tables, the relational reasoning model maintains a tiny parameter footprint (~2 MB). This makes it highly portable, fast to serialize, and cheap to store in edge memory registries.

---

## 4. Policy-Grade Hardening & Guardrails

To remain aligned with SeedCore's **Safety Doctrine**, the following constraints are enforced:

### 1. Offline/Batch Execution Only (No Real-Time PDP Interference)
*   **Constraint:** GNN path-finding message passing (like the NBFNet architecture inside ULTRA) is computationally expensive and scales poorly in real-time execution.
*   **Enforcement:** Relational reasoning is strictly prohibited from running on the synchronous hot path. It is restricted to:
    *   Offline static analysis of authorization graphs during compilation.
    *   Background batch pipelines scanning for structural anomalies or missing edges.
    *   Interactive design-time helpers inside the Policy Replay Studio.

### 2. Hybridization with Semantic Content (No Topology-Only Blindness)
*   **Constraint:** Relational reasoning is structurally blind. If two subgraphs have identical connectivity patterns (e.g., an operator transferring shoes vs. an attacker transferring keys), the model treats them identically.
*   **Enforcement:** SeedCore hybridizes structural graph inputs with semantic and cryptographic validation:
    *   The PDP must deterministically verify the X.509 signer certificates, SPIFFE IDs, and token scopes.
    *   Structural link predictions are ignored if the semantic access checks or cryptographic signatures are invalid.

### 3. Clear Symbolic Explainability
*   **Constraint:** Relational probability scores function as black boxes, lacking deterministic audit trails.
*   **Enforcement:** GNN-predicted links are treated purely as **advisory proposals**. If the model suggests a missing delegation link (e.g., recommending a user be granted a co-signature role), it must be converted into a deterministic, human-reviewed, and signed policy graph update before the PDP will admit it as an active rule.

---

## 5. Architectural Role & Boundary Map

| WAM / Graph Surface | Allowed Role | Prohibited Action |
| :--- | :--- | :--- |
| **Relational Link Prediction** | Suggesting missing authorization paths or policy cleanups | Authorizing requests directly or mutating active PDP policy |
| **Zero-Shot Transfer Model** | Multi-tenant schema parsing in background | Running on the latency-sensitive PDP hot path |
| **Topology-Only Checkpoints** | Lightweight (~2 MB) structural analysis backbone | Replacing semantic and cryptographic signature verification |

---

## 6. Implementation Progression

```text
[Phase 1: Static Policy Graph Analysis (Offline)]
  ──► Run ULTRA-style analysis to find unreachable nodes or missing co-signers.
[Phase 2: Shadow Simulation Gating (Window I/J)]
  ──► Use relation-path checks to generate negative paths for simulation stress-testing.
[Phase 3: Hybridized Graph Schema Evolution]
  ──► Enable zero-shot onboarding helpers to suggest permission updates for review.
```

## References

*   ULTRA: Towards Foundation Models for Knowledge Graph Reasoning: <https://arxiv.org/abs/2310.04562>
*   ADR 0011: Benchmark-Gated Authorization Graph Engine Evolution: `docs/architecture/adr/adr-0011-benchmark-gated-authz-graph-engine-evolution.md`
*   Policy Graph Builder Implementation Plan: `docs/development/policy_graph_builder_implementation_plan.md`
