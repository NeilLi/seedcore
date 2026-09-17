# Microduck Architecture Study

Status: Supporting research

This study summarizes the architecture of Microduck, the robotics project
developed by Pollen Robotics, with emphasis on how remote LLMs or agents
coordinate with onboard daemons, bus ownership, and hardware to achieve safe,
precise motion control.

The central architectural invariant is: **intents, not motor writes**. Remote
reasoning may propose high-level actions, while the onboard control daemon
retains real-time authority over policy execution, safety checks, and the
actuator bus.

## 1. High-Level Architecture Overview

```text
 [ Remote Cloud / LLM / Agent ]
   │  High-level reasoning, vision-language, and tool selection
   │  Transmits semantic intents such as target velocity, gaze, or sit
   ▼
 [ Network Boundary / WebRTC / Rendezvous Gateway ]
   │  Heartbeat, deadman tracking, and token authentication
   │  JSON-RPC 2.0 (NDJSON) over local UNIX sockets
   ▼
 [ microduck Onboard Linux System ]
   ├── configd (/run/configd.sock)
   │     Wi-Fi, BLE bonding, robot identity, and reboot
   ├── btd
   │     BLE transport forwarding into configd/robotd
   ├── updaterd
   │     A/B updates, rollbacks, and policy fetching
   │
   └── robotd (/run/robotd.sock)
         Autonomous safety and real-time authority
         │
         ├── Authority arbiter: gamepad / local > app > remote LLM
         ├── Deadman / heartbeat watchdog
         ├── Joint and thermal limiters / fall detector
         ├── 50 Hz real-time control loop
         │     ├── ONNX Runtime locomotion/manipulation policy
         │     └── duck_control::bus::DynamixelIo
         │           TIOCEXCL exclusive lock
         ▼
 [ Hardware Bus: single shared 1 Mbps UART ]
   ├── ID 200: imu_to_dxl v2 board
   ├── ID 10–14: right leg, 5 × Dynamixel XL330 servos
   ├── ID 20–24: left leg, 5 × Dynamixel XL330 servos
   └── ID 30–34: neck, head, and grasping beak, 5 × Dynamixel XL330 servos
```

## 2. Remote LLM Versus Onboard Daemons

### Remote LLM or agent

The remote model acts as a high-level planner and multimodal observer. It can:

- ingest camera frames through the WebRTC media pipeline and receive IMU,
  battery, and temperature summaries;
- perform tool calling, goal planning, and dialogue logic; and
- produce bounded commands such as `robot.move(vx, vy, yaw_rate)`,
  `robot.head(pitch, yaw)`, or `robot.loadPolicy("roller")`.

It does not command raw PWM, motor angles, or millisecond joint trajectories.
Network latency, jitter, and inference pauses make a remotely hosted dynamic
biped balance loop unsafe and physically impractical.

### `robotd`

`robotd` is the real-time motor authority, safety gatekeeper, and local policy
runner. It:

- runs a deterministic 50 Hz, 20 ms control loop;
- executes local reinforcement-learning policies through ONNX Runtime for
  behaviors such as balance, walking, standing after a fall, and wheeled
  locomotion; and
- translates high-level intent into target vectors consumed by the local
  neural policy.

The control loop must not synchronously block on external RPC calls.

## 3. Bus Ownership, Locking, and Safety Coordination

### Hardware bus ownership

Microduck shares one UART bus (`/dev/ttyS2` at 1 Mbps) across the Dynamixel
actuators and the IMU coprocessor. `robotd` opens the device with `TIOCEXCL`,
preventing other unprivileged processes from opening the descriptor. The
system configuration also masks `serial-getty@ttyS2` and declares conflicts
with legacy runtimes.

Diagnostic tools such as `robotctl` communicate through
`/run/robotd.sock`; they do not access the hardware bus directly.

### Single-transaction sensor and actuator synchronization

The `imu_to_dxl v2` board is assigned Dynamixel ID 200. It performs sensor
fusion using an on-chip SFLP quaternion and exposes the result as ordinary
Dynamixel registers.

At 50 Hz, `robotd` performs one `sync_read`, reading ID 200 first and then
servo status such as PWM, velocity, and position. Reading the IMU and actuator
state in the same bus transaction minimizes skew between balance orientation
and motor position data.

### Persistent state and daemon coordination

Cross-daemon persistent configuration uses ordinary files rather than an IPC
broker. Writes are serialized with `flock` and committed with an atomic
write-to-temp followed by `rename(2)`; `inotify` is used to observe changes.

Daemons communicate with non-blocking, asynchronous JSON-RPC 2.0 (NDJSON) over
local UNIX domain sockets such as `/run/configd.sock` and `/run/robotd.sock`.
The `robotd` control loop never waits synchronously for another service.

### Authority arbitration and deadman watchdog

When a physical gamepad, phone app, and remote LLM may all request control,
local and physical controllers preempt remote sessions. Remote WebRTC or
gateway connections must continuously send heartbeats. If the connection is
partitioned or inference stalls beyond the configured threshold, `robotd`
initiates safe-stop deceleration and transitions the robot to a stable
standing or seated pose.

## 4. Intent-to-Actuation Flow

1. **Cognition:** The remote LLM evaluates the scene and emits a tool call,
   such as `navigate_to(target="ball", speed=0.4)`.
2. **Intent transport:** The gateway translates the request into an NDJSON
   RPC line and sends it through `/run/robotd.sock`.
3. **Arbitration and validation:** `robotd` verifies the remote session lease,
   checks the deadman timer, and confirms that the robot is not in a fallen
   state.
4. **Local policy execution:** On the next 20 ms tick, `robotd` samples IMU
   state, supplies the velocity intent to the ONNX gait policy, and computes
   target joint offsets.
5. **Bus execution:** The targets are sent in a single 1 Mbps Dynamixel
   transaction to the leg actuators, keeping the robot stable and upright.

## 5. SeedCore Relevance

Microduck illustrates a useful embodied-control boundary for SeedCore research:

- remote models and agents remain intent producers and observers;
- the onboard runtime owns deterministic control, arbitration, watchdogs, and
  hardware safety limits; and
- any SeedCore integration should preserve its own authority boundary: an
  intent must still pass the PDP, receive a scoped and revocable
  `ExecutionToken`, and close with replayable evidence before it is treated as
  governed execution.

The robot’s local safety authority and SeedCore’s policy authority are
complementary boundaries. Neither remote model output nor onboard adaptive
learning should become authorization merely because it can produce a valid
motion command.
