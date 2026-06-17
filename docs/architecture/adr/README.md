# Architecture Decision Records (ADRs)

This directory stores durable architecture decisions for SeedCore.

Use ADRs for decisions that should remain stable across refactors, roadmap
windows, or implementation rewrites.

## Index

- [ADR 0001: Keep the PDP Stateless and Synchronous at Decision Time](./adr-0001-pdp-hot-path.md)
- [ADR 0002: Use Google IAP as the First-Mile Identity Gate for Non-Public SeedCore Ingress](./adr-0002-iap-edge-identity.md)
- [ADR 0003: Adopt an IGX Thor Trusted Edge Profile for High-Regulation SeedCore Deployments](./adr-0003-igx-thor-trusted-edge-profile.md)
- [ADR 0004: Coordinator-Embedded RESULT_VERIFIER With Journal Polling and Fail-Closed Twin Mutation](./adr-0004-result-verifier-runtime.md)
- [ADR 0005: Preserve Replayable Evidence for Governed Digital Twin State Transitions](./adr-0005-replayable-evidence-governed-state-transitions.md)
- [ADR 0006: Split RESULT_VERIFIER Into a Dedicated Process on Measurable Triggers](./adr-0006-result-verifier-deployment-split-trigger.md)
- [ADR 0007: Treat NVIDIA cuOpt as an Optional Optimization Sidecar](./adr-0007-cuopt-optimization-sidecar.md)
- [ADR 0008: Enterprise RAG as Governed Evidence Acquisition](./adr-0008-enterprise-rag-governed-evidence-acquisition.md)
- [ADR 0009: Authorization-Aware Retrieval Boundary](./adr-0009-authorization-aware-retrieval-boundary.md)
- [ADR 0010: Hardware-Anchored Telemetry as Execution Proof](./adr-0010-hardware-anchored-telemetry-execution-proof.md)
- [ADR 0011: Benchmark-Gated Authorization Graph Engine Evolution](./adr-0011-benchmark-gated-authz-graph-engine-evolution.md)

## Conventions

- file naming: `adr-XXXX-short-title.md`
- status should be explicit (`Proposed`, `Accepted`, `Superseded`, `Deprecated`)
- each ADR should include: context, decision, rationale, consequences, and
  alternatives considered
