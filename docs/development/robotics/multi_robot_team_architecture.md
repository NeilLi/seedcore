# Multi-robot team architecture

Date: 2026-09-18
Status: Implemented orchestration contracts and local runtime; live Microduck adapter pending.

SeedCore can now represent a team of independently advised robots, plan from a
shared observation, submit concurrent governed actions, and require verified
closure before the next round. Competitive football and cooperative work use
the same runtime. This does **not** yet make the standalone Microduck football
script a governed SeedCore application.

## Responsibilities

| Layer | Implemented responsibility | Does not own |
| --- | --- | --- |
| Organ | Agent/robot/endpoint roster and mission reservations; reserved agents cannot be removed through `remove_agent` | Execution authority or a distributed lease |
| Agent | Package one capability- and duration-bounded proposal; enforce execution affinity, command binding and freshness before tools | Global tactics, peer assignment, token minting |
| Cognitive | Independent per-agent JSON advisors restricted to `RobotProposal`; shared snapshot with isolated copies | Tool selection, endpoints, principal identity, policy, credentials |
| Coordinator | Planning barrier, resource conflict checks, concurrent governed dispatch, closure barrier, terminal halt on uncertainty | Joint control, gait, physical atomicity, evidence self-certification |
| Existing PDP / HAL / RESULT_VERIFIER | Admission, token signature/scope/expiry/single-use/revocation, bounded execution, authenticated evidence closure | Trusting an LLM or driver acknowledgement as authority |

The high-frequency posture, gait, velocity and stop watchdog stay on the robot
runtime. LLM decisions are bounded skill proposals, not motor commands. Each
agent can use its own GPT/cognitive-service adapter, persona, or model; the
orchestrator itself has no provider dependency and performs no API calls.

## Round lifecycle

```text
trusted roster + shared observation (mission, sequence, observation hash)
    -> concurrent cognitive advisors, one per robot
    -> all-proposals barrier: capability, duration, freshness, resource checks
    -> distinct action tasks -> existing Coordinator/PDP -> Agent -> HAL
    -> authenticated RESULT_VERIFIER closures, one per action
    -> all-verified barrier -> next observation/round
                     failure/uncertainty -> halt + retain reservations
```

Every command binds mission, round, observation sequence/hash, agent, robot,
endpoint, tool, runtime profile, start deadline and duration. Its canonical hash
is included in the action parameters for the existing token payload binding.
Task IDs are stable for the same mission/round/agent. Proposals contain no
token, tool name, endpoint, or routing fields; unexpected fields are rejected.

Planning failure or conflicting exclusive claims submits **zero** actions.
After fan-out, execution is not atomic: one robot may succeed while another is
denied or unreachable. Successful closures are retained; failed/uncertain
actions are not retried. The runtime invokes the configured admitted halt path
and refuses subsequent rounds. `halt_acknowledged` means that adapter returned,
not proof that physical motion stopped. A failed halt requires operator action.
Cancellation also requests halt. Endpoint-local expiry/watchdogs must remain
effective even if cancellation cannot stop an already-delivered request.

Only a trusted verifier bridge may return `ActionClosure`. It must authenticate
the evidence, resolve a successful RESULT_VERIFIER record and bind it to the
exact task, command, token and endpoint. The runtime additionally checks task,
mission, round, observation, agent, robot, endpoint and command hash. A driver
`success` or `actuator_ack` cannot open the next-round barrier.

## Integration hooks

- `Organ.reserve_robot_team(mission)` checks that all assigned agents exist and
  reserves their identities and endpoints. Reservations survive runtime failure
  in memory; only explicit reconciliation releases them.
- `BaseAgent.prepare_robot_action(...)` produces the existing `TaskPayload`
  with `type=action` and `governance.require_action_intent=true`. It does not execute.
  `BaseAgent.execute_task` now rejects mismatched or unguided team commands
  before tool invocation, in addition to the existing RBAC/evidence path.
- `CognitiveAdvisoryContractBuilder.robot_team_planner(propose)` wraps an async
  JSON adapter. The adapter receives role, objective, skills, shared observations
  and the proposal schema. It must return just that schema, not an SDK response.
- `Coordinator.create_robot_team_runtime(mission, planners, verify=..., halt=...)`
  is a **trusted in-process composition hook**, not a new public API or LLM tool.
  Reserve the team in its Organ first. It calls the existing
  `Coordinator.route_and_execute` for each task; it never calls robot sockets or
  `Organism` directly. It rejects locally overlapping mission runtimes.

To end an idle mission, call `await runtime.halt_mission()`. For an active round,
cancel and await that round first; cancellation records partial/uncertain
outcomes in `runtime.last_result`. After authentic evidence settlement and
session revocation, an operator may call
`Coordinator.release_robot_team_runtime_after_reconciliation(mission_id)` and
`Organ.release_robot_team_after_reconciliation(mission_id)`. These are trusted
lifecycle operations, not model actions or automatic error cleanup.

The underlying implementation lives in `src/seedcore/robotics/`: `contracts.py`,
`roster.py`, `agent.py`, `cognitive.py`, and `coordinator.py`. A mission supports
2–32 robots with one accountable agent per robot, unique endpoints, explicit
roles and an explicit simulation/hardware profile. Mixing profiles is rejected.
Use `runtime.run_round(observation)` only with a trusted, coherent telemetry
snapshot. Each next round must have a strictly increasing sequence.

`verify` and `halt` are mandatory server-configured async ports. Neither has a
permissive default. Do not manufacture verification records to connect a demo.
The halt adapter must revoke/stop sessions through the policy-admitted safety
path; arbitrary ungoverned STOP calls are not an acceptable implementation.

## Football and cooperative work

- Football: assign blue `attack +x`, orange `attack -x`; supply ball and both
  robot states in each observation. Each advisor proposes its own allowed skill.
  Team mode describes intent; field rules, collision avoidance and motion
  limits still require deterministic checks in policy/adapter/controller.
- Cooperative inspection: agents inspect disjoint work areas concurrently.
  Configure exclusive workcell/object reservations outside the model. Advisors
  may add reservations but cannot remove configured ones.
- Handoff: complete and verify the preparation round, then supply a new trusted
  observation for the handoff round. Do not model dual ownership of an object
  as two conflicting exclusive claims. A genuinely synchronized lift/transfer
  needs an admitted joint-action protocol, not just concurrent task dispatch.

## Offline demonstration and tests

From the repository root:

```bash
PYTHONPATH=src .venv/bin/python scripts/robotics/plan_team_demo.py --scenario football
PYTHONPATH=src .venv/bin/python scripts/robotics/plan_team_demo.py --scenario work
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_robot_team_runtime.py
```

The demos print proposed governed tasks only: fixture observations,
deterministic advisors, no GPT calls, no tokens, no robot movement and no fake
proof of a successful match. Tests use explicitly labeled fake verifier ports
to check orchestration, not to certify physical execution.

Local verification on 2026-09-18: 45 new team tests passed; the combined team,
agent, coordinator-service and generic-simulator run passed 94 tests; the organ
suite passed 17. The Q2 verification script passed (its opt-in Postgres lane was
skipped). The authorization RFC script passed 79 unit tests, then its live
phase stopped because the local API at `127.0.0.1:8002` was unavailable. No live
authorization or Microduck acceptance result is claimed.

## Remaining live-integration gates

1. Implement the [Microduck M1–M2 adapter](microduck_integration_plan.md): distinct
   endpoint bindings, authenticated telemetry, skill argument validation,
   velocity/acceleration envelope, session sequence, start deadline, bounded
   duration, independent expiry/staleness watchdog and revocation. The example
   `microduck.bounded_skill` tool is a contract placeholder, not registered here.
2. Admit the `ROBOT_SKILL` action and tool under explicit policy/agent RBAC;
   preserve payload/endpoint binding through the HAL's token validation and
   single-use claim. Unknown skills/policies must fail closed.
3. Implement trusted verifier and halt adapters; prove denial, replay, stale
   telemetry, revoked tokens, partial execution and stop failure end-to-end.
4. Wire the two cognitive JSON providers and measure planning latency against
   telemetry freshness. Slow LLMs should provide tactics for a fast local skill
   planner; do not make old observations acceptable just to hide latency.
5. Add durable mission journals/leases before multi-replica or crash-resume use.
   Current reservations and replay counters are **single-owner and in-memory**.
   A process restart must reconcile/revoke outstanding sessions before another
   mission is started; automatic resume is not supported. `remove_agent` is
   guarded, but actor crashes/respawn still need controller-side fencing.

This upgrade is the team orchestration layer, not physical safety certification
or evidence that Microduck walking/football performance is solved.
