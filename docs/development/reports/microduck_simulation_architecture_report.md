# Microduck Simulation and Architecture Report

**Status:** Supplied draft; claims not independently verified  
**Scope:** Companion `microduck` and `microduck_rl` projects, not implemented SeedCore capabilities  
**Source revision and test date:** Not provided

> This report preserves the supplied draft for review. Its commands, model
> details, policy inventory, and performance statements need to be checked
> against the cited project revisions and local environment before being used
> as verified test results. SeedCore's current development map describes the
> Microduck adapter and hardware acceptance as planned work.

## 1. Local Development Capabilities (Mac / Apple Silicon)

The supplied draft estimates that local hardware handles approximately **90% of the active development and evaluation loop** without remote GPU compute:

| Task | Supported Locally | Execution Command |
| --- | --- | --- |
| **Simulation & Demo Testing** | Yes (100% real-time) | `./scripts/duck-sim / infer_policy.py` |
| **Unit & Invariant Tests** | Yes (Fast, CPU) | `uv run --with pytest pytest tests/` |
| **Listing Environments** | Yes | `uv run list-envs` |
| **Short Smoke Tests (5 iters)** | Yes (Runs on CPU) | `CUDA_VISIBLE_DEVICES="" WANDB_MODE=disabled uv run train <TASK> --env.scene.num-envs 4 --agent.max_iterations 5` |
| **ONNX Export & Deployment** | Yes | `uv run scripts/export.py ...` |
| **Interactive Keyboard Driving** | Yes (MuJoCo CPU) | `uv run scripts/infer_policy.py --walking out.onnx` |

## 2. Active Simulation Environment Breakdown

### 2.1. Robot Model (MJCF XML)

The supplied draft describes the model as fully loaded:

- **Source XML:** `scene_ball.xml` → `robot_groundcontact.xml`
- **CAD origin:** Exported directly from an Onshape assembly via `onshape-to-robot` (`doc: 804927696f06d877f3f1803e`).
- **Degrees of freedom:** Full 14-DOF biped kinematic tree:
  - Left leg (5): `left_hip_yaw`, `left_hip_roll`, `left_hip_pitch`, `left_knee`, `left_ankle`
  - Head / neck (4): `neck_pitch`, `head_pitch`, `head_yaw`, `head_roll`
  - Right leg (5): `right_hip_yaw`, `right_hip_roll`, `right_hip_pitch`, `right_knee`, `right_ankle`
  - Base: 6-DOF unconstrained freejoint (`trunk_base_freejoint`).
- **Mass distributions:** Computed from material densities (total mass approximately 800 g; trunk base 199.2 g, upper leg 48.2 g).
- **Meshes and collisions:** `.stl` surface and collision meshes for brackets, housings, and feet.
- **Joint limits:** Revolute hinge bounds enforced (for example, knee pitch `[-90°, +90°]`).
- **Scene elements:** Ground plane and a dynamic 70 mm, 15 g soccer ball (`ball.xml`).

### 2.2. Actuator Model (BAM M6 Dynamixel XL330)

The supplied draft describes a two-layer integration.

#### Layer 1: Policy Training Environment (`microduck_rl`)

The draft identifies the electromechanical BAM M6 model (`FrictionDRBamActuator` in `friction_dr_bam.py`) and lists:

- Motor voltage control law and back-EMF (`V - k_e θ̇`).
- Coulomb, viscous, and load-dependent gear mesh friction.
- Battery internal resistance and dynamic voltage sag under load.
- Gearbox backlash play (±1°), with output encoders reading through the mechanical slop.

#### Layer 2: Active Simulation Server (`body_server.py`)

The draft says MuJoCo executes a BAM M6 empirical fit parameterized in XML (`class="chosen_actuator"`):

- **Motor armature:** 0.0018 kg·m² (rotor inertia reflected through a 254:1 gearbox).
- **Damping:** 0.053 N·s/m.
- **Friction loss:** 0.0048 N·m.
- **Peak torque limit:** [-0.96, +0.96] N·m (XL330-M288 physical ceiling).
- **Dynamic gain scaling:** `scale = k_p / 200.0`, where 200 is the Dynamixel register value to which nominal impedance was fitted.
- **Execution:** Native compiled MuJoCo C physics inside `body_server.py`, claimed to maintain a strict 1.00× real-time factor over the IPC socket.

### 2.3. Active RL Neural Policies

The supplied draft lists policies under `~/.cache/duck-sim/policies/current/`:

| Policy File | Role / Skill | Input Shape | Output Shape | Architecture |
| --- | --- | --- | --- | --- |
| `alpha_walking.onnx` | Continuous biped locomotion | `[1, 61]` | `[1, 14]` | 4-layer MLP (Gemm → ELU), PyTorch 2.9.1 |
| `alpha_stand.onnx` | Static upright posture balancing | `[1, 61]` | `[1, 14]` | 4-layer MLP (Gemm → ELU), PyTorch 2.9.1 |
| `alpha_sitstand.onnx` | Seated-to-standing dynamic rise | `[1, 61]` | `[1, 14]` | 4-layer MLP (Gemm → ELU), PyTorch 2.9.1 |
| `ball_kick_right.onnx` | Right-foot ball strike | `[1, 61]` | `[1, 14]` | 4-layer MLP (Gemm → ELU), PyTorch 2.9.1 |
| `ball_kick_left.onnx` | Left-foot ball strike | `[1, 61]` | `[1, 14]` | 4-layer MLP (Gemm → ELU), PyTorch 2.9.1 |
| `roulade.onnx` | 360° acrobatic forward roll | `[1, 61]` | `[1, 14]` | 4-layer MLP (Gemm → ELU), PyTorch 2.9.1 |

The listed observation tensor `[1, 61]` is described as containing:

- Base angular velocity (gyro: 3D)
- Projected gravity vector (accelerometer: 3D)
- Joint positions relative to nominal home pose (14D)
- Joint velocities (14D)
- Previous-step target actions (`aₜ₋₁`: 14D)
- Commanded twist (`vₓ`, `vᵧ`, yaw: 3D)
- Head gaze orientation (4D)
- Body pose offsets / posture flags (6D)

The listed action tensor `[1, 14]` contains 14 target joint-position offsets added to the default stance at 50 Hz.

The draft says inference is driven inside the Rust `robotd` daemon via native C++ bindings (`libonnxruntime.1.24.4.dylib`).

## 3. Summary

The supplied draft describes a closed loop across three layers:

1. **Mechanical:** CAD-derived MJCF rigid-body tree with mass and inertia matrices.
2. **Electromechanical:** BAM M6 actuator dynamics with voltage sag and gearbox backlash.
3. **Control:** 50 Hz ONNX neural policies evaluating a unified 61-D observation vector.

These statements remain claims from the supplied draft until checked against source, reproducible commands, and dated test output. For SeedCore's integration status and acceptance sequence, see the [Microduck integration plan](../robotics/microduck_integration_plan.md) and [development map](../README.md).
