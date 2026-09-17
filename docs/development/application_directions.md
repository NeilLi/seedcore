# Application Directions

Date: 2026-09-17
Status: Canonical next-stage portfolio decision

The next development stage focuses on **Microduck and related robotics
integration**. The immediate outcome is one observable robot action whose
proposal, permission, physical attempt, and result can be explained and
replayed through SeedCore.

## Portfolio Decision

| Direction | Role now | Next-stage work |
| --- | --- | --- |
| Microduck | Primary robotics integration target | Contract inventory, simulation, bounded intent adapter, telemetry, failure drills, supervised hardware |
| Shared trust runtime | Required foundation | Preserve Agent/PDP/token/revocation/evidence boundaries; extend where the robot contract requires it |
| Robot learning | Supporting experiment lane | Reproduce an upstream policy; evaluate candidates before separately reviewed hardware promotion |
| Rare-shoe RCT | Governed-execution and regression reference | Maintain gates and reuse proof patterns; visual/commercial expansion deferred |
| Reachy, WAM/VLA, other robots | Related reference material | Reuse lessons that unblock Microduck; additional hardware rollouts deferred |
| City, producers, journeys, craft and creative applications | Deferred expansion | Preserve prototypes, contracts and backlog for a later portfolio decision |

Microduck integration is planned work. Repository inspection found HAL
interfaces, Reachy drivers, a generic robot simulator, token/revocation checks
and evidence tooling, but no Microduck-specific driver or adapter. The generic
simulator does not establish Microduck dynamics or hardware readiness.

## First Demonstrable Outcome

Use a pinned Microduck simulator/runtime pair to demonstrate one short,
bounded velocity intent followed by a stop. Show the accountable principal,
PDP result, token constraints, endpoint and policy identity, observed state,
and final verifier disposition. Pair the allowed case with expired/revoked
authority, lost intent stream, and missing evidence cases.

Progress to supervised hardware after simulator contract and failure tests.
Select speed, duration, workspace, freshness and stop limits from the chosen
hardware and measured behavior before admitting physical motion.

The [integration plan](robotics/microduck_integration_plan.md) defines the work;
[current next steps](current_next_steps.md) owns its sequence.

## Boundaries

SeedCore owns admission and proof. The onboard runtime owns its control loop,
bus and local safety behavior. A valid token cannot compel the robot to ignore
local safety. An upstream RPC endpoint or learned policy cannot substitute for
SeedCore authorization.

Policy download, promotion, motor enable, posture transitions and motion need
separately defined authority and operational conditions. PPO results support
evaluation; they do not approve installation or execution.

The [policy gates](policy_gate_matrix.md),
[token lifecycle](trust-runtime/execution_token_lifecycle_management.md) and
[flywheel boundary](seedcore_flywheel_harness.md) continue to apply.

## Deferred Work And History

The [applications index](applications/README.md) retains RCT, city, producer,
journey and experience work. No production vertical or deployment is activated
by this decision. The
[previous portfolio](archive/historical/application_directions_before_microduck_2026-09-17.md)
and [previous queue](archive/historical/current_next_steps_before_microduck_2026-09-17.md)
preserve the preceding RCT/city sequencing.
