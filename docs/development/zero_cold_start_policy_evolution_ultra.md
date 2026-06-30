# Zero-Cold-Start Policy Evolution with ULTRA Reference

**Date:** 2026-06-30
**Status:** Reference architecture / future advisory pilot
**Scope:** PolicyGraph Builder research, zero-shot authorization graph analysis, and non-authoritative proposal generation

---

## 1. Context & Executive Judgment

This note evaluates the applicability of the **ULTRA (Towards Foundation Models for Knowledge Graph Reasoning)** relational-path generalization framework to SeedCore's authorization graph engine and policy evolution roadmap.

### The Verdict

* **Pilot in PolicyGraph Builder and static analysis.** ULTRA's useful pattern
  is relation-centric generalization: it learns over interaction structure
  rather than tenant-specific entity embeddings. That makes it a plausible
  future helper for finding missing graph links, redundant paths, or policy
  package gaps before a tenant policy is promoted.
* **Keep out of the PDP hot path.** SeedCore's current authority baseline is a
  synchronous, deterministic, fail-closed PDP over pinned inputs. Online GNN
  inference has not been benchmarked or admitted as part of that path, and
  graph-engine evolution remains governed by ADR 0011 benchmark gates.
* **Doctrine boundary.** ULTRA link predictions are strictly non-authoritative.
  They may become reviewable policy package diffs, fixture suggestions, or
  operator diagnostics. They cannot bypass PDP evaluation, active compiled
  snapshot selection, `ExecutionToken` constraints, evidence closure, or
  `RESULT_VERIFIER` acceptance.

---

## 2. The Core Pattern: Inductive Relational Reasoning

Traditional graph neural network (GNN) models fail to generalize to new schemas because they learn static representations tied to specific nodes and relations. When a new role or resource class is added, the model must be retrained.

ULTRA solves this by shifting the learning target:
1.  **Relation-Path Generalization:** Instead of learning representation vectors for absolute entities (e.g., `principal:agent-01`, `role:facility-manager`), the model learns to reason over relative relational paths (e.g., `X -> delegates_to -> Y -> holds_role -> Z`).
2.  **Schema-Independent Backbones:** Because the network generalizes over the relative topology of edge interactions rather than the specific labels, a single pre-trained backbone can predict missing links on completely unseen graphs (zero-shot transfer).

---

## 3. SeedCore Application: Zero-Cold-Start Policy Analysis

For future multi-tenant PolicyGraph Builder work, this pattern can reduce
analysis cold start without changing execution authority:

```text
Tenant onboarding or schema evolution
  -> export draft policy package / graph tuple snapshot
  -> run ULTRA-style relational analysis offline
  -> propose missing links, redundant paths, or toxic-path fixtures
  -> review, schema-validate, fixture-test, and sign if required
     any policy package diff
  -> compile the approved snapshot for PDP-adjacent admission
```

### Key Integration Lanes

### A. Zero-Shot Onboarding for Multi-Tenant SaaS

* **Problem:** When a new enterprise client onboards, they may bring custom
  security roles, organizational hierarchies, and resource definitions.
  Training a custom policy-checking model for each tenant is structurally and
  operationally unattractive.
* **Candidate solution:** A pre-trained relational backbone can analyze a draft
  tenant delegation graph in offline mode. It can suggest missing authorization
  links, over-broad paths, or additional negative fixtures without requiring a
  custom tenant checkpoint as a prerequisite.

### B. Small Advisory Checkpoint Footprint

* **Problem:** Policy analysis helpers should not introduce multi-gigabyte
  model dependencies into the authority path, deployment baseline, or edge
  evidence profile.
* **Candidate solution:** ULTRA-style checkpoints avoid tenant-specific entity
  embedding tables and publicly described checkpoints are small enough to be
  plausible for local design-time analysis. SeedCore still needs its own
  benchmark evidence before treating any checkpoint size, latency, or memory
  profile as a product commitment.

---

## 4. Policy-Grade Guardrails

To remain aligned with SeedCore's safety doctrine, any implementation must obey
these constraints:

### 1. Offline/Batch Execution Only (No Real-Time PDP Interference)

* **Constraint:** GNN path-finding message passing, including NBFNet-shaped
  architectures used with ULTRA, is not part of the verified PDP path.
* **Boundary:** Relational reasoning is restricted to:
  * offline static analysis of draft authorization graphs before promotion;
  * background batch scans for structural anomalies or missing edges;
  * design-time PolicyGraph Builder helpers;
  * read-only display of analysis evidence in Execution Replay Studio, if a
    future Studio slice needs it.

### 2. Hybridization with Semantic Content (No Topology-Only Blindness)

* **Constraint:** Relational reasoning is structurally biased. If two subgraphs
  have similar connectivity patterns, topology alone may miss the difference
  between an allowed custody transfer and an adversarial or out-of-scope flow.
* **Boundary:** Structural predictions cannot satisfy SeedCore's semantic,
  freshness, or cryptographic gates. Where policy requires signer identity,
  SPIFFE/DPoP proof, hardware signer refs, token scope, telemetry binding, or
  approval envelopes, those checks remain deterministic PDP/evidence/verifier
  responsibilities.

### 3. Clear Symbolic Explainability

* **Constraint:** Relational probability scores are not replayable policy
  reasons by themselves.
* **Boundary:** GNN-predicted links are advisory proposals. If the model
  suggests a missing delegation link, the output must become a structured
  policy package diff with reason codes and fixtures. That diff must be
  reviewed, schema-validated, fixture-tested, and compiled into an active
  snapshot before the PDP can use it. Signing a proposal is necessary only if
  the relevant promotion workflow requires it; it is never sufficient by
  itself.

---

## 5. Architectural Role & Boundary Map

| Advisory graph surface | Allowed role | Prohibited action |
| :--- | :--- | :--- |
| **Relational link prediction** | Suggesting missing authorization paths, redundant paths, or policy cleanups | Authorizing requests directly or mutating active PDP policy |
| **Zero-shot transfer model** | Draft tenant-schema analysis in background | Running on the latency-sensitive PDP hot path |
| **Topology-only checkpoint** | Structural advisory analysis, if benchmarked and reviewed | Replacing semantic, freshness, signer, token, evidence, or verifier checks |

---

## 6. Implementation Progression

```text
[Phase 1: Static Policy Graph Analysis (Offline)]
  -> Export draft policy tuples and run ULTRA-style analysis to find unreachable
     nodes, missing co-signers, redundant paths, and fixture candidates.
[Phase 2: Shadow Simulation Fixture Generation]
  -> Use relation-path findings to generate negative paths for simulation and
     replay stress tests without changing enforce behavior.
[Phase 3: Reviewed Graph Schema Evolution]
  -> Let zero-shot onboarding helpers suggest policy package diffs for human or
     policy-admitted review, then promote only through existing compile,
     fixture, benchmark, PDP, token, evidence, and verifier boundaries.
```

## References

*   ULTRA: Towards Foundation Models for Knowledge Graph Reasoning: <https://arxiv.org/abs/2310.04562>
*   ADR 0011: Benchmark-Gated Authorization Graph Engine Evolution: `docs/architecture/adr/adr-0011-benchmark-gated-authz-graph-engine-evolution.md`
*   Policy Graph Builder Implementation Plan: `docs/development/policy_graph_builder_implementation_plan.md`
