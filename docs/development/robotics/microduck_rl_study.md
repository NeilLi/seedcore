# Microduck Reinforcement Learning Study

Date: 2026-09-17
Status: Supporting study for simulator and policy integration; no training or deployment performed

This document adapts the user's
[RL attachment](sources/microduck_rl_user_supplied.md). Its reward explanations
are useful conceptual material, but its observation dimensions and numeric
randomization claims must not become an implementation contract without
checking the selected upstream revision.

## Verified Starting Point

The pinned [Microduck RL README](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/README.md)
describes PPO using mjlab/MuJoCo Warp, 50 Hz policies and ONNX deployment.
Training requires a suitable CUDA environment; CPU simulation/inference is a
separate workflow. The export path embeds observation normalization in the
ONNX graph. A raw checkpoint conversion is not equivalent.

The initial integration should use a compatible upstream artifact and preserve
its provenance. Establish repeatable inference before spending effort on
reward tuning or new training.

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

The output contains 14 actions for ten leg and four neck/head joints; the mouth
is excluded. Preserve exact ordering, scaling, frames and nominal offsets.
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
| Linear tracking | exp(-||v_xy - v_cmd||² / sigma_v²) | Follow requested planar velocity |
| Yaw tracking | exp(-(omega_z - omega_cmd)² / sigma_omega²) | Follow requested turning rate |
| Height tracking | exp(-(z_base - z_target)² / sigma_z²) | Encourage task-appropriate posture |
| Upright penalty | -||projected_gravity_xy||² | Discourage excess tilt where the task requires upright behavior |
| Torque penalty | -||tau||² | Discourage high actuator effort |
| Action-change penalty | -||a_t - a_(t-1)||² | Reduce abrupt changes |

Foot clearance, air time, joint limits and impact measures can complement
these terms. These expressions summarize the attachment, not the exact active
reward dictionary or weights for every upstream task. Action difference is a
smoothness proxy, not a direct physical jerk measurement.

Walking, ground pickup, recovery and rolling have different desirable
postures and contacts. Read the chosen task's actual reward configuration
before tuning. Overall robot height is not the model's base-frame target.
A high aggregate return does not establish safe hardware behavior.

## Sim-To-Real And Domain Randomization

The upstream project emphasizes BAM actuator modeling, voltage/friction
variation and backlash variants. Preserve the model configuration with each
evaluation so policy comparisons use a known actuator model.
[Actuator/model overview](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/README.md#actuator-model)

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

Pruning is not assumed to be a required export step. Validate the supported
exporter for the pinned revision. Passing evaluation produces a candidate;
installation, activation and physical motion remain separately admitted
operations under the [integration plan](microduck_integration_plan.md).

The attachment's linked video has not been verified and is retained only in
the original source copy, not treated as technical evidence.
