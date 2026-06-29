# SeedCore Sandbox Hardening and Verifier Bridge Strategy

**Date:** 2026-06-26  
**Status:** Canonical Strategy  
**Reference Docs:**  
*   [safety_doctrine_enforcement_plan.md](file:///Users/ningli/project/seedcore/docs/development/safety_doctrine_enforcement_plan.md)  
*   [seedcore_proof_pyo3_bridge_decision_memo.md](file:///Users/ningli/project/seedcore/docs/development/seedcore_proof_pyo3_bridge_decision_memo.md)  
*   [trust_runtime_category_distinction.md](file:///Users/ningli/project/seedcore/docs/development/trust_runtime_category_distinction.md)

---

## 1. Context and Motivation

As a trust runtime, SeedCore’s primary concern is **governed admissibility and replayable proof**. While SeedCore does not replace traditional system-level perimeter defense, it must execute within a secure, isolated container runtime. 

Integrating OS-level sandboxing technologies like **gVisor (`runsc`)** directly impacts how application subprocesses (like our Rust verifier binary) execute. This document outlines the unified strategy to harden our execution environment without compromising our core trust boundaries or introducing premature performance optimizations.

---

## 2. Verifier Bridge Strategy: Subprocess-First, PyO3-Ready

We will continue with the current metric-based fallback trigger strategy, keeping the subprocess verifier bridge as the default, while preparing the PyO3 path as an experimental candidate.

```text
       ┌────────────────────────┐
       │   Agent Actuator /     │
       │   Coordinator Pod      │
       └───────────┬────────────┘
                   │
         [Is PyO3 Flag Active?]
           /               \
       (No)                 (Yes)
       /                       \
 ┌────▼─────────────┐     ┌─────▼────────────┐
 │ Subprocess Bridge│     │ PyO3 Bridge      │
 │ (Default)        │     │ (Experimental)   │
 └────┬─────────────┘     └─────┬────────────┘
      │                         │
      │ • Process Isolation     │ • In-Process GIL
      │ • Blast-Containment     │ • Low Syscall Overhead
      │ • Requires execve       │ • Larger Blast Radius
      └─────────────────────────┘
```

### The Subprocess Advantage: Process Isolation
For a forensic trust verifier, process isolation is valuable. Running the Rust verifier in a separate subprocess guarantees that if the verifier crashes, panics, leaks memory, or experiences unexpected runtime errors, the failure is entirely contained. It prevents corruption of the main Python coordinator memory space, maintaining a clean trust boundary.

### The PyO3 Path: Experimental and Feature-Flagged
While PyO3 avoids `execve` dependencies and reduces JSON serialization overhead, it runs the Rust verifier in-process. This increases coupling and the blast radius—any low-level native extension crash or memory fault could take down the entire coordinator process.

### Decision Rule for PyO3 Promotion
We will not make PyO3 the primary bridge unless sandbox profiles show subprocess execution is failing or degraded. The transition decision is governed by this explicit rule:

```text
Default: subprocess verifier bridge
Fallback candidate: PyO3 bridge

Promote PyO3 only if:
- execve is blocked or degraded under target sandbox profiles;
- verifier latency/error metrics cross defined thresholds;
- PyO3 produces byte-for-byte equivalent verification outcomes;
- crash containment and observability are acceptable;
- replay determinism is preserved.
```

**Post-compromise Rule:** Do not trade trust-boundary clarity for premature optimization. The architecture remains **subprocess-first, PyO3-ready**.

---

## 3. Sandbox Hardening Schedule

We will decouple the development tracks to ensure Window H milestones remain focused on core capability development, while obtaining early signals on sandbox compatibility.

```text
   [ Window H Phase ]                 [ Post-Window H Phase ]
┌─────────────────────────┐        ┌──────────────────────────┐
│ Compatibility Probe     │        │ Full Hardening           │
│ • Local runsc spike     ├───────>│ • Formalize RuntimeClass │
│ • Actuator startup test │        │ • Network egress limits  │
│ • execve telemetry      │        │ • Read-only mounts / CI  │
└─────────────────────────┘        └──────────────────────────┘
```

### A. Alongside Window H: Compatibility Probe & Metrics
Instead of delaying sandbox validation entirely, we will execute a thin-slice compatibility probe. This ensures that runtime changes don't break downstream assumptions.
*   **Local Spike:** Run a minimal `runsc`/gVisor compatibility spike locally.
*   **Startup Verification:** Test actuator pod startup and verify subprocess execution behavior.
*   **Telemetry:** Capture any sandbox-induced failures or performance penalties as metrics.
*   **Boundary Control:** Do not enforce full production-hardening gates yet; focus on signal collection.

**Implementation status (2026-06-29):** The local compatibility probe is now
checked in as [`scripts/host/test_gvisor_compat_probe.sh`](../../scripts/host/test_gvisor_compat_probe.sh).
It validates that Docker exposes a `runsc` runtime, optionally mounts the local
`seedcore-verify` binary, and exits with a clear skip when `runsc`, Docker, or
the Docker daemon are unavailable. This probe is a sandbox signal only; it does
not gate Window H advisory correctness and does not change the subprocess-first
verifier bridge decision.

### B. Post-Window H: Full Sandbox Hardening
Once the functional requirements of Window H are verified, we will harden the infrastructure layer:
*   **Kubernetes Manifests:** Formalize the `RuntimeClass` in Helm and Kubernetes templates to bind actuator pods to `runsc`.
*   **OS Profiles:** Define seccomp and AppArmor profiles specifically tailored to restrict syscall access.
*   **Network and File Hardening:** Enforce strict outbound network egress filters and read-only root mounts for running pods.
*   **E2E Validation:** Verify that policy gates, token issuance, signed receipts, and evidence flows operate normally under the restricted system state.
*   **CI Pipeline Integration:** Add automated CI steps that execute verification tests inside sandboxed environments to prevent regression.
