# Microduck Source Ledger

Date: 2026-09-17
Status: Supporting source record; revalidate when selecting the implementation baseline

## Provenance

The two user-supplied studies are preserved under [sources](sources/README.md).
They contain useful explanations but did not specify upstream commits.
Repository source was inspected to identify integration-critical differences.

| Source | Revision inspected | Use |
| --- | --- | --- |
| [Microduck](https://github.com/pollen-robotics/microduck/tree/768e1922715942d8c6aa5254c6d1cd35cf099482) | `768e1922715942d8c6aa5254c6d1cd35cf099482` | Onboard design and runtime boundary |
| [Microduck RL](https://github.com/pollen-robotics/microduck_rl/tree/cb70b792312d559a4da09064d92009079671815f) | `cb70b792312d559a4da09064d92009079671815f` | Training, model/export workflow and configuration |
| [Architecture](https://github.com/pollen-robotics/microduck/blob/768e1922715942d8c6aa5254c6d1cd35cf099482/docs/design/architecture.md) | Same runtime revision | Daemon responsibilities |
| [Control design](https://github.com/pollen-robotics/microduck/blob/768e1922715942d8c6aa5254c6d1cd35cf099482/docs/design/robotd-design.md) | Same runtime revision | Bus, observation and local control |
| [Walking configuration](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/src/mjlab_microduck/tasks/microduck_velocity_env_cfg.py) | Same RL revision | Actor/critic separation and randomization settings |

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
