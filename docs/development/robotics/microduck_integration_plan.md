# Microduck Integration Plan

Date: 2026-09-17
Status: Active next-stage plan; adapter and hardware integration not implemented

## Outcome And Scope

Demonstrate one short movement that an agent proposes, SeedCore admits,
Microduck attempts, and the verifier closes with traceable evidence. Start
with simulation and a compatible upstream policy. Add hardware after command
contracts and failure cases are reproducible.

The [active queue](../current_next_steps.md) owns sequencing. The
[source ledger](microduck_source_ledger.md) distinguishes supplied claims,
upstream observations and unresolved facts.

## Runtime Boundaries

```text
Agent / operator proposal
  -> ActionIntent / Agent Action Gateway
  -> PDP allow or deny
  -> scoped ExecutionToken
  -> SeedCore robot execution boundary
       validate token, scope, freshness, revocation, replay
       bind bounded session to endpoint and policy identity
  -> Microduck RPC client
  -> robotd local control / safety / sole bus owner
  -> observed outcome
  -> action-bound telemetry and receipt
  -> evidence bundle / RESULT_VERIFIER / replay
```

Network admission and evidence processing must stay outside the local control
loop. An admitted action can still be refused or preempted locally; report the
actual outcome. The following interfaces are proposed SeedCore behavior;
exact upstream methods and schemas must come from the pinned runtime.

| Surface | Proposed scope | Required boundary |
| --- | --- | --- |
| Health/state | Read-only observation | Endpoint identity, capture time, source profile, freshness |
| Bounded motion | Velocity/duration within a reviewed envelope | PDP, token, endpoint/action binding, revocation, session deadline |
| Stop/cancel | Terminate motion using local safety behavior | Available during network loss; no implicit permission to resume |
| Enable/rise/posture | Separate state-changing operation | Explicit intent and reviewed preconditions |
| Policy/runtime update | Artifact/change-management operation | Pinned provenance, compatibility, admission, rollback |
| Raw joint/bus access | Onboard runtime ownership | Never expose as a remote model tool |

## M0: Integration Manifest

Record runtime/RL URLs and commits; board, firmware and IMU revisions; endpoint
and transport; policy digest/provenance; observation/action shape; joint
ordering, home pose, normalization, scaling and control period. Capture command
and telemetry schemas, units, sequencing, errors, local watchdog behavior,
client ownership and startup posture. Version the simulation model separately.

Resolve base-height targets from the model rather than overall robot height.
Measure sensor alignment rather than assuming one bus transaction samples all
devices simultaneously.

## M1: Read-Only Adapter And Simulation

Use explicit profiles for protocol fixtures, the daemon with fake I/O, MuJoCo
body simulation, and physical hardware. Their evidence identities must differ.
Missing hardware fails the requested hardware profile.

Capture health/state first. Check malformed responses, disconnect/reconnect,
stale timestamps and non-finite values. Compare frozen observations and ONNX
outputs against the training reference within a declared numeric tolerance.

The generic SeedCore simulator can test authority plumbing. Microduck
locomotion acceptance requires the selected Microduck model/runtime pair.
Record these as separate results.

## M2: One Bounded Motion Session

Reuse the gateway and HAL admission path. Verify the adapter cannot reach
motion through legacy/dev bypasses or direct remote socket access. Inventory
gamepad, BLE, WebRTC and local tools before claiming all remote motion is
governed.

Define the session before streaming:

- One token admits one bounded action/session, endpoint, policy identity,
  command envelope and maximum duration.
- Claim the action once; refresh commands with sequence numbers inside that
  session instead of replaying its token as new actions.
- Refresh cannot widen scope, change policy, extend expiry or revive a
  completed/revoked session.
- Revocation/expiry stops refresh within a specified bound; stale intent
  invokes the reviewed local stop behavior.
- Reconnect reconciles session state and requires fresh admission where
  necessary. Never replay buffered stale motion.
- Cancellation/local preemption terminates the attempt and is recorded.
  Resumption requires valid admission.

This session design is proposed. Reconcile it with existing single-use token
and replay semantics before implementation. Transport heartbeat alone is
insufficient: a gateway can stay alive after a planner stops producing intent.
Track command freshness and action deadline independently.

## M3: Evidence And Closure

Extend the [physical telemetry contract](../evidence/physical_telemetry_processing_contract.md)
and [hardware evidence contract](../evidence/hardware_anchored_telemetry_mvp_contract.md).
Reuse existing gateway/verifier schemas; document versioned additions first.

Bind each attempt to action/token/session, endpoint, runtime revision, policy
digest, command bounds, observed start/end state, timestamps, sequence coverage,
stop/preemption events and outcome. Use monotonic time for local duration with
explicit clock mapping across systems. Distinguish measurements from estimates.

An RPC acknowledgement proves receipt, not completion. Missing, stale,
mismatched or contradictory telemetry cannot become successful closure.
Simulator receipts remain simulation evidence. Hardware signing claims require
an enrolled signer and actual captured proof.

## Acceptance Cases

| Case | Required result |
| --- | --- |
| Valid bounded action | One attempt with correlated evidence; verifier decides closure |
| Missing/expired/forged/wrong-endpoint token | No motion dispatch |
| Reused token or duplicate sequence | No second action; documented session/idempotency behavior |
| Revocation during motion | Refresh ceases within the defined bound; stop evidence captured |
| Gateway/planner partition | Stale intent deadline applies independently of heartbeat |
| Local operator preemption | Remote motion yields; no automatic resume |
| Policy/observation mismatch | Reject before enabling policy-driven motion |
| Non-finite/stale sensor state | Defined local response; failed/incomplete evidence closure |
| Restart/reconnect | No unintended motion or queued-command replay |
| RPC success without telemetry | No verified completion |
| Requested hardware unavailable | Explicit failure; no simulator fallback |

These are proposed SeedCore acceptance criteria, not claims that upstream
already implements every row.

## M4: Supervised Hardware

Select one robot and bounded workspace. Measure command-to-observation latency,
control timing, stop latency, sensor freshness, battery/thermal behavior and
communication-loss response. Set numeric limits from measurements and the
reviewed hardware profile.

Begin with read-only capture and reviewed posture conditions, then short
low-speed movement. Record operator supervision, local stop control, versions
and rollback. Require reproducible allowed, denied and interrupted cases with
replay before expanding speed, terrain, duration or behaviors.

## M5: Learning And Promotion

Evaluate the baseline before training a candidate. Preserve configuration,
seeds, model/actuator versions, normalization, export provenance, policy hash
and episodes. Compare tracking, falls, saturation, action changes, thermal
proxies and observation mismatch.

Training produces candidates. Evaluation does not install a policy or admit
motion. Promotion validates compatibility, retains the previous artifact for
rollback, and binds the selected version to later execution evidence.

## Completion Evidence

A reviewer must be able to reproduce the pinned simulation, inspect allowed
and denied/interrupted actions, reconstruct the endpoint/policy, and see why
RESULT_VERIFIER accepted or refused closure. Hardware and policy promotion
have separate later acceptance evidence.
