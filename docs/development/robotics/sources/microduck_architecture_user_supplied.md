# Microduck Architecture — Supplied Study

Received: 2026-09-17
Status: Original user-supplied research; claims are not independently verified here

Preserved verbatim below. Use the [source ledger](../microduck_source_ledger.md)
and revised studies for corrections and the current integration assumptions.

---

Based on the official architecture and design documentation of the **Microduck** robotics project (developed by Pollen Robotics), here is a complete architectural breakdown explaining how remote-end LLMs/agents coordinate with the onboard daemons, bus locks, and hardware to achieve precise and safe motion control.

---

### 1. High-Level Architecture Overview

```
 [ Remote Cloud / LLM / Agent ]
   │  (High-level reasoning, vision-language, tool selection)
   │  Transmits semantic high-level INTENTS (e.g., target_velocity, gaze, sit)
   ▼
 ════════════════════════════════════════════════════════════════════════════════
 [ Network Boundary / WebRTC / Rendezvous Gateway (mediad / remote gateway) ]
   │  Heartbeat / Deadman tracking & token auth
   │  JSON-RPC 2.0 (NDJSON) over local UNIX Sockets
   ▼
 [ microduck Onboard Linux System (e.g. Radxa Zero 3W / RK3566) ]
   ├── configd (/run/configd.sock) ── Wi-Fi, BLE bonding, robot identity, reboot
   ├── btd                       ── BLE transport forwarding into configd/robotd
   ├── updaterd                  ── A/B updates, rollbacks, policy fetching
   │
   └── robotd (/run/robotd.sock)  ── THE AUTONOMOUS SAFETY & REAL-TIME AUTHORITY
         │
         ├── Authority Arbiter (Gamepad / Local > App > Remote LLM)
         ├── Deadman / Heartbeat Watchdog
         ├── Joint & Thermal Limiters / Fall Detector
         │
         ├── 50 Hz Real-Time Control Loop (never blocks on external RPC)
         │     │
         │     ├── ONNX Runtime (Loads RL locomotion/manipulation policy)
         │     └── duck_control::bus::DynamixelIo (TIOCEXCL exclusive lock)
         │
         ▼ UART (/dev/ttyS2 at 1 Mbps, Dynamixel Protocol v2)
 ════════════════════════════════════════════════════════════════════════════════
 [ Hardware Bus (Single Shared 1 Mbps Bus) ]
   ├── ID 200:  imu_to_dxl v2 board (LSM6DSV16X on-chip SFLP quaternion)
   ├── ID 10–14: Right Leg (5 × Dynamixel XL330 servos)
   ├── ID 20–24: Left Leg  (5 × Dynamixel XL330 servos)
   └── ID 30–34: Neck, Head & Grasping Beak (5 × Dynamixel XL330 servos)

```

---

### 2. The Role-Playing Breakdown: Remote LLM vs. Onboard Daemons

The fundamental invariant of the Microduck architecture is: **"Intents, not motor writes."**

#### Remote LLM / Agent

* **Role:** High-level planner and multimodal observer.
* **Responsibilities:**
* Ingests sensory telemetry (camera frames via WebRTC media pipeline, IMU state summaries, battery voltage, temperature).
* Executes tool-calling, goal planning, and dialog logic (the "personality" or task logic).
* Produces high-level commands, such as `robot.move(vx, vy, yaw_rate)`, `robot.head(pitch, yaw)`, or `robot.loadPolicy("roller")`.


* **What it NEVER does:** It never commands raw PWM, motor angles, or millisecond joint trajectories directly. Latency, network jitter, or model stalling (e.g., token generation pauses) make running dynamic biped balance loops over a network physically impossible.

#### `robotd` (The Core Control Daemon)

* **Role:** Real-time motor authority, safety gatekeeper, and policy runner.
* **Responsibilities:**
* Runs a strictly deterministic **50 Hz (20 ms) control loop**.
* Executes local reinforcement learning (RL) policies using **ONNX Runtime** (e.g., balance, walking, standing up after a fall, wheeled locomotion).
* Translates LLM intent into target vectors fed into the neural policy.



---

### 3. Bus Locking, Exclusive Ownership, and Safety Coordination

Precision control in robotics requires preventing competing entities from corrupting bus traffic. Microduck enforces coordination across multiple boundaries:

#### 1. Hardware Bus Port Ownership (`TIOCEXCL` & Single Writer)

* Microduck shares a **single UART bus (`/dev/ttyS2` at 1 Mbps)** across all 15 Dynamixel XL330 actuators and the IMU coprocessor.
* `robotd` opens `/dev/ttyS2` using `TIOCEXCL` (exclusive lock) so no other unprivileged process can open the descriptor.
* Because `robotd` runs as root, OS-level conflicts are eliminated by design: systemd units mask `serial-getty@ttyS2` (which would otherwise attach a serial login shell) and mark conflicting legacy runtimes as `Conflicts=`.
* All external diagnostic tools (like `robotctl`) must communicate via `/run/robotd.sock` rather than touching the bus directly.

#### 2. The Single-Transaction Sensor/Actuator Sync Loop

* The IMU is an `imu_to_dxl v2` board assigned **Dynamixel ID 200**. It runs sensor fusion (SFLP quaternion) on-chip and exposes it as ordinary Dynamixel registers.
* At 50 Hz, `robotd` performs a single `sync_read` that reads ID 200 first, followed by the servo status (PWM, velocity, position).
* Because the IMU and actuators are on the same bus transaction, data skew between balance orientation and motor positions is virtually zero.

#### 3. State Ownership & Lock Serialization (`flock` + `inotify`)

* Cross-daemon persistent configuration uses plain files on disk rather than an IPC broker.
* File access uses `flock` for write serialization and atomic `write-to-temp + rename(2)` patterns. Changes are subscribed to using `inotify`.
* Daemons communicate with non-blocking, asynchronous JSON-RPC 2.0 (NDJSON) over local UNIX domain sockets (`/run/*.sock`). Invariant: `robotd`'s control loop **never blocks** synchronously waiting for responses from other services.

#### 4. Explicit Authority Arbitration & Deadman Watchdog

To handle cases where a physical gamepad, a phone app, and a remote LLM all attempt control:

* **Priority Handoff:** Local and physical controllers always have preemption authority over remote sessions.
* **Heartbeat / Deadman Switch:** Remote WebRTC/gateway connections must continuously pulse heartbeats. If the LLM network partition occurs or inference stalls beyond a strict threshold, `robotd` automatically triggers safe-stop deceleration and transitions the robot into a stable standing or seated pose.

---

### 4. Summary Flow: From LLM Thought to Servo Movement

1. **Cognition (Remote):** LLM evaluates duck surroundings and outputs tool call: `navigate_to(target="ball", speed=0.4)`.
2. **Intent Transport:** Network gateway translates this into an NDJSON RPC line: `{"method": "robot.move", "params": {"vx": 0.4, ...}}` pushed over `/run/robotd.sock`.
3. **Arbitration & Validation:** `robotd` verifies remote session lease, checks deadman timer, and ensures the robot is not currently in a fallen state.
4. **Local RL Policy Loop:** On the next 20 ms tick, `robotd` samples ID 200 IMU data, passes the LLM velocity intent into the ONNX gait policy, and computes 14 target joint offsets.
5. **Bus Execution:** Targets are flushed in a single 1 Mbps packet across the Dynamixel bus to the leg actuators, keeping the robot stable and upright.
