# SeedCore 2026 Execution Plan

Date: 2026-04-10
Status: Working execution plan (Q2 freeze implemented; Window A host-first closure complete; RESULT_VERIFIER P0 shipped; remote kube topology validated with scripted verification lane; verification API kube integration lane implemented)

## Purpose

This document converts the current SeedCore strategy into a concrete 2026
execution plan.

It is meant to answer:

> If SeedCore is going to become genuinely useful this year, what exactly do we
> ship, in what order, and how do we know the work is actually moving the
> product forward?

This plan is grounded in the current repo state:

- the must-win workflow remains `Restricted Custody Transfer`
- the proof / verification surface is the first real product surface
- the hot path remains in `shadow`
- the runtime already has a credible governed execution baseline
- the PDP decision boundary is synchronous and stateless at decision time, with stateful snapshot/context/evidence systems around it

This is not a speculative "future platform" plan. It is a wedge-first
execution plan.

## Execution Update (2026-05-21, Autonomy-Ready Trust Runtime)

The 2026 plan should now explicitly support the coming wave of coding and
action agents. The goal is not to make agents trusted by default. The goal is
to give agents stronger **self-regulation**, **simulation**, and
**self-healing** interfaces while keeping SeedCore's deterministic authority
boundary intact.

New operating principle:

```text
Autonomy can increase inside the proposal, simulation, and repair loops.
Authority still enters only through PDP allow, scoped ExecutionToken issuance,
evidence closure, and verifier acceptance.
```

This pulls four workstreams forward:

1. **Bounded autonomy interfaces.** Accelerate the Q3 agent boundary around MCP and `seedcore.agent_action.evaluate`, integrating them directly with the public SDK for **Agent Self-Regulation**. Assistants can run preflight simulation checks ("would this action be admissible?") prior to execution.
2. **Gated Action DX (MVP landed).** The `@gated_action` decorator,
   thread-local evaluator injection, and `GovernedResult` are implemented at
   `src/seedcore/sdk/gated_action.py` for one preflight-only RCT adapter path.
   Targeted tests validate strict fail-closed behavior, missing telemetry
   evidence handling (`origin_scan`, `delivery_scan`, `signed_edge_telemetry`),
   and zero execution of wrapped business functions in MVP preflight/shadow
   mode.
3. **Governance-aware learning (Elevated).** Elevate the Scenario Generator and Governance Reward Scorer as active simulation infrastructure for coding/action agents. They produce probes, typed verdicts, and training samples. They do not authorize execution, override the PDP, or reinterpret `RESULT_VERIFIER`, but actively drive reinforcement learning and self-correction loops.
4. **AI-led self-healing.** Add a staged operational-autonomy ladder:
   diagnose -> propose patch -> run degraded-edge gates -> open PR or patch
   review -> canary/shadow validation -> operator-approved promotion. Until a
   separate promotion contract exists, assistants must not directly mutate live
   production trust state.

The program remains locked to Restricted Custody Transfer. Autonomy work must
make the RCT wedge easier to implement, test, replay, and repair; it must not
turn the 2026 plan into a broad autonomous-agent platform.

### AI-Led Self-Healing Workstream

This workstream is about operational repair loops, not autonomous production
authority.

Milestone ladder:

1. **Read-only diagnosis.** Assistant runs hot-path status, verification queue,
   replay detail, runbook lookup, and degraded-edge drill summaries; produces a
   bounded incident hypothesis with cited evidence.
2. **Fixture reproduction.** Assistant turns the failure into a local fixture
   or host drill that reproduces telemetry loss, outbox delay, stale graph,
   stale telemetry, Redis outage, or replay mismatch.
3. **Patch proposal.** Assistant edits only the scoped code/docs/tests needed
   for the reproduced failure and attaches the before/after gate output.
4. **Gate execution.** Assistant runs the relevant host or CI gate, beginning
   with `verify_q2_degraded_edge_drill_matrix.sh`,
   `verify_q2_verification_contracts.sh`, targeted pytest, TypeScript tests,
   or Rust verifier checks as appropriate.
5. **Reviewable promotion.** Assistant opens a PR or patch review with
   replay/audit references, changed files, residual risk, and rollback notes.
6. **Shadow/canary only.** Assistant may help prepare a shadow or canary
   promotion plan, but enforce-mode changes and quarantine clearance require
   operator approval until a dedicated promotion ADR exists.

Initial repair targets:

- telemetry envelope schema drift;
- missing or delayed outbox publication;
- fixture/runtime mismatch in verification API projections;
- stale graph or stale telemetry degraded-edge failures;
- replay lookup or workflow correlation breaks across gateway and verifier
  surfaces.

Hard stops:

- no direct production mutation;
- no quarantine clearance;
- no signer or token revocation bypass;
- no `shadow` -> `enforce` promotion without explicit gate evidence and human
  approval.

## Execution Update (2026-04-07)

The highest-risk north-star verification gap is now closed for the current RCT
slice:

- **RESULT_VERIFIER (P0) is implemented and live-validated** for the RCT trust
  slice: a coordinator-embedded runtime polls `digital_twin_event_journal` for
  `transition_recorded` and `evidence_settled`, enqueues idempotent jobs
  (`result_verifier_jobs`, `FOR UPDATE SKIP LOCKED` workers), runs the same
  replay-chain verification stack as `ReplayService` (Python + Rust chain
  verifier), and **immediately** mutates authoritative asset twin / custody on
  mismatch (`verification_failed` vs `verification_quarantined`,
  `result_verifier_lockout` in governance, `authority_source=result_verifier`).
  Durable outcomes live in `result_verifier_outcomes`; intake watermark state is
  in `result_verifier_runtime_state` (migrations `133` / `134`). Control:
  `SEEDCORE_RESULT_VERIFIER_*` env vars. **v1 constraints:** RCT workflow scope
  only; DB journal polling as the trigger (not Kafka); no automatic
  unquarantine. Architecture decision: [ADR 0004](../architecture/adr/adr-0004-result-verifier-runtime.md).
- **Hard downstream fail-closed gating is now wired to authoritative verifier
  state**, not only read-side projection: policy evaluation, closure, and
  settlement handoff explicitly deny when `result_verifier_lockout`,
  `verification_failed`, or verifier quarantine state is present on the
  authoritative twin.
- **Near-term follow-ups:** Postgres-backed integration tests (journal -> job ->
  twin mutation -> downstream deny), multi-worker `SKIP LOCKED` contention
  coverage, operator remediation/runbook guidance for quarantine clearance, and
  an optional future move to an out-of-coordinator worker or event-bus trigger
  only if scale or isolation requires it.

Remaining Q2 emphasis is now operationalization:

- validate the now-aligned gates in each real deployment topology
- expand adversarial and degraded-edge-condition coverage
- stabilize benchmark and observability baselines under deployment-realistic
  topology
- begin the narrow Q3 bridge work only after the above is green enough to
  support external-agent debugging without contract churn
- define the smallest safe Gemini-visible read surface once the verification
  and hot-path read contracts stop shifting

## Execution Update (2026-04-10, Remote Kube Topology)

The first deployment-realistic Kubernetes topology is now green for the
runtime-critical Q2 gates:

- remote GCP VM + Kind deployment through `build.sh` and `deploy/` is working
  for SeedCore API, Ray/KubeRay, ingress, and HAL simulation
- `/health`, `/readyz`, `/api/v1/pdp/hot-path/status`, and live observability
  checks are aligned and passing against the kube-backed API
- the Redis dependency-loss drill now passes in this topology without flipping
  the runtime into rollback or mismatch posture
- deployment-realistic hot-path benchmark capture is stable enough to use as a
  baseline (`40` requests, `0` mismatches, `0` errors, `p50 ~111ms`,
  `p95 ~139ms`, `p99 ~156ms`)

Important topology limit:

- the current remote Kind topology does **not** yet include Kafka or the
  verification API deployment, so this is not full external-surface signoff

Decision:

- Q3 bridge work may begin only in the narrow read-oriented form needed for
  external-agent debugging against the hot-path/runtime read contract
- the Gemini-visible surface should stay at the exact minimal read-only bundle
  already defined in `src/seedcore/plugin/mcp_server.py`, and in this topology
  the safe live subset is only `seedcore.hotpath.status` and
  `seedcore.hotpath.metrics` until the verification API is also deployed

Checked-in signoff note:

- see
  [kube_topology_validation_q2_signoff.md](/Users/ningli/project/seedcore/docs/development/kube_topology_validation_q2_signoff.md)

## Execution Update (2026-04-10, Kube Verification Lane Hardening)

The kube validation path is now implemented as a first-class deployment
verification lane rather than a manual sequence.

Implemented:

- `deploy/verify-kube-topology.sh` now orchestrates:
  - aligned gate checks (`/health`, `/readyz`, hot-path status)
  - status/metrics observability parity check
  - optional degraded-edge drills
  - benchmark + baseline capture
  - topology signoff report generation with Q3-readiness and Gemini-safe
    read-surface output
- `deploy/deploy-all.sh` now supports post-deploy verification controls:
  - `--verify-kube`
  - `--verify-kube-no-degraded`
  - `--verify-kube-no-benchmark`
  - `--enforce-kube-q3-gate`
  - `--kube-verify-report-dir`
- `scripts/host/verify_pkg_redis_resilience.sh` now supports
  deployment-realistic Redis outage drills in Kubernetes mode
  (`SEEDCORE_REDIS_DRILL_MODE=auto|kube|docker`) in addition to local docker
  mode.

Latest live run (remote GCP Kind topology):

- gates: passed
- degraded Redis drill (kube scale down/up): passed
- benchmark (`40` requests): `0` mismatches, `0` errors
- latest benchmark latency sample:
  - `p50=153.79ms`
  - `p95=386.25ms`
  - `p99=400.15ms`
- signoff report outcome:
  - `green_enough_for_narrow_q3_bridge=true`
  - `verification_api_available=false`
  - `safe_gemini_read_surface=["seedcore.hotpath.status","seedcore.hotpath.metrics"]`

Operational consequence:

- narrow Q3 bridge work remains allowed from this topology
- verification-surface bridge work remains blocked until the verification API
  is deployed in-cluster
- Kafka-dependent readiness/degraded lanes remain blocked until Kafka is
  deployed in-cluster

## Execution Update (2026-04-10, Verification API Kube Integration)

The verification API gap in the Kubernetes deploy/verification surface is now
implemented in repo scripts/manifests so the topology can promote from
hot-path-only signoff to full productized verification-surface signoff when
the service is deployed.

Implemented:

- dedicated verification API image build path:
  - `docker/Dockerfile.verification-api`
  - runtime includes `seedcore-verify` binary and fixture assets for
    fixture-mode verification endpoints
- dedicated Kubernetes workload:
  - `deploy/k8s/verification-api.yaml` (`Deployment` + `Service` on `7071`)
  - runtime API base wired through service-DNS env (`SEEDCORE_RUNTIME_API_BASE`)
  - readiness/liveness probes on `/health`
- deploy runner:
  - `deploy/deploy-verification-api.sh`
  - supports build + kind image load + rollout wait
- orchestration integration:
  - `deploy/deploy-all.sh` adds:
    - `--deploy-verification-api`
    - `--verification-api-image <img:tag>`
    - `--skip-verification-api-build`
    - `--enforce-kube-full-gate`
  - default remains soft/non-breaking (verification API deploy opt-in)
- kube verification lane upgrade:
  - `deploy/verify-kube-topology.sh` now:
    - detects/port-forwards verification API when present
    - runs `scripts/host/verify_productized_surface.sh` automatically when
      verification API is reachable
    - resolves `SEEDCORE_AUDIT_ID` via in-cluster Postgres fallback
      (`kubectl exec ... psql`) for deployment-realistic runs
    - emits new signoff fields:
      - `verification_surface_available`
      - `verification_surface_protocol_passed`
      - `green_enough_for_full_external_agent_debugging`

Safe-read-surface promotion rule is now topology-driven:

- verification API unavailable or protocol failing:
  safe surface remains `seedcore.hotpath.status`, `seedcore.hotpath.metrics`
- verification API available and protocol passing:
  promote to full minimal read-only bundle
  (`verification.queue`, `workflow_verification_detail`, `workflow_replay`,
  `runbook_lookup`, plus hot-path reads)

Validation completed for this implementation slice:

- script contract tests (`tests/test_deploy_kube_verification_scripts.py`)
- shell syntax checks (`bash -n` on deploy and verification scripts)
- verification API image/container smoke:
  - image build from `docker/Dockerfile.verification-api`
  - `/health` endpoint healthy
  - fixture verification endpoint responds in-container on `:7071`
- remote Kind topology run (GCP VM):
  - `deploy/deploy-verification-api.sh` deployed
    `seedcore-verification-api` (`Deployment` + `Service`) in `seedcore-dev`
  - kube verification lane now reports verification-surface availability and
    full-surface gate status from live topology reports
  - Scenario B validated:
    when verification service is not discoverable, report keeps
    `verification_surface_available=false` and safe read surface remains
    hot-path-only
  - Scenario C validated:
    `SEEDCORE_ENFORCE_FULL_VERIFICATION_GATE=1` fails as intended when
    verification-surface protocol is not green

Remaining operational closure:

- Scenario A full protocol pass is still blocked by missing runtime audit IDs
  in the current topology (`public.governed_execution_audit` empty), so
  `verification_surface_protocol_passed` remains `false` until runtime traffic
  populates an audit-backed replay path.

## Prior Execution Update (2026-04-02)

The highest-priority Q2 contract hardening sequence has now been implemented in
the codebase for the RCT slice:

- `VerificationSurfaceProjection` is frozen as the frontend-facing read
  contract with versioned models and deterministic business-state mapping.
- verification API routes are migrated to `/api/v1/verification/*`.
- `AgentActionGateway` request schema is hardened and locked with generated
  schema artifacts/tests (`seedcore.agent_action_gateway.v1`).
- Screen 2 side-by-side audit trail is implemented as a contract-driven,
  three-column correlated view.
- hot-path `shadow`/`canary`/`enforce` semantics now include strict promotion
  gates, durable parity evidence persistence, and rollback triggers.
- first forensic-block JSON-LD contract freeze pass is implemented with strict
  schema validation, explicit `forensic_block_id`, and replay/materialization
  alignment checks.
- hot-path now exposes Prometheus text metrics in addition to JSON status.
- queue rows now expose product, update-time, and trust-alert fields.
- runbook lookup is available as a contract-shaped read surface for
  verification failures.
- edge telemetry now has a checked-in JSON Schema export path.
- Window A host-first closure is now implemented and verified:
  - host and CI gate components are aligned on the same acceptance slices
  - `scripts/host/verify_q2_verification_contracts.sh` now executes fixture
    HTTP matrix + degraded-edge drill matrix by default via CI launcher scripts
  - hot-path observability gate parsing is hardened for deployment-role labeled
    Prometheus text and now passes against live host runtime metrics/status

## Scheduled Next Execution Windows (2026-04-02)

The next schedule should be treated as the working sequence for the current
quarter boundary and early Q3 setup.

### Window A: 2026-04-02 to 2026-04-12

Goal:

- close Q2 acceptance gating

Status:

- **Implemented (host-first):** acceptance gates are executable and passing in
  both CI and local host verification paths.
- **Implemented (remote kube path):** first Kind-based runtime topology is now
  validated for health/readiness/hot-path observability, Redis dependency
  resilience, ingress, and HAL.
- **Implemented (scripted deployment lane):** kube verification is now wired
  into `deploy/` with explicit post-deploy flags and machine-readable signoff
  output.
- **Remaining:** verification API and Kafka deployment validation in the kube
  topology (verification API scripts/manifests now implemented; pending live
  capture in target remote cluster).

Must land:

- required CI coverage for Python parity/replay checks plus TypeScript
  verification surface tests
- host verification script parity with CI
- stable pass/fail contract for queue, verification detail, replay, runbook,
  and runtime/fixture forensics lookup

### Window B: 2026-04-08 to 2026-04-19

Goal:

- operationalize hot-path observability under real deployment wiring

Must land:

- manifest-backed deployment-role wiring validation
- JSON-to-metric export path for Prometheus or equivalent telemetry bridge
- alert-rule verification against live `/api/v1/pdp/hot-path/status` payloads

### Window C: 2026-04-15 to 2026-04-30

Goal:

- harden the slice against degraded and adversarial conditions

Must land:

- intermittent edge-connectivity drills
- stale-graph and dependency-unavailable drills
- coordinate tamper / replay injection simulation coverage
- repeatable evidence bundle export for rollback and quarantine cases

### Window D: 2026-05-01 to 2026-05-21

Goal:

- Land Gated Action DX MVP and establish agent self-regulation foundations

Status:

- **Implemented and targeted-test validated:** The SDK surface
  (`src/seedcore/sdk/`) provides the `@gated_action` decorator, thread-local
  evaluator injection (`using_evaluator`), and `GovernedResult` for one
  preflight-only RCT adapter path. It enforces preflight-only execution,
  SDK-side telemetry evidence checks (supporting `origin_scan`, `delivery_scan`,
  and `signed_edge_telemetry`), and strict fail-closed exceptions
  (`GatedActionEvaluatorNotConfigured`).
- **Validated with pytest:** Targeted coverage tests preflight zero-execution,
  telemetry validation quarantine, evaluator isolation, HTTP-style evaluator
  responses, and fail-closed evaluator errors.

Must land:

- one reference adapter for a current agent platform (Completed)
- one narrow commerce-side adapter for the canonical transaction flow (Completed)
- deterministic gateway request -> decision -> replay lookup mapping (Completed)

### Window E: 2026-05-15 to 2026-06-07

Goal:

- advance Workstream 3 from draft to implementation-grade evidence input

Must land:

- JSON schema export for `EdgeTelemetryEnvelopeV0`
- persistence of telemetry envelope refs on the governed receipt / forensic
  path
- fixture and test expansion for signed edge telemetry in the RCT closure flow

### Window F (Pulled Forward & Elevated): 2026-05-21 onward

Goal:

- Publish accelerated Gemini MCP tool bundles and operationalize Agent Self-Regulation

Status:

- **Pulled Forward:** Shifted from Q3 to late Q2/immediate execution to align with rapid advancements in AI agents (e.g. Antigravity and Codex).
- **Agent Self-Regulation:** Exposes the `seedcore.agent_action.evaluate` preflight path through Gemini MCP tools, enabling coding and action agents to run self-regulated simulation drills and verify policy compliance without granting write authority.

Must land:

- read-only wrappers for verification queue, detail, replay, runbook lookup, and hot-path metrics/status as Gemini MCP tools.
- explicit documentation that the Gemini surface is read-only, contract-driven, and designed for self-healing diagnosis.
- integration of Scenario Generator and Governance Reward Scorer scaffolds from the Governance-Aware Learning (GAL) loop as active shadow/simulation tools for agent training and drills.

## 2026 Objective

The 2026 objective should be:

**Make SeedCore the verifiable agentic ledger for one high-trust agent workflow
that can be piloted credibly before year end.**

In practice, that means:

- one canonical workflow
- one external agent boundary
- one physical custody boundary
- one runtime decision contract
- one evidence loop
- one verification surface
- one forensic replay story that survives adversarial review

Everything else is secondary.

## Canonical 2026 Positioning

For 2026 messaging, use this document as the canonical positioning source for
the active wedge.

Core position:

- SeedCore is the zero-trust execution and proof layer for
  high-consequence agent actions.
- In deployment terms for this phase, SeedCore is the verifiable agentic
  ledger and trust-anchor service for the trust slice.
- Short form: SeedCore makes AI actions governable, custody-aware, and
  replay-verifiable.

Category to own:

- zero-trust execution runtime for custody-aware agent operations

Category distinction to keep explicit:

- SeedCore is not a traditional cybersecurity product, even though it shares
  zero-trust terminology.
- Cybersecurity products primarily protect environments through detection,
  hardening, or blocking suspicious behavior.
- SeedCore governs execution inside an environment: it evaluates admissibility,
  issues bounded authority, and produces replayable proof.
- The PDP is deterministic and stateless at decision time; it is not a threat
  classifier.
- Memory and supporting state systems exist to provide bounded context,
  salience, and evidence support, not a threat-intelligence plane.

What SeedCore is not:

- a perimeter-defense or threat-detection system
- another model provider
- a generic agent framework
- a chatbot orchestration tool
- a broad workflow automation suite
- an observability dashboard wrapped in AI language

Canonical one-sentence pitch:

> SeedCore is the runtime that decides whether an AI agent may act in the real
> world, issues bounded execution authority when allowed, and proves what
> happened afterward.

Canonical mental model:

```text
The model decides what to try.
SeedCore decides what is admissible.
The execution layer performs the action.
The evidence layer proves what happened.
```

Messaging guardrails:

- prefer "productizing irrefutable governed execution and forensic replay"
- prefer "governing execution within the environment" over "protecting the
  environment"
- explain the difference between policy-driven admissibility and threat
  detection when zero-trust language might cause confusion
- avoid "full autonomous commerce stack" claims for the current phase
- avoid collapsing SeedCore into generic cybersecurity positioning without
  naming the proof-runtime distinction
- keep claims tied to the must-win `Restricted Custody Transfer` workflow and
  replay-verifiable evidence surface
- use
  [`trust_runtime_category_distinction.md`](trust_runtime_category_distinction.md)
  as the canonical supporting note for this category framing

## Product Definition For 2026

The product to ship this year is:

**Agent-Governed Restricted Custody Transfer with a Forensic Handshake**

User-level promise:

- an external agent requests a restricted transfer or purchase intent
- SeedCore validates delegated authority and policy
- SeedCore returns `allow`, `deny`, `quarantine`, or `escalate`
- if allowed, SeedCore mints transaction-specific execution authority
- the physical actor produces sensor-grounded evidence before closure
- SeedCore binds the economic and physical evidence into one replayable
  forensic chain
- operators and partners can verify the result afterward without trusting the
  initiating agent

This should be treated as the canonical 2026 package.

## Architectural Positioning In One Diagram

Use this framing consistently across roadmap and architecture discussions:

- top (`Brain/Intent`): humans and AI agents originate intent
- bottom (`Sandboxes/Reality`): economic and physical systems emit evidence
- center hub (`SeedCore`): PDP plus forensic evidence integrator

Boundary mapping:

- economic boundary: commerce transaction and order identifiers (for example,
  Shopify sandbox)
- physical boundary: simulation or edge telemetry and motion evidence (Gazebo
  in Q3, Jetson/robot edge in Q4)

SeedCore obligation:

- do not issue scoped authority for high-consequence execution unless policy,
  approval lineage, and boundary evidence requirements are satisfied
- persist one replayable forensic handshake chain tying decision, authority,
  and closure evidence together

For 2026, that package should be grounded in one concrete physical story:

- the governed good is physically handled during transfer
- the edge evidence source is a Jetson AGX Orin-class node
- the Q4 pilot package scopes a Unitree B2-class robot as the physical courier
  or custodian actor
- the digital transaction boundary is represented through a narrow commerce
  sandbox integration such as Shopify Sandbox
- the physical custody boundary is represented through Gazebo simulation in Q3
  and hardware-in-the-loop in Q4
- the digital twin mutation is tied to the exact transfer event, not only the
  policy decision

## Canonical 2026 Handshake

The must-win story for the year is this six-step sequence:

1. Human provides a rough request such as "get me a Tang Dynasty style tea set,
   roughly $50."
2. Agent-B queries the commerce sandbox, identifies the item, and signs an
   intent packet with its delegated hardware-bound identity.
3. Agent-S validates the authority chain, reserves the item, and returns the
   physical location or custody coordinates.
4. The physical actor executes the move or verification path, then captures
   shelf or handover evidence plus telemetry.
5. SeedCore packages the request, decision, quote, location evidence, and edge
   telemetry into a forensic block.
6. Settlement or transfer release occurs only when the digital and physical
   fingerprints agree.

This is still `Restricted Custody Transfer`. The difference is that the 2026
story now makes the proof boundary explicit.

## Execution Principles

Every 2026 deliverable should improve at least one of these:

- authority correctness
- runtime safety
- evidence integrity
- operator trust
- partner verifiability
- external agent integration
- physical and economic state convergence

If a task does not improve one of those directly for `Restricted Custody
Transfer`, it is sidecar.

## Workstreams

The year should be run as five connected workstreams.

## Cluster Deployment Posture (Trust Slice)

For pilot and production-facing deployments, SeedCore should run as a
high-availability trust service on the cloud cluster rather than as a
single-node demo dependency.

Operational role by substrate:

| Substrate | Operational role |
| :--- | :--- |
| Confluent Kafka | Event backbone for intent, telemetry, and policy outcome streams |
| Ray + Kubernetes | Distributed execution for compiled authz graph and shard-aware hot-path routing |
| Redis | Token revocation and emergency cutoff propagation |
| Cloud KMS | Hardware-backed signing for policy and transition artifacts |
| Durable forensic store | Long-lived persistence for signed forensic blocks and replay evidence |

Non-negotiable invariant:

- SeedCore is the final authority service for the trust slice. If evidence
  convergence fails, SeedCore must not attest the forensic handshake.

### Workstream 1: Hot-Path Operability

Goal:

- turn the current hot-path shadow work into production-grade operational
  evidence

Required outcomes:

- real runtime semantics for `shadow`, `canary`, and `enforce`
- durable parity evidence for the last `1,000` runs
- operator-visible mismatch and freshness alerts
- realistic concurrent benchmark coverage
- explicit rollback and auto-quarantine behavior
- graph and decision readiness signals that remain trustworthy under degraded
  edge conditions

Primary repo anchors:

- [hot_path_shadow_to_enforce_breakdown.md](/Users/ningli/project/seedcore/docs/development/hot_path_shadow_to_enforce_breakdown.md)
- [hot_path_enforcement_promotion_contract.md](/Users/ningli/project/seedcore/docs/development/hot_path_enforcement_promotion_contract.md)

### Workstream 2: Agent Action Gateway And Delegated Authority

Goal:

- make SeedCore callable by an external agent through a clean product boundary
  with narrow zero-trust authority

Required outcomes:

- one stable request schema for agent-originated actions
- identity and delegated-authority binding for agent principals
- hardware or device fingerprint capture on the request path
- transaction-specific token scoping to workflow, product or asset id, and
  physical scope
- deterministic error contracts
- multi-signature release hooks for human approval plus physical verification
- one reference adapter for a current agent platform
- one reference digital-transaction adapter for the canonical commerce story

This is the workstream that turns SeedCore from "deep system" into "integrable
product" without weakening the trust boundary.

### Workstream 3: Evidence Closure, Forensic Blocks, And Settlement

Goal:

- prove not only that the action was authorized, but that the governed outcome
  actually happened and can be replayed later

Required outcomes:

- evidence ingestion required for selected allowed actions
- sensor-grounded evidence schemas for cryptographically signed edge telemetry
- a canonical fingerprint component set for the pilot, covering:
  - economic transaction hash
  - physical presence hash
  - policy or reason trace hash
  - actuator or torque telemetry hash
- a first-class forensic block that binds:
  - request and decision hashes
  - approval and delegation linkage
  - product or asset identity
  - physical evidence references
  - telemetry and torque or weight signals
  - settlement and twin mutation references
- authoritative twin settlement on completion
- atomic linkage between twin-state mutation and localized physical evidence:
  - location
  - environmental readings
  - hardware health
- synchronized state capture for the canonical digital transaction boundary and
  the physical execution boundary
- audit-chain consistency across runtime, replay, and verification
- explicit failure handling for missing, stale, or contradictory evidence
- **2026-04 shipped:** continuous **RESULT_VERIFIER** loop after journal events:
  deterministic replay verification and **fail-closed** authoritative twin/custody
  mutation for RCT (see [ADR 0004](../architecture/adr/adr-0004-result-verifier-runtime.md))

Interpretation:

- "settlement" is not only a completed status flag
- settlement means SeedCore can prove which governed state transition occurred,
  which physical evidence was attached, and which twin state was finalized as a
  result

### Workstream 4: Verification Surface Productization

Goal:

- make the proof story usable for operators and third parties

Required outcomes:

- workflow-specific operator status and forensic views
- narrow partner/public proof surfaces
- stable explanation payloads
- signer provenance and authority-source visibility
- digital-twin state visibility at the exact handover moment
- a usable audit-trail view that can correlate:
  - natural-language or agent request
  - digital transaction trail
  - physical replay and telemetry timeline
- runbooks for lookup, exception handling, and investigation

Q2 product spec for this workstream:

- [q2_2026_audit_trail_ui_spec.md](q2_2026_audit_trail_ui_spec.md)

### Workstream 5: Pilot Packaging

Goal:

- package the above into something a design partner can evaluate

Required outcomes:

- one deployment path
- one operational runbook
- one scripted demo / simulation
- one verification package
- one clear integration guide
- one physical handover story that crosses the edge boundary
- one adversarial drill package proving the pilot is resilient, not only happy
  path

The Q4 pilot package should be explicit about the hardware story:

- the Unitree B2 is the scoped physical actor for custody movement or handover
- the Jetson edge node is the scoped telemetry and local execution boundary
- the pilot demonstrates allow / deny behavior using both digital credentials
  and real-time physical telemetry
- the operator surface shows both proof artifacts and the twin state captured at
  custody transfer time
- the pilot includes at least three red-team drills:
  - coordinate tampering
  - stolen authority replay
  - physical double-spend attempt

## Quarter Plan

## Q2 2026: Make The Wedge Operable And Freeze The Forensic Contract

This quarter should focus on hardening what already exists and freezing the
first replay-grade forensic schema.

### Primary objective

- convert the current RCT sign-off wedge into an operable, repeatable trust
  runtime slice with stable forensic inputs

### Must-ship items

- ~~freeze and version the current runtime-up RCT sign-off bundle~~
- ~~freeze the Q2 Audit-Trail UI contract for the four-screen verification surface~~
  (`Transfers`, transfer detail, asset forensics, replay/verification)
- ~~implement runtime-selectable hot-path mode semantics~~
- ~~persist parity events and build `1,000`-run exportable evidence~~
- instrument hot-path observability consistently across Kubernetes and host-mode
  environments
- ~~add graph freshness and dependency-based auto-quarantine~~
- add dedicated hot-path benchmark harness coverage for concurrent load
- promote runtime matrix capture and replay verification into CI / host gates
- define the deployment topology used by CI / host gates and benchmark the Ray
  coordination path under that topology
- ~~freeze the first forensic block field set for the canonical workflow~~
- ~~choose the schema direction explicitly:~~
  - canonical replay/export shape: JSON-LD
  - optional internal transport mirror later: Protobuf
- ~~define transaction-specific authority binding inputs:~~
  - asset or product id
  - facility or zone scope
  - policy snapshot or decision hash
  - device fingerprint handle
- include simulated edge-network conditions in hot-path testing:
  - intermittent connectivity
  - sensor jitter / noise
  - edge hardware latency

### Exit criteria

- sign-off evidence is repeatable, not one-off
- hot-path observability is operator-grade
- `shadow` mode becomes promotion-quality evidence
- the first forensic block contract is fixed enough to build adapters against
- the runtime is stable enough to expose as a real integration boundary
- concurrency results reflect real coordination behavior, not only local happy
  path benchmarks

### Non-goals

- no broad product rebrand
- no general multi-workflow expansion
- no full autonomous robotics stack work

## Q3 2026: Productize The Agent Boundary And State Convergence

This quarter should make SeedCore usable by external agent systems and prove
that digital and physical state can be reconciled deterministically.

### Primary objective

- define the cleanest possible external contract for governed action requests
  and the first multi-agent forensic handshake

### Must-ship items

- stable `AgentActionRequest` contract for the RCT family
- mapping from external agent identity to accountable principal and delegation
- device-bound identity or attestation metadata on the request path
- deterministic response contract with:
  - disposition
  - explanation
  - required approvals
  - trust gaps
  - minted artifacts
- reference adapter or SDK for one current agent platform
- one reference commerce-side adapter for the canonical transaction flow
- gateway support for intent reservation and closure acknowledgement
- edge-to-cloud synchronization contract for Dockerized edge nodes running the
  restricted-transfer boundary
- reconnection and reconciliation rules for restricted transfers under
  intermittent connectivity
- deterministic mapping from gateway request -> decision -> forensic block ->
  replay lookup
- simulated multi-agent handshake between:
  - buyer-side agent
  - seller-side or inventory-side adapter
  - SeedCore authority boundary
- first red-team validation in simulation:
  - coordinate tamper attempt should deny or quarantine
  - stolen session replay should be attributable in forensic logs

### Exit criteria

- one external agent platform can request an RCT action end to end
- SeedCore no longer requires callers to understand internal coordinator
  semantics
- denial, quarantine, and escalation behavior are externally legible
- the edge node can safely reconcile local custody outcomes after reconnect
- the digital transaction and physical verification states can be correlated by
  a single audit id or equivalent forensic join key

### Recommended discipline

- support one platform well
- avoid trying to support every agent framework at once
- support one commerce path well before generalizing to every marketplace

## Q4 2026: Close The Loop, Red-Team It, And Package The Pilot

This quarter should turn the runtime into a buyer- and operator-legible pilot.

### Primary objective

- prove end-to-end governed action with independent verification and adversarial
  resilience

### Must-ship items

- evidence-required closure for selected transfer actions
- authoritative twin settlement integrated into the runtime story
- sensor-grounded closure using Jetson-captured localized telemetry
- operator verification surface ready for live usage
- partner-facing proof flow for post-hoc verification
- one design-partner simulation or controlled pilot package
- Unitree B2 included as the physical custodian / courier actor in the pilot
- scripted zero-trust physical handover demonstrating policy `allow` / `deny`
  against real-time edge telemetry
- audit-trail view showing request, transaction trail, and physical replay side
  by side
- lightweight self-contained verification package that does not require the full
  SeedCore runtime stack
- full red-team package for the canonical workflow:
  - man-in-the-middle coordinate redirect
  - authority leak / replay injection
  - physical double-spend attempt
- operating metrics for:
  - allow / deny / quarantine / escalate rates
  - latency profile
  - parity stability
  - evidence closure rate
  - replay verification success
  - edge reconciliation time
  - time to proof
  - forensic block completeness rate
  - physical vs digital fingerprint match rate

### Exit criteria

- a third party can inspect a completed governed transfer
- a real or simulated external agent can initiate the flow
- the proof surface explains the final result without requiring source-code
  access
- the physical handover path is demonstrated with hardware in the loop, not
  only mocked software components
- the red-team drills produce deterministic quarantine, deny, or replay-visible
  findings instead of ambiguous failure

## Deliverable Map

The delivery order should stay strict.

### Layer 1: Runtime correctness

- hot-path semantics
- parity evidence
- rollback and quarantine behavior
- ~~RESULT_VERIFIER: journal-driven replay verification with authoritative
  fail-closed twin/custody enforcement (RCT v1; coordinator-embedded)~~

### Layer 2: Product contract and delegated authority

- external request schema
- identity / delegation binding
- transaction-specific authority scope
- response contract

### Layer 3: Closure, forensic blocks, and proof

- evidence ingestion
- settlement
- replay and verification consistency
- edge-to-cloud reconciliation
- forensic block packaging

### Layer 4: Pilot packaging

- runbook
- deployment path
- operator flow
- partner proof flow
- red-team drill package
- physical handover packaging

Do not invert this order.

## Metrics That Actually Matter

The year should be measured with a small set of metrics.

### Runtime metrics

- hot-path p50 / p95 / p99 latency
- shadow parity rate
- mismatch root-cause closure time
- dependency freshness violations
- auto-quarantine rate
- RESULT_VERIFIER: jobs enqueued/processed, verification pass vs
  integrity/trust failure counts, quarantine mutations, worker latency
- evidence payload ingestion p50 / p95 latency
- evidence payload size distribution
- forensic block assembly latency

### Workflow metrics

- RCT allow / deny / quarantine / escalate distribution
- approval completeness rate
- evidence closure rate
- replay verification success rate
- edge node reconciliation time after reconnect
- twin-settlement completion time after governed action close
- physical vs digital fingerprint match rate
- red-team drill detection rate

### Product metrics

- time to integrate one external agent
- operator time to explain a decision
- time to investigate a failed transfer
- number of required manual trust-ops steps per transfer
- time for a third-party verifier to validate one exported transfer package
- time to reconstruct one failed handshake from replay artifacts only

## Ownership Model

Even if the team is small, the work should be thought of as four explicit
ownership lanes:

### Runtime lane

- hot path
- policy evaluation
- approval truth
- decision contracts

### Trust lane

- signer provenance
- evidence integrity
- replay verification
- settlement correctness
- forensic block schema and chain integrity
- RESULT_VERIFIER outcomes, quarantine mutations, and coordinator metrics
  (`result_verifier_*`)

### Product lane

- verification surface
- external API contract
- integration guides
- operator runbooks

### Pilot lane

- demo package
- design-partner workflow
- onboarding path
- operational metrics and sign-off
- hardware-in-the-loop validation
- adversarial drill validation

This helps prevent "everything is infra" drift.

## 2026 Risks

The main risks are strategic, not only technical.

### Risk 1: Becoming too broad

Symptom:

- too many workflows, too many surfaces, too much generic autonomy language

Counter:

- keep `Restricted Custody Transfer` as the must-win workflow for the full year

### Risk 2: Staying too internal

Symptom:

- excellent runtime internals, but no external contract that a real agent
  platform can use

Counter:

- ship the Agent Action Gateway in Q3 even if it is narrow

### Risk 3: Over-optimizing before productizing

Symptom:

- spending large amounts of time on generalized performance or architecture
  cleanup before the integration and proof story is product-ready

Counter:

- optimize only where it is required for hot-path promotion or pilot readiness

### Risk 4: Letting proof quality drift

Symptom:

- a good policy engine but weak replay, settlement, or evidence closure

Counter:

- treat verification and evidence as first-class release gates

### Risk 5: The edge-to-cloud reality gap

Symptom:

- the governed transfer works in centralized simulation but breaks under
  intermittent networking, sensor noise, or physical hardware latency

Counter:

- require Q2 hot-path testing to include degraded edge-network conditions
- require Q4 pilot evidence to come from actual hardware in the loop

### Risk 6: Verification package dependency bloat

Symptom:

- a third party needs too much internal SeedCore infrastructure just to verify
  one completed transfer

Counter:

- keep the Q4 verification package lightweight and self-contained
- rely only on standard cryptographic primitives and exported proof artifacts,
  not the full Kubernetes / Ray runtime

### Risk 7: Split-brain forensic schemas

Symptom:

- one internal transport schema and one external audit schema diverge before the
  first pilot is stable

Counter:

- freeze one canonical replay/export contract first
- add transport-specific encodings only after the external field set stabilizes

## 2026 Decision Rule

When choosing between two tasks, prefer the one that makes this sentence more
true:

> An external agent can request a restricted transfer through SeedCore,
> SeedCore can govern the action safely across the cloud and edge boundary, and
> a third party can verify both the digital transaction and the physical outcome
> afterward.

If a task does not strengthen that sentence, it is probably not on the critical
path.

## End State For This Year

SeedCore has had a successful 2026 if, by year end, it can honestly claim:

- we have one governed high-trust workflow that is externally integrable
- we have one operator-grade proof surface for it
- we can prove both authorization and post-action closure
- we can show denial, quarantine, and escalation as strengths, not edge cases
- we can demonstrate the workflow with physical hardware and edge telemetry in
  the loop
- we can replay the workflow as a coherent forensic chain after the fact
- we occupy a necessary layer between frontier agents and real-world execution

That is enough to matter.

## 2027 Continuation

After 2026 closure, the next-stage high-vertical deployment direction is
tracked in:

- [seedcore_2027_high_vertical_direction.md](/Users/ningli/project/seedcore/docs/development/seedcore_2027_high_vertical_direction.md)

This continuation keeps the same trust-boundary model while adding staged
hardware-bound execution identity for IGX/Jetson edge deployments.
