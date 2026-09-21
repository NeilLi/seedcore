# Microduck Reinforcement Learning Study

Date: 2026-09-21
Status: Supporting study for simulator and policy integration; no training or deployment performed

This document adapts the user's
[RL attachment](sources/microduck_rl_user_supplied.md). Its reward explanations
are useful conceptual material, but its observation dimensions and numeric
randomization claims must not become an implementation contract without
checking the selected upstream revision.

The later [architecture infographic](sources/microduck_rl_architecture_user_supplied.md)
adds a useful overview of the training stack. Its elements are incorporated
below with corrections against the same pinned revisions. The
[source ledger](microduck_source_ledger.md) records claim status; this is source
inspection, not a reproduced training or hardware result.

## Verified Starting Point

The pinned [Microduck RL README](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/README.md)
describes PPO using mjlab/MuJoCo Warp, 50 Hz policies and ONNX deployment.
Training requires a suitable CUDA environment; CPU simulation/inference is a
separate workflow. The export path embeds observation normalization in the
ONNX graph. A raw checkpoint conversion is not equivalent.

The initial integration should use a compatible upstream artifact and preserve
its provenance. Establish repeatable inference before spending effort on
reward tuning or new training.

## Training Loop And Deployment Path

The infographic combines training, inference and physical hardware in one
picture. Keep the feedback loop and the artifact handoff distinct:

```text
OFFLINE TRAINING
task commands + simulated robot state -> actor observation
  -> PPO actor -> joint target offsets -> actuator/contact simulation
  -> next state, observations and task rewards -> rollout collection
  -> PPO actor/critic update -> repeat

ARTIFACT HANDOFF
selected checkpoint + observation normalizer -> supported ONNX export
  -> parity/evaluation report -> separately reviewed promotion

ADMITTED ROBOT EXECUTION
SeedCore ActionIntent -> PDP -> ExecutionToken -> bounded robot session
  -> native observation builder -> ONNX actor -> local controller/interlocks
  -> physical attempt -> telemetry -> SeedCore evidence closure
```

PPO optimization and its critic belong to training. The deployed actor performs
inference; it does not run PPO updates at each control tick. The documented
50 Hz is the policy/control cadence, not the optimizer update rate or a
SeedCore admission requirement. Physics substeps and control decimation must
be recorded separately. The README's 4,096 parallel environments are an example
training configuration, not a required deployment resource or throughput claim.
[Pinned training overview](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/README.md)

| Technology | Role | SeedCore handoff requirement |
| --- | --- | --- |
| mjlab / MuJoCo Warp | Task environments and GPU physics rollouts | Pin task, model, dependency versions and simulation timing |
| PPO / `rsl_rl` | Actor/critic optimization from rollouts | Record training configuration, seeds and selected checkpoint |
| BAM M6 and friction/backlash extensions | Approximate actuator and transmission behavior | Preserve model parameters and enabled variants |
| Task rewards and curricula | Define objectives and the learning schedule | Evaluate physical failure modes beyond aggregate reward |
| ONNX exporter | Package actor inference with normalization | Compare exported outputs against the reference policy |
| Native robot runtime | Build observations and control hardware | Validate artifact compatibility, local limits and transitions |

## Actor Observation And Action Contract

The current documented actor input contains 61 values. The grouping below is
the runtime layout, not a generic locomotion example:

| Slots (zero-based) | Signal | Width |
| --- | --- | --- |
| 0–2 | Base angular velocity | 3 |
| 3–5 | Projected gravity | 3 |
| 6–19 | Joint position relative to home | 14 |
| 20–33 | Joint velocity | 14 |
| 34–47 | Previous action | 14 |
| 48–50 | Velocity command | 3 |
| 51–54 | Head command | 4 |
| 55–60 | Body command | 6 |
| Total | Proprioception/history plus command | 61 |

Thus the infographic's **48 + 13 = 61** grouping is useful, but its signal list
is not the serialization order: angular velocity precedes projected gravity
in the pinned runtime. The 13 command values have specific meanings:

| Command | Components | Important qualification |
| --- | --- | --- |
| Twist, 3 | `vx`, `vy`, yaw rate | Freeze units, reference frame and admitted bounds |
| Head, 4 | Neck pitch, head pitch, head yaw, head roll | Four joint-oriented commands, not a quaternion |
| Body, 6 | Position deltas `x,y,z` and angles roll/pitch/yaw | Slot presence does not establish six-axis tracking by every policy |

The pinned control design holds body `x`, `y` and yaw at zero. The selected
walking configuration retains the body-command slots but sets the body-pose
tracking reward weight to zero. Record the actual task/runtime behavior before
exposing these slots as user-controllable capabilities.
[Runtime command layout](https://github.com/pollen-robotics/microduck/blob/768e1922715942d8c6aa5254c6d1cd35cf099482/docs/design/robotd-design.md#22-one-observation-builder),
[walking configuration](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/src/mjlab_microduck/tasks/microduck_velocity_env_cfg.py)

The output contains 14 actions for ten leg and four neck/head joints; the mouth
is excluded. Preserve exact ordering, scaling, frames and nominal offsets.
The runtime converts offsets using its home pose and action scale before local
filtering/limits. A 14-value output is not an unrestricted raw motor interface.
Do not add the attachment's optional two-value gait clock to this input.
[Runtime observation contract](https://github.com/pollen-robotics/microduck/blob/768e1922715942d8c6aa5254c6d1cd35cf099482/docs/design/robotd-design.md#22-one-observation-builder)

The walking configuration removes simulator-only base linear velocity from
the actor while retaining it for the critic. Hardware-available actor inputs
do not prohibit privileged critic inputs or simulator-derived rewards.
[Walking configuration](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/src/mjlab_microduck/tasks/microduck_velocity_env_cfg.py)

## Reward Concepts From The Attachment

A weighted reward combines tracking objectives and regularization:

```text
R_t = sum_i w_i * r_i(s_t, a_t)
```

Representative expressions from the supplied study:

| Term | Conceptual expression | Purpose |
| --- | --- | --- |
| Linear tracking | exp(-‖v_xy - v_cmd‖² / sigma_v²) | Follow requested planar velocity |
| Yaw tracking | exp(-(omega_z - omega_cmd)² / sigma_omega²) | Follow requested turning rate |
| Height tracking | exp(-(z_base - z_target)² / sigma_z²) | Encourage task-appropriate posture |
| Upright penalty | -‖projected_gravity_xy‖² | Discourage excess tilt where the task requires upright behavior |
| Torque penalty | -‖tau‖² | Discourage high actuator effort |
| Action-change penalty | -‖a_t - a_(t-1)‖² | Reduce abrupt changes |

Foot clearance, air time, joint limits and impact measures can complement
these terms. These expressions summarize the attachment, not the exact active
reward dictionary or weights for every upstream task. Action difference is a
smoothness proxy, not a direct physical jerk measurement.

Walking, ground pickup, recovery and rolling have different desirable
postures and contacts. Read the chosen task's actual reward configuration
before tuning. Overall robot height is not the model's base-frame target.
A high aggregate return does not establish safe hardware behavior.

## Reward Design And Training Lessons

The infographic highlights upstream training lessons, rather than one reward
formula applied identically to every task:

| Technique | Intended effect | Evaluation question |
| --- | --- | --- |
| Progress-based shaping | Pay for improvement in posture/progress rather than repeatedly occupying a rewarded state | Can the policy exploit resets, oscillation or a stationary failure pose? |
| Rate-limited internal targets | Make commanded transitions track a gradual setpoint | Does the chosen task implement the target schedule, and does hardware follow it? |
| Delayed smoothness penalties | Introduce action-change/torque-change penalties as a skill develops | Does the curriculum reduce jitter without suppressing the task? |
| State/contact conditions | Constrain what counts as a successful maneuver | Can an unintended contact or posture still collect the reward? |
| Scale-aware regularization | Account for the dynamics of a small body | Are impact, saturation and recovery acceptable under the test profile? |

The upstream playbook's 3.5–5.5 rad/s tumbling example is a task-design
observation, not a permissible user command or hardware safety limit. Vertical
acceleration and action-change penalties are training signals, not certified
impact protection. The image's “exploitation resistance” is a design goal that
needs adversarial episode review, not proof that reward exploitation is solved.
[Upstream training notes](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/AGENTS.md),
[reward implementations](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/src/mjlab_microduck/tasks/mdp.py)

The upstream `AGENTS.md` is cited here as research material; its instructions
do not replace SeedCore's repository rules or authorize a training run.

## Sim-To-Real And Domain Randomization

The upstream project emphasizes BAM actuator modeling, voltage/friction
variation and backlash variants. Preserve the model configuration with each
evaluation so policy comparisons use a known actuator model.
[Actuator/model overview](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/README.md#actuator-model)

The BAM M6 model represents XL330 voltage control, back-EMF and nonlinear
friction. SeedCore should preserve that actuator configuration rather than
assuming an ideal position controller is equivalent. The local friction
extension scales the velocity-independent friction budget; simply randomizing
MuJoCo `dof_frictionloss` does not substitute for it because BAM clears that
field. The encoder-feedback extension also distinguishes output-side position
from the motor-side velocity used for back-EMF/friction.
[Actuator implementation](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/src/mjlab_microduck/actuator/friction_dr_bam.py)

Backlash variants insert a passive hinge in series with each policy-controlled
joint. The documented variant has **±1° play, 2° total**, not an interchangeable
±1°/±2° setting. The policy observes position/velocity through the play; for
position this combines the servo and backlash coordinates. Passive joints must
not be counted as additional policy actions or accidentally selected by joint
limit/pose rewards. These variants preserve the 61-input/14-output interface.
[Backlash task transformation](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/src/mjlab_microduck/tasks/backlash.py)

Collision geometry is also task-specific: `robot_walk.xml` simplifies contacts,
while `robot_groundcontact.xml` represents contacts needed for recovery and
ground maneuvers; roller/backlash variants change the model again. Preserve
the exact model identity. A walking-model success does not establish that a
roll, fall or recovery was tested with suitable collision geometry.
[Model inventory](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/README.md#robot-models)

The attachment names latency, floor contact, payload/CoM and motor
friction/damping as useful variation categories. Its 10–40 ms latency,
±10% mass variation, and across-every-batch wording are not universal defaults.
At the pinned walking revision, mass/inertia scaling is 0.95–1.05;
enabled flags and sampling cadence vary by term. Inspect configuration rather
than copying a single global range.
[Configuration and events](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/src/mjlab_microduck/tasks/microduck_velocity_env_cfg.py)

Keep sensor delay distinct from actuator delay. Record friction, voltage,
backlash, calibration and payload assumptions separately. Simulation rewards
may use ground truth that must never leak into the deployed actor.

## Behavior Families And Policy Switching

| Image example | Pinned-source interpretation | SeedCore status |
| --- | --- | --- |
| Walking | Velocity task family | First integration candidate; acceptance pending |
| Stand-up | StandUp/VelStand families | Separate posture/recovery preconditions and evidence required |
| Bow | Illustrative pose; no dedicated Bow task found in the inspected registry | Do not advertise a tested bow skill; establish a supported implementation first |
| Kick | BallKick family | Separate object, workspace and outcome contract required |
| Forward roll | Roulade family | Separate contact model, starting conditions and physical acceptance required |

[Pinned task registry](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/src/mjlab_microduck/tasks/__init__.py)

A common tensor shape enables interface reuse but is insufficient to validate
a live handover. Check home offsets, action scaling, command meaning, previous
action/history, starting posture and controller transition/reset behavior.
The image's “without re-initialization” claim is not a SeedCore guarantee.
Loading/promoting a policy artifact and selecting an already enrolled behavior
are distinct operations. A behavior switch must remain inside explicitly
admitted scope; a changed artifact or widened skill scope needs fresh admission
and session reconciliation under the integration contract.

## Evaluation And Export Handoff

For the next-stage experiment, capture:

1. upstream commits, selected task, robot/actuator model and policy hash;
2. training seed/configuration and baseline/candidate identities;
3. observation ordering, frames, scaling, home pose and normalizer provenance;
4. golden observations with expected outputs and a declared numeric tolerance;
5. tracking error, falls, action smoothness, saturation and failure episodes;
6. held-out terrain/payload/delay conditions within a documented test envelope;
7. ONNX shape/finite-output checks and runtime compatibility;
8. promotion decision and retained rollback artifact.

Include actuator parameters, backlash variant, collision-model digest,
command-slot semantics, simulation timestep/decimation, actual environment count
and reward/curriculum settings in that record. Use transitions and interrupted
episodes when evaluating a policy family, not only steady-state walking.

Pruning is not assumed to be a required export step. Validate the supported
exporter for the pinned revision. Passing evaluation produces a candidate;
installation, activation and physical motion remain separately admitted
operations under the [integration plan](microduck_integration_plan.md).

The pinned exporter calls the runner's ONNX export and attaches metadata; its
normalization is part of the exported model. Preserve the exporter version and
artifact digest, and test numeric parity rather than inferring deployability
from an `.onnx` suffix.
[Export implementation](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/src/mjlab_microduck/export.py)

The attachment's linked video has not been verified and is retained only in
the original source copy, not treated as technical evidence.
