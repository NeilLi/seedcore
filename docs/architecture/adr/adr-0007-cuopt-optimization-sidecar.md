# ADR 0007: Treat NVIDIA cuOpt as an Optional Optimization Sidecar

- Status: Accepted
- Date: 2026-05-15
- Scope: Optimization-service boundary for routing, dispatch, scheduling, and logistics planning. Does not change PDP authority, RESULT_VERIFIER semantics, custody-state truth, or evidence-closure rules.
- Related: [ADR 0001: Keep the PDP Stateless and Synchronous at Decision Time](./adr-0001-pdp-hot-path.md), [ADR 0003: Adopt an IGX Thor Trusted Edge Profile for High-Regulation SeedCore Deployments](./adr-0003-igx-thor-trusted-edge-profile.md), [ADR 0004: Coordinator-Embedded RESULT_VERIFIER With Journal Polling and Fail-Closed Twin Mutation](./adr-0004-result-verifier-runtime.md), [ADR 0005: Preserve Replayable Evidence for Governed Digital Twin State Transitions](./adr-0005-replayable-evidence-governed-state-transitions.md), [Current Next Steps](../../development/current_next_steps.md), [SeedCore 2026 Execution Plan](../../development/seedcore_2026_execution_plan.md), [Collectible Rare-Shoe RCT Demo Spec](../../development/rare_shoes_collecting_transfer_demo_spec.md)

## Context

SeedCore's current commercial wedge is `Restricted Custody Transfer`:
policy-bound AI execution, delegated authority, signed physical telemetry, and
replayable proof. The current rare-shoe vertical scene and Q3/Q4 execution
plan make the logistics problem visible:

- an external buyer or collector agent can express intent
- SeedCore maps that intent to accountable principal, commerce refs, and
  custody scope
- physical handoff is constrained by vault, courier, device, zone, and time
  window
- edge telemetry and forensic evidence close the workflow

This naturally raises the question of whether SeedCore should depend on an
optimization stack such as NVIDIA cuOpt for route planning, dispatch,
scheduling, or multi-stop logistics.

NVIDIA cuOpt is relevant because it is a GPU-accelerated optimization stack for
routing and mathematical optimization workloads. It can plausibly improve
route-plan generation for:

- multi-vault or multi-stop custody pickup
- courier assignment under time windows
- dispatch scheduling for bonded logistics
- robotics or warehouse path planning at pilot scale
- exception rerouting after quarantine, timeout, or route disruption

However, SeedCore's moat is not route optimality. It is the trust boundary
between AI intent and governed physical execution. A route optimizer can answer
"what plan is efficient?" It must not answer "is this physical custody
movement authorized?" or "is this evidence sufficient for closure?"

Without a durable decision, future implementation work could accidentally move
optimization output into the authority path, introduce GPU/runtime dependency
into the PDP hot path, or make NVIDIA infrastructure a hidden prerequisite for
the current RCT demo. This ADR freezes the boundary before that drift happens.

## Decision

SeedCore may integrate NVIDIA cuOpt as an **optional optimization sidecar** for
route, schedule, dispatch, and logistics-plan proposals.

SeedCore must not treat cuOpt as:

- a PDP authority dependency
- a custody-state source of truth
- an evidence-closure verifier
- a RESULT_VERIFIER dependency
- a requirement for the rare-shoe RCT fixture demo
- a requirement for the Q3 agent-boundary productization path

cuOpt outputs are advisory candidate plans. Before any custody movement is
authorized, SeedCore must post-validate the candidate plan against its own
policy, authority, evidence, and state-convergence rules.

### Required Boundary

The allowed control flow is:

```text
AI / commerce intent
-> SeedCore request normalization and policy preflight
-> optional optimizer proposal
-> SeedCore post-validation
-> bounded custody authority
-> signed edge telemetry
-> RESULT_VERIFIER / replayable proof
```

The forbidden control flow is:

```text
AI / commerce intent
-> optimizer route plan
-> custody movement authority
```

An optimized route is not authority. It is a candidate input to authority
evaluation.

### Optimizer Backend Contract

SeedCore should expose an internal optimizer boundary with a backend selection
shape equivalent to:

```text
SEEDCORE_OPTIMIZER_BACKEND=none|fixture|cuopt
```

The first implementation should use `none` or `fixture`. The `cuopt` backend
should be added only when a pilot, simulation, or demo requires real
multi-stop, fleet, route, schedule, or dispatch optimization.

The canonical optimizer artifact is a `RoutePlanProposal` or equivalent
projection. At minimum, it should bind:

- `route_plan_id`
- `workflow_join_key`
- `asset_refs`
- `origin_zone`
- `destination_zone`
- `allowed_actor_refs`
- `allowed_device_refs`
- `authority_window`
- `forbidden_zones`
- `service_time_windows`
- `solver_backend`
- `solver_version`
- `solver_objective`
- `candidate_stops`
- `route_plan_hash`

`route_plan_hash` may appear in forensic linkage and replay bundles, but it is
not sufficient to mint authority.

### Post-Validation Requirements

SeedCore must reject or quarantine any optimized plan that violates:

- asset and workflow binding
- approved registration or admissibility state
- allowed courier, robot, or edge-device identity
- authorized origin, destination, or intermediate zone
- authority time window
- risk-state restrictions such as quarantine, legal lock, or pending telemetry
- telemetry and closure evidence requirements
- public/operator proof redaction rules

If the optimizer is unavailable, SeedCore must not fail the core RCT happy path
unless the specific workflow explicitly requires optimization. The default
fallback is deterministic fixture planning, static route planning, or operator
review.

## Rationale

- SeedCore's core product boundary is governed execution, not logistics
  optimization. Keeping cuOpt outside the authority path preserves that
  distinction.
- ADR 0001 requires the PDP to remain stateless and synchronous at decision
  time. A GPU solver, NIM service, or external optimization server must not
  become a synchronous PDP dependency.
- ADR 0003 already introduces NVIDIA edge infrastructure as a possible trusted
  physical execution lane. This ADR prevents that NVIDIA relationship from
  expanding silently into the authority core.
- The rare-shoe RCT demo does not need route optimization to prove the trust
  runtime. It needs registration, gateway admission, signed edge telemetry,
  proof projection, and replay.
- cuOpt becomes valuable when the demo or pilot shifts from one handoff to
  many constrained handoffs: multiple pickups, multiple couriers, hard
  delivery windows, fleet utilization, warehouse dispatch, or robotics routing.

## Cost And Dependency Controls

cuOpt can increase cost and operational complexity through GPU infrastructure,
cloud GPU runtime, NVIDIA AI Enterprise support lanes, NIM deployment,
container operations, and GPU scheduling overhead.

SeedCore must therefore treat cuOpt as opt-in and cost-bounded:

- keep `SEEDCORE_OPTIMIZER_BACKEND` defaulting to `none` or `fixture`
- keep optimizer calls outside the PDP hot path
- set a per-call solve-time budget
- set per-environment or per-tenant optimizer quotas
- cache normalized route-plan proposals where safe
- batch solve requests when route density justifies GPU use
- keep a deterministic fallback backend
- avoid sending raw authority-tier evidence to the optimizer
- redact sensitive asset, party, and custody metadata before optimization

The adoption trigger for real cuOpt is not "NVIDIA has a relevant stack." The
trigger is a concrete route, dispatch, or scheduling pain that simple fixtures
or deterministic heuristics cannot credibly represent.

## Consequences

- The current rare-shoe RCT implementation order remains unchanged. Slice 1-4
  should not grow a cuOpt dependency.
- A future logistics, warehouse, robotics, or multi-asset custody pilot may add
  a cuOpt backend behind the optimizer boundary without changing PDP,
  RESULT_VERIFIER, or replay semantics.
- Route-plan evidence becomes replay-visible when used, but route-plan evidence
  is not policy truth.
- GPU cost remains controllable because the default backend is not cuOpt.
- Vendor lock-in risk is reduced by keeping the optimizer interface generic and
  preserving deterministic fallback behavior.
- NVIDIA stack adoption remains compatible with ADR 0003, but remains bounded:
  NVIDIA can help plan or execute physical work; SeedCore decides whether that
  work is authorized and whether evidence closes it.

## Alternatives Considered

- **Adopt cuOpt as a required SeedCore substrate.** Rejected because the current
  must-win workflow does not require GPU optimization, and making cuOpt required
  would add cost and vendor dependency before the product boundary needs it.
- **Ignore cuOpt entirely.** Rejected because future logistics, robotics, and
  multi-stop custody workflows may benefit from a serious optimization backend.
  The right move is a boundary, not avoidance.
- **Place cuOpt inside the PDP hot path.** Rejected because this conflicts with
  ADR 0001 and would turn route-solving latency, GPU availability, or solver
  runtime failures into authority availability risks.
- **Treat cuOpt output as sufficient custody authority.** Rejected because an
  optimized route does not prove delegation, registration, admissibility,
  physical identity, telemetry integrity, or evidence closure.
- **Build only a cuOpt-specific integration surface.** Rejected because SeedCore
  should preserve a generic optimizer interface with deterministic fixtures and
  fallback backends.

## Adoption Triggers

The `cuopt` backend may be implemented when at least one of these is true:

- a design partner requires multi-stop custody routing or dispatch scheduling
- a demo needs credible fleet, courier, robot, or warehouse optimization
- deterministic fixture plans are no longer sufficient to explain the workflow
- route optimization materially affects pilot cost, SLA, or utilization
- the Q4 hardware-in-the-loop pilot expands from one handoff to constrained
  route planning across multiple physical actors or zones

Until one of these triggers is true, SeedCore should keep cuOpt at the ADR and
interface-design level only.

## External References

- [NVIDIA cuOpt documentation](https://docs.nvidia.com/cuopt/)
- [NVIDIA cuOpt GitHub repository](https://github.com/NVIDIA/cuopt)
- [NVIDIA: Optimize Supply Chain Decision Systems Using NVIDIA cuOpt Agent Skills](https://developer.nvidia.com/blog/optimize-supply-chain-decision-systems-using-nvidia-cuopt-agent-skills/)
- [NVIDIA AI Enterprise licensing guide](https://docs.nvidia.com/ai-enterprise/planning-resource/licensing-guide/latest/pricing.html)
