# PDP Architecture Research Synthesis

Date: 2026-05-22  
Status: Reference synthesis  
Primary ADR: [ADR 0001: Keep the PDP Stateless and Synchronous at Decision Time](../architecture/adr/adr-0001-pdp-hot-path.md)

## Purpose

This reference evaluates the PDP architecture research against SeedCore's
current authorization posture.

The conclusion is deliberately narrow:

- ADR 0001 does not need to be replaced or materially upgraded.
- The research supports ADR 0001's accepted decision: keep the final PDP
  stateless, synchronous, deterministic, local or near-local, and fail-closed.
- The full research belongs in a reference document because much of it is
  vendor landscape, admin-plane design, synchronization strategy, and future
  roadmap guidance rather than a new architecture decision.

## Disposition

### Keep ADR 0001 As-Is

ADR 0001 already captures the core decision that matters for SeedCore:

- one synchronous request-time authorization decision
- pinned policy snapshot and bounded request context
- stateless PDP evaluation
- fail-closed dependency and freshness behavior
- causality and freshness controls around the context supply chain
- signed edge context for hardware-critical facts
- replay-visible policy and context evidence
- shadow, canary, enforce, and rollback controls

The new research strengthens the rationale, but it does not overturn the
decision.

### Preserve This Research As Reference Material

The research is most useful as a reference because it spans topics that should
not all be placed inside an ADR:

- comparative policy language landscape
- local sidecar and embedded PDP patterns
- endpoint routing and fact-cache guidance
- OPAL-style policy and data synchronization
- visual policy builder and template-linked policy design
- ReBAC consistency and causality-token patterns
- decentralized authorization tokens such as Biscuit
- policy CI, shadow evaluation, canary rollout, and rollback practice

Those topics should inform implementation plans, product specs, and future ADRs
only when SeedCore makes a specific binding decision.

## Research Fit Matrix

| Research theme | SeedCore fit | Recommended placement |
| --- | --- | --- |
| Stateless synchronous PDP | Already accepted | ADR 0001 |
| Local sidecar or embedded PDP | Strong fit | ADR 0001 plus hot-path implementation docs |
| Cache facts, not decisions | Strong fit | ADR 0001 and hot-path contract |
| Path-trie endpoint routing | Useful gateway optimization | Development contract or gateway implementation note |
| Cedar / Cerbos / OPA comparison | Useful landscape, no binding choice yet | Reference only |
| Cedar template-linked policies | Useful for policy builder and end-user sharing | PolicyGraph Builder docs |
| OPAL-style synchronization | Strong direction for control/data plane updates | Future context supply-chain RFC |
| ReBAC and causal tokens | Strong fit where delegation/sharing graphs dominate | ADR 0001 follow-on and authz graph RFC |
| Biscuit-style attenuation | Useful for edge/delegated authority research | Future execution-token research |
| XACML | Historical context only | Reference only |
| Fail-open canary behavior | Poor fit for high-consequence execution | Do not use for SeedCore hot path |

## Technology Landscape

The research compares five major policy paradigms. SeedCore should treat them as
design inputs, not as an immediate engine-selection mandate.

| Paradigm | Useful lesson for SeedCore | Caveat |
| --- | --- | --- |
| OPA / Rego | Mature policy-as-code, JSON input model, bundle and WASM options | General-purpose expressiveness can increase authoring and optimization burden |
| Cedar | Specialized authorization grammar, default deny, forbid-overrides-permit, template-linked policies, analyzability | Strong candidate for future policy templates, but not a current replacement decision |
| Cerbos | Stateless PDP, resource/principal-oriented YAML policy, service or sidecar deployment | Useful reference for admin-friendly policy shape, not a required runtime |
| Zanzibar-style ReBAC | Best fit for deep sharing, delegation, group, and resource hierarchy graphs | Requires specialized consistency and graph operational discipline |
| XACML | Historical ABAC blueprint | Too heavyweight for SeedCore's hot path and not a candidate default |

External checkpoint:

- Cedar documentation confirms template-linked policies, permit/forbid effects,
  forbid-overrides-permit behavior, and skip-on-error semantics.
- OPA documentation confirms Rego as the policy language over structured data,
  bundle/WASM deployment options, and performance guidance for optimized policy
  fragments.
- Cerbos documentation confirms stateless PDP deployment as a service or sidecar,
  with policy decisions based on caller-supplied information.
- SpiceDB documentation confirms ZedToken / zookie-style consistency controls
  for the New Enemy Problem and `at_least_as_fresh` semantics.
- Biscuit documentation confirms public-key authorization tokens, Datalog-based
  checks, and offline attenuation where added token blocks can only restrict
  authority.

## SeedCore Hot-Path Guidance

The research reinforces five implementation rules that are already directionally
present in SeedCore.

### 1. Keep Final Evaluation Local Or Near-Local

The final authorization check should run in-process, in a colocated sidecar, or
against a near-local compiled index. Remote calls may refresh inputs before the
decision, but the final decision should not depend on live multi-hop discovery.

For SeedCore, this maps to:

- compiled active authz graph
- pinned PKG snapshot
- local policy-case assembly
- bounded request context
- fail-closed quarantine when freshness cannot be proven

### 2. Cache Facts, Not Final Decisions

SeedCore should not cache final `allow`, `deny`, `quarantine`, or `escalate`
decisions as reusable authority.

Preferred cache contents:

- active policy snapshot metadata
- compiled graph indexes
- identity and delegation attributes
- approval envelope projections
- custody and asset state projections
- signed telemetry or edge context envelopes
- relationship tuples where a ReBAC store is introduced

This preserves low latency without turning stale decisions into accidental
permissions.

### 3. Use Gateway Classification Before PDP Evaluation

The path-trie routing idea is useful for the Agent Action Gateway and any
HTTP-facing governance boundary.

Recommended classification:

- `OPEN`: no governed action authority can be minted
- `AUTHENTICATED`: identity validation only
- `ACCESS_CONTROLLED`: identity validation plus PDP evaluation

This should remain a routing optimization. It must not become a second
authorization engine.

### 4. Initialize Engines And Compiled Artifacts At Startup

Policy engines, WASM modules, compiled authz graph indexes, and heavyweight
lookup tables should be loaded during service startup or snapshot activation.

Hot-path requests should not instantiate policy engines, compile rule bundles,
or perform expensive graph rebuilds.

### 5. Bind Freshness To Replay

Decision receipts should continue to evolve so a replay can answer:

- which policy snapshot was active
- which compiled graph version was used
- which context freshness boundary was satisfied
- which causality token or signed edge envelope was checked
- which stale or missing context caused quarantine

## Admin-Plane And End-User Policy Design

The research strongly supports the existing SeedCore split between:

- deterministic runtime authority in SeedCore
- guided policy authoring and simulation in `pkg-simulator`
- advisory AI explanation rather than direct policy authority

The strongest product pattern is:

1. users answer guided operational questions
2. the workbench maps answers into typed policy templates and scenario packs
3. SeedCore runs deterministic preflight
4. human review approves publication
5. runtime activation remains guarded by snapshot, manifest, and PDP controls

Cedar-style template-linked policies are a useful model for dynamic sharing:
developers define structurally validated templates, while product actions bind
specific principals or resources as data. SeedCore should borrow the separation
of static policy shape from dynamic assignments even if it does not adopt Cedar
as the runtime engine.

## Synchronization And OPAL-Like Control Plane

The research's OPAL pattern maps well to a future SeedCore context supply chain:

- central control plane watches policy and data changes
- edge clients subscribe to policy/data update notifications
- clients load only the relevant policy bundles and facts
- local PDPs evaluate without synchronous remote lookups

SeedCore should adapt this pattern rather than import it blindly.

Recommended SeedCore shape:

- Git or manifest-backed policy snapshot source of truth
- event-driven updates for approval, delegation, custody, and telemetry facts
- local materialized context views next to the PDP
- snapshot and context freshness exposed in status endpoints
- strict fail-closed behavior for high-consequence workflows

## ReBAC And Causality Tokens

The ReBAC section is highly relevant if SeedCore grows into richer sharing,
delegation, partner, and multi-tenant custody graphs.

The important lesson is not "always adopt Zanzibar." The lesson is:

- relationship writes should return an opaque causality token
- protected resources may store the token associated with relevant permission or
  state changes
- later checks can require the PDP to evaluate against a view at least as fresh
  as that token
- stale local replicas should block briefly for convergence or fail closed for
  high-consequence actions

This aligns with ADR 0001's follow-on work for causality and freshness controls.

## Decentralized Tokens And Attenuation

Biscuit-style attenuation is relevant to SeedCore's `ExecutionToken` and edge
authority research, but it is not an immediate replacement for SeedCore tokens.

Useful ideas:

- authority can be carried in cryptographically signed envelopes
- downstream holders may attenuate authority by adding restrictions
- services can verify local facts against token-borne logic
- token restrictions should be monotonic: a derived token can narrow authority,
  not expand it

SeedCore should consider this only after the current `ExecutionToken`,
hardware-anchor, and replay-proof contracts are stable.

## Rollout Safety

The research's CI/CD lifecycle matches the existing SeedCore promotion posture:

- static validation before activation
- shadow evaluation against live or production-equivalent traffic
- canary rollout before full enforcement
- latency, mismatch, error, and dependency-health monitors
- automated rollback triggers

SeedCore-specific correction:

- fail-open canary behavior is not acceptable for high-consequence physical,
  custody, or actuator-bound workflows.
- SeedCore can log candidate errors without enforcing candidate decisions in
  shadow mode, but once a path is authoritative it should fail closed to
  `deny`, `quarantine`, or `escalate` according to policy.

## What Should Change Next

Recommended documentation changes:

1. Keep ADR 0001 accepted and stable.
2. Cross-link ADR 0001 to this reference.
3. Use this reference to inform future implementation work, especially:
   - fact-cache and no-decision-cache guidance
   - gateway endpoint classification
   - causality-token request fields
   - signed context-envelope replay fields
   - PolicyGraph Builder template model
   - OPAL-like synchronization design

Recommended future code/docs targets:

- `docs/development/asset_centric_pdp_hot_path_contract.md`
  - add explicit no-decision-cache language
  - add optional causality-token request field
  - add compiled-context freshness fields to response checks
- `docs/development/policy_graph_builder_implementation_plan.md`
  - add template-linked policy pattern as a design inspiration
  - keep generated policy drafts advisory until deterministic preflight passes
- `docs/development/hot_path_enforcement_promotion_contract.md`
  - keep fail-closed as mandatory for high-consequence enforce mode
  - make any fail-open canary language explicitly out of scope
- future context supply-chain RFC
  - define event topics, ownership, freshness SLAs, and replay-visible context
    version proofs

## Bottom Line

Do not expand ADR 0001 into a vendor comparison or implementation survey.

ADR 0001 already makes the right durable decision. This research should live as
a complete reference synthesis and feed targeted follow-on specs where SeedCore
chooses concrete mechanisms.

## Source Checkpoints

These sources were used only to sanity-check the external technology claims in
the supplied research. They are not SeedCore commitments.

- [Cedar policy templates](https://docs.cedarpolicy.com/policies/templates.html)
- [Cedar authorization semantics](https://docs.cedarpolicy.com/auth/authorization.html)
- [OPA policy language](https://www.openpolicyagent.org/docs/policy-language)
- [OPA WebAssembly](https://www.openpolicyagent.org/docs/wasm)
- [OPA policy performance](https://www.openpolicyagent.org/docs/policy-performance)
- [Cerbos deployment patterns](https://docs.cerbos.dev/cerbos/latest/deployment/index.html)
- [SpiceDB consistency](https://authzed.com/docs/spicedb/concepts/consistency)
- [SpiceDB read-after-write consistency](https://authzed.com/docs/spicedb/concepts/read-after-write)
- [OPAL TL;DR](https://docs.opal.ac/getting-started/tldr/)
- [Biscuit specifications](https://doc.biscuitsec.org/reference/specifications)
- [Biscuit Datalog](https://doc.biscuitsec.org/reference/datalog.html)
- [Biscuit cryptography](https://doc.biscuitsec.org/reference/cryptography)
