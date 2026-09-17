# Microduck RL — Supplied Study

Received: 2026-09-17
Status: Original user-supplied research; claims are not independently verified here

Preserved verbatim below. Use the [source ledger](../microduck_source_ledger.md)
and revised studies for corrections and the current integration assumptions.

---

In `microduck_rl`, the reinforcement learning stack (built around MuJoCo and PPO) models locomotion and bipedal behaviors as a discrete, synchronized Markov Decision Process (MDP) running at **50 Hz (20 ms timesteps)**.

To bridge the sim-to-real gap, the observation space relies strictly on real-world sensor availability, while the reward formulation balances task tracking against mechanical wear and dynamic stability.

---

### 1. The Observation Space (Policy Inputs)

The observation vector fed into the policy network (and exported to the onboard ONNX model) contains only quantities that `robotd` can sample deterministically on hardware every 20 ms. It deliberately omits simulator-only ground truth (such as global Cartesian coordinates or privileged contact force maps).

A standard walking observation vector is composed of:

| Signal Category | Dimensions | Physical Description & Hardware Source |
| --- | --- | --- |
| **Base Orientation** | 3 or 4 | Projected gravity vector $g_b \in \mathbb{R}^3$ or base orientation quaternion from the **`imu_to_dxl v2`** board (LSM6DSV16X on-chip sensor fusion). |
| **Base Angular Velocity** | 3 | Gyroscope angular rates $(\omega_x, \omega_y, \omega_z)$ expressed in the robot base frame. |
| **Velocity Commands** | 3 | Desired high-level task targets $(v_x^{\text{cmd}}, v_y^{\text{cmd}}, \omega_z^{\text{cmd}})$ supplied by the user, gamepad, or remote LLM. |
| **Joint Positions (Error)** | $N$ | Current joint angles minus the default standing offset: $(q_t - q_{\text{default}})$. |
| **Joint Velocities** | $N$ | Filtered joint angular velocities $\dot{q}_t$ estimated across the Dynamixel bus. |
| **Previous Action History** | $N$ | Joint position targets commanded at step $t-1$ (crucial for dealing with actuator lag and latency). |
| **Gait Phase / Timing** | 2 | Periodic clock indicators $(\sin(\phi_t), \cos(\phi_t))$ to establish cyclic footfall rhythms (in walking policies). |

> **Note on Degrees of Freedom ($N$):** While Microduck has 15 total Dynamixel XL330 servos (5 per leg, 5 for neck/head/beak), locomotion policies typically control the **10 leg joints** (Hip Yaw, Hip Roll, Hip Pitch, Knee, Ankle Pitch per side). The remaining upper-body joints are either fixed, locked to neutral offsets, or controlled by an auxiliary head-stabilization loop.

---

### 2. Reward Function Formulation

The training objective optimizes a weighted multi-term scalar reward $R_t$:

$$R_t = \sum_i w_i \cdot r_i(s_t, a_t)$$

The reward formulation is structured into **Task Tracking (Positive)** and **Style / Physical Regularization (Negative)** penalties:

#### Task Tracking Objectives

* **Linear Velocity Tracking:**

$$r_{\text{lin\_vel}} = \exp\left( -\frac{\Vert{}v_{xy} - v_{xy}^{\text{cmd}}\Vert{}^2}{\sigma_v^2} \right)$$



Incentivizes tracking the requested forward/lateral speed without running away or drifting.
* **Angular Velocity Tracking:**

$$r_{\text{ang\_vel}} = \exp\left( -\frac{(\omega_z - \omega_z^{\text{cmd}})^2}{\sigma_\omega^2} \right)$$



Enforces heading/yaw turns in response to remote commands.
* **Base Height & Posture:**

$$r_{\text{height}} = \exp\left( -\frac{(z_{\text{base}} - z_{\text{target}})^2}{\sigma_z^2} \right)$$



Penalizes collapsing or hyperextending the legs, keeping the duck biped at its nominal ~25 cm operating height.

#### Stability & Gait Style Constraints

* **Orientation / Upright Regularization:** Penalizes roll and pitch tilts away from the vertical gravity vector:

$$r_{\text{upright}} = -\Vert{}\text{projected\_gravity}_{xy}\Vert{}^2$$


* **Foot Clearance & Air Time:** Encourages clean stepping and rhythmic foot clearance rather than dragging feet or jittery micro-steps.
* **Air Time Reward:** Bonus awarded for keeping the swing foot airborne for a target duration, preventing scuffing.

#### Hardware Lifespan & Sim-to-Real Penalties

Because the XL330 servos are small plastic/metal-geared actuators, aggressive sim motions can burn them out or strip gears:

* **Torque / Action Magnitude:** Penalizes commanding extreme motor torques:

$$r_{\text{torque}} = -\Vert{}\tau_t\Vert{}^2$$


* **Action Rate (Jerk Mitigation):** Penalizes high-frequency oscillations and step-to-step jerk:

$$r_{\text{action\_diff}} = -\Vert{}a_t - a_{t-1}\Vert{}^2$$


* **Joint Velocity & Acceleration Limits:** Penalizes exceeding the thermal and mechanical operating envelopes of the Dynamixel gearboxes.
* **Foot Impact Force:** Penalizes slamming feet hard into the floor to prevent shock damage to ankle mounts.

---

### 3. Sim-to-Real Domain Randomization

The reward function alone is insufficient for zero-shot hardware transfer. During MuJoCo rollout generation in `microduck_rl`, domain randomization is injected across every batch:

1. **Actuator Latency:** 10–40 ms random delay buffers between action computation and simulated torque application.
2. **Dynamic Friction & Floor Restitution:** Randomized contact parameters to handle wood, tile, and carpet.
3. **Payload & Center of Mass (CoM):** Random offsets applied to base mass (±10%) and torso inertia matrices to account for battery degradation, camera tilts, or beak grasping payloads.
4. **Motor Friction & Damping:** Perturbations to joint friction coefficients to match unmodeled gear backlash.

Once training converges, the policy is pruned, exported to standard `.onnx`, and copied onto the duck’s onboard filesystem, where `robotd` feeds the real observation vector into ONNX Runtime every 20 ms.

For a walkthrough showing the transfer from MuJoCo PPO training to the ONNX export deployed on the duck hardware, check out [From MuJoCo PPO Training to a Safe ONNX Robot Handoff](https://www.youtube.com/watch?v=YuT-8D2If8U). This video is relevant as it directly covers the pipeline bridging Microduck's PPO simulation training to its onboard ONNX runtime execution.
