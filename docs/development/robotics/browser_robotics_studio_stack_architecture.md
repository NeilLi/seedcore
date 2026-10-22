# Browser Robotics Studio Architecture & Technology Stack Assessment

Date: 2026-10-21
Status: Architectural reference and stack evaluation for SIM-1–SIM-6 and Central World (CW-A01–CW-L03); no new runtime dependency or hardware authority is granted by this document
Baseline: `293ebbe` (`CW-S01` restricted assembly-to-MJCF compiler and native MuJoCo 3.15.0 parity)

Implementation update, 21 October: the optional
[browser performance lab](browser_performance_pipeline.md) now implements
separate scalar Wasm physics and OffscreenCanvas/WebGPU rendering, bounded
transferable/shared snapshots and WGSL display FK. That record corrects broad
zero-copy, solver, SIMD-speedup and remote-latency claims and owns the measured
device evidence and adoption gates. The assessment below remains the wider
architectural reference; no general browser MuJoCo or physical gate is closed.

Implementation update, 22 October: the separate
[static scene lab](static_scene_streaming.md) now adds the pinned NASA 3D Tiles
renderer, original Draco HLOD assets, bounded SSE/frustum/LRU streaming and
origin rebasing beside an independent planar actor. Its source/fault/precision
record owns this limited visual profile; KTX2/Basis textures, external CAD,
general browser dynamics and hardware qualification remain separate.

Browser-based robotics platforms have evolved from passive 3D visualizers into simulation, offline programming (OLP), and hardware-in-the-loop (HIL) environments. Shifting traditional desktop stacks into browser runtimes removes local OS setup friction, but **zero-install convenience does not establish numerical fidelity, execution authority, or physical safety**.

This document evaluates the five-layer browser robotics studio stack against SeedCore's delivered engineering slices (`SIM-1–SIM-3`, `CW1`, `CW-A01–CW-A04`, `CW-S01`, and `fast-spine-v1` session rehearsal) and defines concrete optimizations for upcoming `CW-S02–CW-S04`, `CW-G01/G02`, and `SIM-4–SIM-6` work packages.

---

## 1. Five-Layer Browser Studio Stack vs. SeedCore Architecture

A general browser robotics studio decouples user interface, 3D rendering, physics/kinematics, computation workers, and device/network I/O. SeedCore adds an explicit **Trust & Verification Boundary** so that neither UI state, worker scripts, nor browser serial permissions can mint motor authority:

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ 1. User Interface & Authoring Shell                                        │
│    Industry: React / Svelte / Solid + Monaco Editor / BlockUI              │
│    SeedCore: Vanilla TS + AssemblyStore (CW-A02..A04) · Zero UI-state auth │
├─────────────────────────────────────┬──────────────────────────────────────┤
│ 2. 3D Scene & Asset Rendering       │ 3. Kinematics, DRC & Physics (Wasm)  │
│    Industry: Three.js / Babylon /   │    Industry: Rapier.js / PhysX /     │
│    WebGPU + urdf-loader + Draco GLB │    MuJoCo Wasm / Pinocchio / TRAC-IK │
│    SeedCore: Three.js 0.181.1 box   │    SeedCore: Dual-ABI C++17 Wasm     │
│    proxies (CW-A02/A03) + 3D Orbit  │    (SIM-3) + CW-S01 MJCF Compiler -> │
│    Canvas (SIM-3); mesh != inertia  │    CW-S02 Pinned MuJoCo Wasm Worker  │
├─────────────────────────────────────┴──────────────────────────────────────┤
│ 4. Sandboxed Computation, Behavior Compilation & DRC Workers               │
│    Industry: Pyodide (CPython Wasm) / Web Workers / ROS 2 package export   │
│    SeedCore: Pure DRC Worker (CW-A04) + Declarative Keyframe/Chunk         │
│    Compiler (CW-S04); optional Pyodide stays untrusted intent proposer     │
├─────────────────────────────────────┬──────────────────────────────────────┤
│ 5A. Network & Telemetry Bus         │ 5B. Governed Hardware & Proof Bridge │
│    Industry: WebRTC / WebSockets /  │    Industry: Raw WebSerial / WebHID  │
│    rosbridge_suite / Zenoh / MCAP   │    SeedCore: Agent Gateway -> PDP -> │
│    SeedCore: Localhost COOP/COEP +  │    Single-Use Token -> fast-spine-v1 │
│    Python/Rust Verified Replay      │    Watchdog -> Signed Receipt (G1/G2)│
└─────────────────────────────────────┴──────────────────────────────────────┘
```

| Stack Layer | Common Industry Choice | SeedCore Delivered Baseline (`293ebbe`) | SeedCore Target Optimization (`CW-S02`–`CW-L03`) |
| :--- | :--- | :--- | :--- |
| **1. UI / IDE Shell** | React / `@react-three/fiber` / Zustand + Monaco / Blockly | Framework-free TypeScript (`ts/apps/mini-studio`), deep-frozen `AssemblyStore` (`CW-A02`), `15 mm` / `5°` snapping & numeric placement (`CW-A03`), and `DRC & BOM` inspector (`CW-A04`). | Keep pure graph, snapping, DRC, and MJCF compilation independent of UI frameworks (`central_world_engineering_plan.md`). Add declarative gesture timeline editor in `CW-S04`. |
| **2. 3D Scene & Assets** | `Three.js` / `Babylon.js` + [`urdf-loader`](https://github.com/gkjohnson/urdf-loaders) + [Draco](https://github.com/google/draco) glTF/GLB | `three@0.181.1` rest-pose viewport (`ts/packages/robot-canvas`) with byte-pinned `.sc-part.json` and bounded box-proxy `.glb` decoder (`decodeProxy`). | Retain strict separation between visual GLBs and dynamics (`CW-S01`). Evaluate Draco compression only for optional high-poly visual meshes in `CW-L01` after pinning decoder Wasm hashes. |
| **3. Physics & Kinematics (Wasm)** | [Rapier.js (`@dimforge/rapier3d-compat`)](https://rapier.rs/docs/user_guides/javascript/getting_started_js), Ammo.js/PhysX, or [Pinocchio](https://github.com/stack-of-tasks/pinocchio) | Owned C++17 dual-ABI `mini-physics.wasm` (`13,242 B`, `SIM-1–SIM-3` planar 1/2/3-link) + `@seedcore/wasm-sim-bridge` (`CW-S01`) restricted MJCF compiler verified against native MuJoCo `3.15.0`. | Keep two distinct backends: custom planar Wasm for `SIM-1–SIM-3` lessons, and a pinned browser MuJoCo Wasm worker (`CW-S02`) for `CW-S01` MJCF models. Never silently fall back between them. |
| **4. Computation & Scripting** | [Pyodide](https://pyodide.org/) in Web Workers; in-tab ROS 2 package generators | Dedicated `SIM-1/2` simulation worker, `CW-A04` `DrcWorkerCoordinator` (`2 MiB` cap, generation-ticket fencing), and standalone build-time Ajv validators (no `unsafe-eval`). | Compile user behaviors (`CW-S04` Robot Moments) to declarative, extrema-checked keyframe/chunk manifests—never arbitrary privileged scripts. Keep any future Pyodide worker strictly an untrusted `ActionIntent` proposer. |
| **5. Transport, HIL & Observability** | [Chrome WebSerial](https://developer.chrome.com/docs/capabilities/serial), [`rosbridge_suite`](https://github.com/RobotWebTools/rosbridge_suite), [Eclipse Zenoh](https://zenoh.io/), [Foxglove MCAP](https://github.com/foxglove/studio) | `fast-spine-v1` wire schemas, localhost split-screen bounded-session rehearsal (`:8766`), 5 ms host watchdog fixture, and Python/Rust (`seedcore-verify`) receipt verification. | Require PDP admission, single-use session tokens, and hardware watchdog fencing before any physical `WebSerial` dispatch (`CW-G01`, `CW-F01/F02`). Bind replay (`CW-G02`) to cryptographic receipts rather than unverified log files. |

---

## 2. Subsystem Deep Dive & SeedCore Engineering Decisions

### A. Robot Modeling, Asset Ingestion & Inertial Integrity (`URDF / SDF / MJCF / glTF`)

1. **Format Parsing & Kinematic Compilation (`URDF / SDF` vs. `.sc-part.json` -> `CW-S01` MJCF):**
   - Browser visualizers commonly use [`urdf-loader`](https://github.com/gkjohnson/urdf-loaders) to parse XML links and joints directly into a Three.js scene graph. However, visual XML parsing does not validate joint-axis conventions, closed-loop constraints, actuator saturation, or electrical bus compatibility.
   - **SeedCore Architecture:** SeedCore separates **component authoring** (`.sc-part.json` v1), **assembly graph & electrical net authoring** (`seedcore.assembly.v2` in `CW-A01..A03`), **offline electrical/mechanical DRC** (`CW-A04`), and **restricted MJCF compilation** (`@seedcore/wasm-sim-bridge` in [`central_world_cw_s01_mjcf.md`](central_world_cw_s01_mjcf.md)).
   - For external robot models (such as pinned **Microduck 0.1.0** in `packages/models/microduck/0.1.0/` or future CAD exports via [Rhoban `onshape-to-robot`](https://github.com/Rhoban/onshape-to-robot) and [FreeCAD `RobotCAD`](https://github.com/drfenixion/freecad.robotcad) in [`robot_design_toolkit_assessment.md`](robot_design_toolkit_assessment.md)), ingestion requires a SHA-256 asset manifest and native MuJoCo parity verification ([`model_package_ingestion.md`](model_package_ingestion.md)).

2. **Mesh Pipeline & Compression (`glTF / GLB / Draco`):**
   - Production web studios convert heavy STEP/DAE/STL CAD into binary **GLB** and apply [Google Draco](https://github.com/google/draco) geometry compression to reduce network payload and GPU buffer upload latency.
   - **SeedCore Optimization & Boundary:**
     - In `CW1` and `CW-A02..A04`, visual meshes are frozen box-proxy GLBs (`seedcore_box_proxy`, Y-up converted at a single tested boundary in `ts/packages/robot-canvas/src/assets.ts`) verified by exact SHA-256 byte pins and a bounded streaming reader (`readBounded`, `1 MiB` limit).
     - `CW-S01` deliberately emits **primitive box geometry only** into compiled MJCF XML and never loads external meshes, `<include>` tags, or filesystem hooks during physics compilation.
     - When curated high-resolution visual meshes are introduced in `CW-E01` / `CW-L01`, Draco decompression may be used **for visual rendering only**, provided the Draco Wasm decoder binary is locally pinned under the studio's no-`unsafe-eval` Content Security Policy (CSP) and uncompressed byte ceilings remain enforced before GPU upload.

3. **Inertial Calculations (Why Mesh-Volume Inertia Is Not Hardware Truth):**
   - While some browser tools estimate mass and inertia tensors automatically from mesh surface volumes in Wasm, **visual shells rarely reflect internal motor rotors, brass gears, steel fasteners, PCBs, or battery cell distribution**.
   - **SeedCore Rule (`CW-DRC-03` & `CW-SIM-01`):** Never infer calibrated mass or inertia from a visual GLB mesh. Each `.sc-part.json` component declares an explicit mass, local COM, and symmetric positive-definite $3\times 3$ inertia tensor satisfying principal-moment triangle inequalities ($\lambda_1 > 0$, $\lambda_3 \le \lambda_1 + \lambda_2 + \epsilon$). `CW-A04` rotates the full $3\times 3$ tensor into world coordinates ($\mathbf{I}_{i,\text{world}} = \mathbf{R}_i \mathbf{I}_{i,\text{local}} \mathbf{R}_i^\top$, preserving off-diagonal `ixy, ixz, iyz` terms) and applies the 3D parallel-axis theorem, which `CW-S01` verifies against native MuJoCo `3.15.0` across 12 synthetic models (`verify-mjcf.cjs`).

---

### B. Physics & Kinematic Solvers in WebAssembly (`Rapier.js` vs. `MuJoCo Wasm` & `mini-physics.wasm`)

1. **Rigid-Body Game Physics vs. Generalized-Coordinate Robotics Solvers:**
   - **[Rapier.js (`@dimforge/rapier3d-compat`)](https://rapier.rs/docs/user_guides/javascript/getting_started_js)** and **Ammo.js / PhysX** are versatile Rust/C++ Wasm engines for general 3D rigid bodies, convex-hull collisions, and game-scale constraints. However, maximal-coordinate game solvers can exhibit joint compliance/drift on high-ratio serial manipulators or closed-loop linkages compared to reduced/generalized-coordinate articulated-body solvers ([MuJoCo](https://mujoco.readthedocs.io/en/stable/overview.html), [Pinocchio](https://github.com/stack-of-tasks/pinocchio)).
   - **SeedCore Dual-Backend Strategy:**
     - **Analytical Planar C++17 / Wasm Kernel (`packages/mini-physics/`, Delivered):** Zero-allocation (`0` heap `malloc`/`new`), double-precision (`f64`) analytical Lagrangian solver (`mini-physics.wasm`, `13,242` raw bytes) exporting `ABI 1` (2-link) and `ABI 2` (1/2/3-link serial chains) with exact $M(q)$, skew-symmetric Coriolis $c(q,v)$, gravity $g(q) = \nabla U(q)$, analytical $3\times 3$ Cramer inverse, and RK4 integration. Matches native C++ within $3.997 \times 10^{-14}$ over 2,880-tick reference traces.
     - **General Browser MuJoCo Wasm Worker (`ts/packages/wasm-sim-bridge`, `CW-S02` Next):** Consumes the restricted MJCF models compiled by `CW-S01`. As documented in the [`mjswan 0.11.9` integration assessment](mjswan_integration_assessment.md), adopting an upstream MuJoCo Wasm package requires reconciling the MuJoCo engine version (`3.11.0` vs. SeedCore's pinned native `3.15.0`) and wrapping it in a **state-owning Web Worker** with per-substep control gating (`CW-SIM-04`) and deterministic telemetry capture (`CW-SIM-03`).

2. **Forward & Inverse Kinematics (`FK / IK`) Placement:**
   - **Forward Kinematics (FK):** SeedCore computes deterministic rest-pose FK both in Python (`compute_node_world_transforms` in `src/seedcore/robotics/assembly.py`) and in TypeScript (`ts/packages/robot-canvas/src/snapping.ts`), verified against native MuJoCo FK in `tests/test_cw_s01_native.py`.
   - **Inverse Kinematics (IK) Optimization:** In `SIM-3`, `mini-physics.wasm` already exports the exact analytical end-effector Jacobian $\mathbf{J}(q)$. For `CW-S04` (Robot Moments gesture authoring) and interactive target dragging, a Damped Least Squares (DLS) step ($\Delta q = \mathbf{J}^\top (\mathbf{J}\mathbf{J}^\top + \lambda^2 \mathbf{I})^{-1} \Delta x$) or a Wasm-compiled [Pinocchio](https://github.com/stack-of-tasks/pinocchio) / [TRAC-IK](https://traclabs.com/projects/trac-ik/) solver can run in the authoring layer to propose joint keyframes. **Boundary:** IK is a *proposal generator*; the resulting joint trajectory must still pass `CW-S04` position/velocity/acceleration/jerk extrema checks and `CW-G01` capability admission before execution.

---

### C. In-Browser Code Execution, Sandboxing & Behavior Contracts (`Pyodide` vs. Declarative Chunks)

1. **Why Arbitrary In-Tab Scripting Cannot Own Motor Execution:**
   - Many educational web studios embed [Pyodide](https://pyodide.org/) (CPython in Wasm) with Monaco Editor so users can run Python loops (`while True: robot.set_joint(...)`) or generate ROS 2 packages in the browser.
   - In SeedCore's **Slow Brain, Fast Spine** architecture, running an unconstrained Python interpreter in the control loop introduces garbage-collection jitter, unbounded blocking loops, and an unverified authority bypass if scripts can write directly to serial/network sockets.

2. **SeedCore Sandboxing & Compilation Pattern (`CW-S04` & `robot_skill_contract.md`):**
   - **Declarative Bounded Timelines First:** In `CW-S04` (`CW-MOM-01`), behaviors compile to declarative joint/LED keyframe timelines or receding-horizon `fast-spine-v1` action chunks (`30–50` waypoints) with explicit units, interpolation rules, and verified extrema bounds. Any edit, loop, or time-stretch invalidates prior admission and increments `authorityEpoch`.
   - **Isolated Worker Sandbox for Optional Python/LLM Prototyping:** If a Pyodide or Monaco scripting pad is added for advanced curriculum labs, it must execute inside a **network-isolated, hardware-isolated Web Worker** (`connect-src 'none'`, zero `WebSerial` handles) with a hard wall-clock execution timeout. Its sole output is a candidate `ActionIntent` or declarative trajectory JSON that enters the exact same local validator, DRC check, and PDP admission gate as hand-authored moves.

---

### D. Hardware Telemetry, Communication Bus & Observability (`WebSerial / Zenoh / Foxglove` vs. SeedCore Proof Pipeline)

1. **Direct Device Control (`WebSerial` / `WebHID` vs. `fast-spine-v1` Governed Sessions):**
   - Tools like [Arctos Studio](https://arctosrobotics.com/robot-simulation-software/) use the [Chrome WebSerial API](https://developer.chrome.com/docs/capabilities/serial) to stream raw G-code or servo packets directly from the browser tab to an MCU.
   - **SeedCore Security Boundary (`fast_spine_protocol_spec.md` & `CW-G01/F02`):** Browser serial-port selection and CRC checksums are **transport plumbing, not authentication or authorization**. Before physical `WebSerial` actuation is enabled (`CW-F01/F02` and `G1/G2`), SeedCore requires:
     1. A **single-use session `ExecutionToken`** issued by a trusted PDP (`CW-AUTH-01`) bound to the exact reviewed assembly/configuration digest.
     2. Monotonic command freshness and revocation-context checks (`CW-AUTH-02`) where heartbeats cannot extend the admitted session horizon or clear a latched stop.
     3. An independent **hardware watchdog on the MCU** (`ESP32-S3`) that brings actuators to a safe stop if authenticated chunks cease or browser/USB communication drops.

2. **Network Transport (`rosbridge_suite` / `Zenoh` / `WebRTC`):**
   - For networked robots, studios often bridge ROS 2 topics over WebSockets via [`rosbridge_suite`](https://github.com/RobotWebTools/rosbridge_suite) or [Eclipse Zenoh (`zenoh-ts`)](https://github.com/eclipse-zenoh/zenoh), paired with WebRTC for camera feeds.
   - **SeedCore Boundary:** External camera egress and unauthenticated topic bridges remain **disabled by default** (`application_directions.md`). Native Microduck execution routes through governed RPC (`robotd` retains onboard balance and bus ownership), and any future Zenoh or WebSocket transport adapter must terminate at the SeedCore Agent Action Gateway / HAL boundary rather than exposing raw actuator topics to browser clients.

3. **Observability & Verifiable Replay ([Foxglove Studio](https://github.com/foxglove/studio) / `MCAP` vs. `CW-G02` & `RESULT_VERIFIER`):**
   - [Foxglove Studio](https://github.com/foxglove/studio) and **MCAP** containers excel at high-bandwidth multimodal diagnostic visualization.
   - SeedCore's `CW-G02` (`CW-EVID-01`) replay surface solves a complementary problem: **cryptographic auditability**. Every replay bundle binds `intent_digest`, `capability_digest`, `assemblyDigest`, `electricalPlanDigest`, sample coverage, and signer provenance, verified identically by Python and the Rust `seedcore-verify` kernel. Missing, gapped, stale, or host-simulated traces are explicitly labeled or quarantined—never presented under a blanket "Verified Safe" badge.

---

## 3. Landscape Comparison Matrix

| Category | Representative Platforms | Core Architectural Approach | Primary Strength | SeedCore Differentiation & Boundary |
| :--- | :--- | :--- | :--- | :--- |
| **Industrial Cloud Digital Twins** | [ABB RobotStudio Cloud](https://www.abb.com/global/en/areas/robotics/products/software/robotstudio-suite/robotstudio-cloud), [Universal Robots UR Studio / PolyScope X](https://www.universal-robots.com/products/ur-studio/) | Vendor-specific virtual controller in cloud/containers paired with browser 3D workcell layout and OLP. | High controller fidelity for proprietary 6-DOF industrial arms and cycle-time estimation. | Targets sub-$300 open maker/STEM embodiments (`Microduck`, `STS3215` tabletop fixtures) with open RFC 8785 contracts and cross-vendor component registries rather than locked vendor controllers. |
| **Web-Native URDF / Physics Simulators** | Robo Studio, BrowserBotics, [URDF-Studio](https://github.com/OpenLegged/URDF-Studio), [mjswan](https://github.com/ttktjmt/mjswan) | Client-side Wasm physics ([Rapier.js](https://rapier.rs/) or MuJoCo Wasm), URDF/MJCF loading, and in-browser policy/script execution. | Zero-install kinematic/dynamic visualization and rapid student/research prototyping. | Adds byte-pinned `.sc-part.json` catalogs (`CW1`), electrical/rail/GPIO DRC (`CW-A04`), native MuJoCo `3.15.0` compile/FK/inertia parity (`CW-S01`), and scoped `ExecutionToken` enforcement (`CW-SIM-04`). |
| **Direct Browser-to-MCU HIL** | [Arctos Studio Web](https://arctosrobotics.com/robot-simulation-software/), [ESP Web Tools](https://esphome.github.io/esp-web-tools/) | WebGL UI + direct [WebSerial](https://developer.chrome.com/docs/capabilities/serial) USB-CDC streaming or binary flashing to ESP32/STM32/Arduino. | Zero-driver USB commissioning and immediate slider-to-motor teleoperation. | Separates flashing/port access from motor authority: requires single-use session tokens, NVS golden partition verification (`CW-F01`), local watchdog stop, and action-bound receipts (`G1/G2`). |
| **Observability & Log Replay** | [Foxglove Studio](https://github.com/foxglove/studio) (MCAP / ROS 1 & 2) | Extensible React panel workspace for multimodal sensor playback and live WebSocket diagnostics. | Industry-standard timeline inspection for high-rate ROS bag/MCAP telemetry. | Binds replay (`CW-G02`) to cryptographic authority and verifier dispositions (`verified`, `interrupted`, `quarantined`) checked by the Rust proof kernel (`seedcore-verify`). |

---

## 4. Engineering Challenges & SeedCore Optimization Blueprint

### Challenge 1: Deterministic Physics vs. Variable Display Refresh Rates (`60 / 120 / 144 Hz`)

- **Problem:** Browser `requestAnimationFrame` callbacks fluctuate with display refresh rate, tab throttling, and main-thread layout stalls. Stepping physics with variable wall-clock $\Delta t$ causes numerical divergence, energy drift, and non-reproducible contact outcomes.
- **SeedCore Optimization (`SIM-1–SIM-3` Delivered; `CW-S02` Required):**
  1. **Three-Clock Decoupling (`CW-SIM-03`):** The simulation worker owns an integer tick counter $k$ and a frozen physics timestep $\Delta t_{\text{phys}}$ (e.g., `1/480 s` in `SIM-1–SIM-3`; profile-pinned `2 ms` in `CW-S02`). Policy evaluation runs at an integer decimation ratio (e.g., `50 Hz` / every 10 ticks at `2 ms`), while the UI thread interpolates the latest immutable snapshot at display refresh rate.
  2. **Bounded Catch-Up & Explicit Stall Reporting:** Accumulate wall-clock elapsed time up to a strict per-frame substep ceiling (48 steps in `SIM-3`). If a UI or worker stall exceeds the ceiling, **discard wall-time debt and slow simulated time visibly** rather than enlarging $\Delta t_{\text{phys}}$ or dropping required telemetry capture samples.
  3. **Hidden-Tab & Lifecycle Fencing:** Hiding the browser tab or losing window focus pauses local lessons (`SIM-3`) and triggers deterministic session interruption in governed runs (`CW-SIM-03`) so background tabs never resume stale motion attempts.

### Challenge 2: Web Worker Serialization Overhead & Zero-Copy Memory

- **Problem:** Cloning large state/telemetry payloads via `postMessage` at `60–500 Hz` creates structured-clone CPU overhead and GC pauses. While `SharedArrayBuffer` enables zero-copy memory sharing, it requires cross-origin isolation (`Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Embedder-Policy: require-corp`), which can break embedded iframes or third-party assets if unverified.
- **SeedCore Optimization (`SIM-1` Pool + `CW-A04` Epoch Fencing + `CW-S02` Profiles):**
  1. **Bounded `Transferable` Ring Buffer Pool (Default Zero-Copy Path):** Use a preallocated pool of 3 reusable [`Transferable` `ArrayBuffer`s](https://developer.mozilla.org/en-US/docs/Web/API/Web_Workers_API/Transferable_objects) (proven in `SIM-1/SIM-2`) transferred ownership-ping-pong style between the simulation worker and UI thread. Never detach the Wasm module's internal linear memory buffer; copy only the compact state/observation frame (`64` doubles in `ABI 2`) into the transferable slot before transfer.
  2. **Generation-Ticket & Epoch Fencing:** Every worker request and response carries `{ revisionDigest, assemblyDigest, catalogDigest, authorityEpoch, generation }` (implemented in `AssemblyStore` and `DrcWorkerCoordinator`). Late or out-of-order worker messages are discarded in $O(1)$ without mutating UI or session state.
  3. **Explicit Single-Thread vs. Pthread/SharedArrayBuffer Profiles (`CW-S02`):** `src/seedcore/robotics/mini_studio_api.py` already emits `COOP: same-origin`, `COEP: require-corp`, and `CORP: same-origin` on localhost. For `CW-S02`, qualify a deterministic **single-thread Wasm worker profile** first so embeds and standard hosts always work, and gate multi-threaded `SharedArrayBuffer` Wasm behind an explicit runtime check (`self.crossOriginIsolated === true`) tested on the actual deployment origin/subdomain.

### Challenge 3: Browser Memory Limits (`1–2 GB` Tab Ceiling) & Asset Security

- **Problem:** Lower-end laptops, tablets, and managed Chromebooks enforce strict per-tab memory limits. Unbounded JSON payloads, high-polygon CAD meshes, or growing undo/telemetry histories crash the renderer or worker process.
- **SeedCore Optimization (Implemented Across `CW-A01..S01`, Extended to `CW-S02..E01`):**
  1. **Streaming Byte & Graph Bounds Before Allocation:**
     - Raw JSON text capped at `256 KiB` (`262,144` UTF-8 bytes), `32` nesting levels, and `50,000` visited nodes in `parseStrictJson()` (`ts/packages/contracts/src/assemblyText.ts`).
     - Assembly graph capped at `256` nodes, `255` edges, `64` nets, and `32` actuator outputs (`v2.sc-assembly.schema.json`).
     - Streaming HTTP/asset reader `readBounded()` (`ts/packages/robot-canvas/src/assets.ts`) aborts fetches mid-stream if a mesh exceeds `1 MiB` or a validation payload exceeds `2 MiB`.
  2. **Bounded History & Geometry Disposal:**
     - `AssemblyStore` caps undo/redo history at `32` entries and `2 MiB` total (`store.ts`).
     - `RobotCanvas` explicitly calls `.geometry.dispose()` and `.material.dispose()` on every Three.js mesh and line before rebuilding or disposing a scene (`canvas.ts`).
  3. **Primitive Collision/Inertial Compilation (`CW-S01`):**
     - Physics and collision shapes in `CW-S01` use bounded primitive geometry (`<= 32` bodies, `<= 1 m` per dimension, `<= 5 kg` total mass) rather than feeding high-polygon visual meshes into the physics contact solver.

---

## 5. Immediate Action Items for `CW-S02`–`CW-S04`

When implementing the next Central World Phase 3 packages (`CW-S02` browser MuJoCo worker, `CW-S03` ONNX policy adapter, and `CW-S04` Robot Moments gesture timeline), apply the following checklist:

1. **`CW-S02` (Pinned Browser MuJoCo Worker in `ts/packages/wasm-sim-bridge`):**
   - Consume only verified `CW-S01` compiled MJCF bundles (`seedcore.cw-s01.mjcf.v1`) with matching `assemblyDigest`, `catalogDigest`, and `electricalPlanDigest`.
   - Run the physics step inside a dedicated Web Worker owning state (`q`, `v`, `act`, `time`), exposing a 3-buffer `Transferable` snapshot ring and enforcing the three-clock contract (`dt_physics`, `dt_policy`, `dt_render`).
   - Implement the `CW-SIM-04` state-owning control gate inside the worker substep loop so expired, revoked, or out-of-epoch commands are vetoed before `mj_step`.
2. **`CW-S03` (Model-Bound ONNX Policy Adapter):**
   - Pin ONNX Runtime Web Wasm binaries and model SHA-256 digests; reject unverified external URLs or mismatched observation/action dimensions.
   - Keep Microduck's `61`-observation / `14`-action locomotion policy disabled in custom-build studio runs until independent checkpoint/export parity (`M1`) and body compatibility are established.
3. **`CW-S04` (Declarative Robot Moments Timeline & Optional IK Helper):**
   - Implement the bounded joint/LED keyframe schema with analytical velocity/acceleration/jerk extrema validation (`CW-MOM-01`) and automatic `authorityEpoch` invalidation on any curve edit.
   - If adding an interactive IK target handle, run Damped Least Squares IK as a pure client-side keyframe proposer that feeds into `CW-S04` extrema validation rather than driving actuators directly.
