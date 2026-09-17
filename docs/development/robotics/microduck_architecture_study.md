# Microduck Architecture Study

Date: 2026-09-17
Status: Supporting study; upstream architecture informs the planned integration

Adapted from the [supplied architecture study](sources/microduck_architecture_user_supplied.md).
The [source ledger](microduck_source_ledger.md) records revisions and corrections.
This document describes the robot boundary; the
[integration plan](microduck_integration_plan.md) proposes SeedCore's adapter.

## System Shape

```text
Remote agent / application / operator
  -> high-level motion intent
  -> network transport (for example WebRTC)
  -> JSON-RPC over onboard Unix sockets
  -> robotd
       local command handling, watchdog and control
       sensors -> observation -> ONNX policy -> safety -> targets
  -> shared Dynamixel UART
       IMU board + 15 servos
  -> state/health observations returned to clients
```

The upstream workspace separates robot control, configuration, Bluetooth,
gamepad input, media and updates into daemons. Its architecture makes
`robotd` the motor-control owner; clients use an intent interface.
See the [upstream architecture](https://github.com/pollen-robotics/microduck/blob/768e1922715942d8c6aa5254c6d1cd35cf099482/docs/design/architecture.md).

| Component | Responsibility in the study |
| --- | --- |
| Remote agent | Planning, dialogue, perception and proposed intents |
| `mediad` | WebRTC media/control transport |
| `btd` | BLE transport to onboard services |
| `padd` | Gamepad client |
| `configd` | Configuration and identity |
| `updaterd` | Release/update lifecycle |
| `robotd` / control library | Local inference, motor control and safety |

Transport authentication identifies a caller; it does not establish a
SeedCore PDP decision or ExecutionToken.

## Control And Bus Ownership

The supplied study describes a 50 Hz loop, a shared 1 Mbps
`/dev/ttyS2` Dynamixel bus, IMU ID 200, and fifteen servo IDs distributed
between legs and neck/head/mouth. Treat those as revision-specific hardware
details to record in the integration manifest.

The pinned design adds an endpoint advisory lock alongside `TIOCEXCL`;
privileged processes are not excluded by tty exclusivity alone. A control
tick has a combined sensor read and a separate target write. Shared transport
does not imply simultaneous sampling or zero skew.
[Control design](https://github.com/pollen-robotics/microduck/blob/768e1922715942d8c6aa5254c6d1cd35cf099482/docs/design/robotd-design.md)

Only the onboard runtime should translate admitted high-level motion into
motor targets. Network latency and model inference delays must remain outside
the balance/control loop. A nominal 20 ms period is a timing target, not proof
of hard real-time performance; measure deadlines and jitter on the selected
board.

## Policy Interface

The current studied policy interface is `[1,61] -> [1,14]`; the mouth is
outside the policy action vector. The [RL study](microduck_rl_study.md)
covers the layout and export checks.

Distinguish the number of physical servos, the action-vector size, and the
subset moved by a specific behavior. These are different quantities.

## Safety And Client Control

A watchdog, local safety checks, policy state and operator control constrain
execution. Do not assume the attachment's strict gamepad/app/LLM hierarchy,
session lease, or guaranteed standing/seated response is already implemented
for every failure. Confirm behavior from the selected revision and tests.

Likewise, the attachment's blanket claim that all configuration is watched
through `inotify` is too broad: the pinned control design describes
restart-bound settings and specific reload exceptions.
[Configuration behavior](https://github.com/pollen-robotics/microduck/blob/768e1922715942d8c6aa5254c6d1cd35cf099482/docs/design/robotd-design.md#42-params)

SeedCore's integration must explicitly define client ownership, stale-intent
handling, cancellation, restart and policy-change behavior. A local stop or
refusal overrides an admitted command; evidence records that interruption.

## SeedCore Mapping

1. An accountable Agent turns a proposal into an ActionIntent.
2. The PDP evaluates it and may issue a scoped, revocable ExecutionToken.
3. The robot execution boundary validates the token and bounded session.
4. The adapter submits compatible intent to the onboard runtime.
5. Local control attempts the action within its own constraints.
6. Telemetry and receipts bind the actual result to that admitted action.
7. RESULT_VERIFIER decides closure using the existing evidence contract.

The onboard runtime is not assumed to understand SeedCore tokens. That
integration is planned work, and alternate remote command paths must be
accounted for before claiming enforced coverage.
