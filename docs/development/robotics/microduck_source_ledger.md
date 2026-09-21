# Microduck Source Ledger

Date: 2026-09-21
Status: Supporting source record; revalidate when selecting the implementation baseline

## Provenance

The two user-supplied studies and later architecture infographic are preserved
under [sources](sources/README.md). They contain useful explanations but did not
specify upstream commits.
Repository source was inspected to identify integration-critical differences.

| Source | Revision inspected | Use |
| --- | --- | --- |
| [Microduck](https://github.com/pollen-robotics/microduck/tree/768e1922715942d8c6aa5254c6d1cd35cf099482) | `768e1922715942d8c6aa5254c6d1cd35cf099482` | Onboard design and runtime boundary |
| [Microduck RL](https://github.com/pollen-robotics/microduck_rl/tree/cb70b792312d559a4da09064d92009079671815f) | `cb70b792312d559a4da09064d92009079671815f` | Training, model/export workflow and configuration |
| [Architecture](https://github.com/pollen-robotics/microduck/blob/768e1922715942d8c6aa5254c6d1cd35cf099482/docs/design/architecture.md) | Same runtime revision | Daemon responsibilities |
| [Control design](https://github.com/pollen-robotics/microduck/blob/768e1922715942d8c6aa5254c6d1cd35cf099482/docs/design/robotd-design.md) | Same runtime revision | Bus, observation and local control |
| [Walking configuration](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/src/mjlab_microduck/tasks/microduck_velocity_env_cfg.py) | Same RL revision | Actor/critic separation and randomization settings |
| [Actuator extension](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/src/mjlab_microduck/actuator/friction_dr_bam.py) | Same RL revision; inspected 2026-09-21 | BAM friction scaling and encoder feedback |
| [Backlash transformation](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/src/mjlab_microduck/tasks/backlash.py) | Same RL revision; inspected 2026-09-21 | Passive joints and observation/reward selection |
| [Reward functions](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/src/mjlab_microduck/tasks/mdp.py) and [training notes](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/AGENTS.md) | Same RL revision; inspected 2026-09-21 | Progress rewards, gradual targets and task-specific training lessons; notes are research material |
| [Task registry](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/src/mjlab_microduck/tasks/__init__.py) | Same RL revision; inspected 2026-09-21 | Named behavior families; no dedicated Bow task found |
| [ONNX export](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/src/mjlab_microduck/export.py) | Same RL revision; inspected 2026-09-21 | Exporter path, embedded normalization and metadata |

These are research snapshots, not a tested compatible runtime/policy release
pair. M0 must select that pair and record its actual artifact hashes.

## Reconciliation With Supplied Material

| Attachment statement | Treatment in the revised studies |
| --- | --- |
| Typical ten-joint actor with optional gait clock | Use the pinned 61-input/14-output contract; freeze exact layout before integration |
| No simulator-only observations | Applies to deployed actor; critic and reward computation may use privileged simulation state |
| ~25 cm base-height reward target | Overall height does not establish the task's base-frame target |
| 10–40 ms delay and ±10% mass across every batch | Conceptual examples only; obtain enabled terms, ranges and cadence from task configuration |
| Prune, export, copy policy | Pruning unverified; supported export/normalization and controlled promotion required |
| TIOCEXCL eliminates competing opens | Privileged opens need additional ownership controls |
| Same transaction implies virtually zero sensor skew | Measure sample freshness/alignment; serialized replies are not simultaneous acquisition |
| Gamepad always preempts app/LLM; remote lease already exists | Unverified guarantee; test ownership and preemption at the selected revision |
| Every watchdog failure produces a stable stand/sit | Unverified universal outcome; test the specific local response |
| All configuration watched by inotify | Per-setting reload/restart behavior must be checked |
| Linked RL video directly demonstrates the pipeline | Unverified; preserved as supplied material only |

The [architecture study](microduck_architecture_study.md) and
[RL study](microduck_rl_study.md) cite the relevant sources alongside the
corrected explanations.

## Architecture Infographic Reconciliation (2026-09-21)

The [preserved infographic](sources/microduck_rl_architecture_user_supplied.md)
is a conceptual reference. The same pinned sources were inspected; no upstream
baseline was upgraded and no training/runtime behavior was executed.

| Image element | Assessment against inspected sources |
| --- | --- |
| Approximately 25 cm / 800 g | Matches the pinned RL README's approximate description; not measured SeedCore hardware specifications |
| 14 XL330 actuators / 14 DOF | Describes the policy's joint set; pinned runtime design includes 15 physical servos with the mouth outside the 14 actions |
| 48 proprioception/history + 13 commands = 61 observations | Supported layout; preserve serialization order, frames, normalization and offsets |
| Four-dimensional head pose | Four neck/head angular commands; not a quaternion |
| Six-dimensional body pose | Shared slots, not a guarantee of six-axis control; runtime design zeros x/y/yaw, walking config gives body tracking zero reward weight |
| PPO at 50 Hz / 4,096 environments | 50 Hz refers to policy/control cadence; 4,096 is a documented training example, not optimizer frequency or a mandatory batch size |
| BAM M6, voltage, back-EMF and friction | Supported modeling approach; friction randomization must use the BAM path |
| Explicit backlash ±1° / 2° | Documented variant is ±1° per joint, 2° total; do not interpret as ±2° |
| Output-side encoder through play | Supported in backlash observation and position-feedback code; preserve distinction from motor-side velocity |
| Simplified contacts and ground-contact model | Task-specific model choice; cannot transfer walking-model results to ground maneuvers automatically |
| Progress rewards, gradual targets, delayed smoothing | Supported as task-specific implementations/training lessons, not one universal recipe or guaranteed exploitation prevention |
| 3.5–5.5 rad/s / impact penalties | Upstream training-note example and reward guidance; not admission limits or measured safety guarantees |
| Walk, stand-up, kick, forward roll | Corresponding registered task families exist; availability of a tested compatible artifact remains to be established |
| Bow | Illustration lacks a dedicated task in the inspected registry; implementation and acceptance unresolved |
| Hot swapping without re-initialization | Shared shape supports compatibility; transition state, artifact identity and local runtime behavior still require validation |
| Standard sim2real fails / high performance | Qualitative comparison and positioning; no comparative benchmark or SeedCore performance result supplied |

The [integration plan](microduck_integration_plan.md) translates these details
into M0 model/command metadata, M1 parity and M5 evaluation requirements.

## Open Before Implementation

- Select policy artifact and runtime versions that actually work together.
- Read the executable RPC schema and actual authority/ownership behavior.
- Establish endpoint identity and access control across socket, BLE and WebRTC.
- Determine safe command ranges, session expiry, cancellation and local preemption.
- Validate observation parity, control timing and telemetry sampling on target.
- Confirm hardware availability, board/IMU revision and signer capability.
- Record which upstream design assertions are implemented and tested.

No Microduck checkout, simulation run, training job, hardware operation, or
policy installation was performed as part of this documentation reorganization.
