# PythonRobotics applicability to SeedCore

Date: 2026-10-08
Status: Source assessment and implemented offline experiment; no hardware integration

PythonRobotics is useful as a readable robotics reference and source of baseline
experiments. SeedCore owns accountability, admission and evidence; robot-native
controllers own motor control and local safety. Algorithm prototypes belong on
the advisory side of that boundary.

## Source review and corrections

Reviewed upstream revision
[`cdd0cc888802b584c2d654ca85e3c5460973487d`](https://github.com/AtsushiSakai/PythonRobotics/tree/cdd0cc888802b584c2d654ca85e3c5460973487d).
The [upstream README](https://github.com/AtsushiSakai/PythonRobotics/blob/cdd0cc888802b584c2d654ca85e3c5460973487d/README.md)
supports the educational-reference framing. Its advertised sample environment
uses Python 3.13 and NumPy, SciPy, Matplotlib and cvxpy. SeedCore currently targets
Python 3.12 with pinned NumPy; importing an entire upstream checkout is not an
established compatible dependency strategy. Individual algorithms have different
imports, shared helpers, model assumptions and plotting behavior.

The supplied paths need correction:

- [DWA](https://github.com/AtsushiSakai/PythonRobotics/blob/cdd0cc888802b584c2d654ca85e3c5460973487d/PathPlanning/DynamicWindowApproach/dynamic_window_approach.py): `PathPlanning/DynamicWindowApproach/`.
- [Stanley](https://github.com/AtsushiSakai/PythonRobotics/blob/cdd0cc888802b584c2d654ca85e3c5460973487d/PathTracking/stanley_control/stanley_control.py): `PathTracking/stanley_control/`.

The inspected DWA example uses a circular/rectangular planar robot and velocity
sampling. Its selection loop can retain a colliding trajectory when all costs
are infinite, and its stuck heuristic can change the returned command after
predicting the returned trajectory. These are reasons to adapt and test the
interface before use. It is not a plug-and-play hardware collision-avoidance layer.

Stanley and the [pure pursuit example](https://github.com/AtsushiSakai/PythonRobotics/blob/cdd0cc888802b584c2d654ca85e3c5460973487d/PathTracking/pure_pursuit/pure_pursuit.py)
use vehicle steering geometry. They cannot directly replace Microduck balance or
accept arbitrary model-generated waypoints as motor authority. Simple mathematics
also does not establish embedded suitability: timing, numerical precision,
memory, sensor calibration and the hardware control interface need measurements.
Visualization does not establish determinism; random sources, configuration,
versions, initial state, time steps and termination must be controlled explicitly.

Upstream is MIT licensed. Any future copied extraction must retain the applicable
copyright and license notice. The experiment added here is original SeedCore code
using the algorithmic idea; it vendors no upstream implementation and adds no
runtime dependency.

## Applicability decisions

| Suggestion | Decision for SeedCore | Concrete fit or missing prerequisite |
| --- | --- | --- |
| Lightweight headless algorithm experiments | Apply now | Pure functions, synthetic fixtures, reproducible output and bounded work; no middleware needed for these experiments |
| DWA local navigation | Apply as offline baseline | Circular planar velocity proposals and short-horizon collision checks; body/profile, sensing, stopping and session enforcement required before hardware |
| A*/Dijkstra and D* Lite | Useful later | Candidate routes when a navigation task, map frame, resolution, inflated footprint and map freshness contract exist |
| Stanley/pure pursuit | Defer direct integration | Car-like steering examples; a walking body needs a validated path-to-body-velocity layer and native balance controller |
| EKF/UKF | Defer to sensor adapter work | Need actual sensor rates, frames, timestamp handling, calibration, noise and covariance validation; an estimate is neither identity proof nor authority |
| Mapping, ICP and SLAM | Defer | No inspected Microduck map/sensor contract establishes these as current requirements; uncertainty and stale-map cases need explicit handling |
| Arm inverse kinematics | Relevant separate reference | Mini Robot Lab already has a two-link engine; do not replace its physics or mix in a mobile-base model |
| MPC/LQR, aerial and bipedal demos | Research references | Dynamics, actuator interfaces and real-time requirements differ; no drop-in Microduck controller |
| Embedded ports and ROS removal | No current implementation | Choose on measured requirements; this reference does not justify replacing onboard control or existing HAL |

## Implemented application

[`navigation_sandbox.py`](../../../src/seedcore/robotics/navigation_sandbox.py)
provides `assess_command` and `propose_dynamic_window`. Inputs are a typed planar
state, constant speed/yaw-rate command, circular obstacle snapshot and synthetic
configuration. Coordinates are metres in one fixed world frame; yaw is radians.
The forward-only model intentionally omits reverse, gait, balance, friction,
actuator lag, moving obstacles, sensor uncertainty and world boundaries.

The sampler intersects configured velocity limits with the acceleration window
from the current velocity. It includes endpoints, current velocity and zero when
reachable. Candidate rollouts use exact constant-twist kinematics, an integer
step count and conservative swept-segment clearance, inflated for the arc's
deviation from the chord. Touching the inflated obstacle counts as collision.
Ranking uses endpoint distance, clearance and turn magnitude with stable sampling
and tie ordering. It is a deliberately small DWA-inspired baseline, not upstream
behavioral parity or a complete implementation of braking-admissible DWA.

All colliding candidates yield `no_feasible_candidate` with no command. A
zero-speed output, when selected, remains a simulated candidate; no output is an
emergency stop or evidence that a moving robot has stopped. Reports identify
`OFFLINE_ADVISORY_NO_ACTUATION`, the model, candidate count, trajectory and clearance.
An obstacle-free scene uses null clearance rather than non-finite JSON.

This checks only a finite horizon under ideal constant commands. Acceleration
bounds check command increments, not motor ramps or stopping-distance envelopes.
Conservative arc inflation may reject otherwise clear paths. Local minima and a
small sample grid may produce poor progress or miss feasible routes. A candidate
does not prove goal arrival, collision freedom beyond the modeled scene or a
successful physical attempt. It is not a `RESULT_VERIFIER` result or signed evidence.

Run from the repository root:

```bash
PYTHONPATH=src .venv/bin/python scripts/robotics/navigation_sandbox_demo.py --scenario clear
PYTHONPATH=src .venv/bin/python scripts/robotics/navigation_sandbox_demo.py --scenario obstacle
PYTHONPATH=src .venv/bin/python scripts/robotics/navigation_sandbox_demo.py --scenario blocked
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_navigation_sandbox.py
```

The CLI records its complete fixture/configuration alongside assessments. It has
no HAL, network, token or task-dispatch connection. It does not modify the Mini
Robot Lab arm engine or the multi-robot coordinator. Tests exercise analytic
motion, collisions between samples, arc clearance, limits, malformed inputs,
blocked scenes, repeatability and the finite-horizon limitation.

## Gate for a future live adapter

Use this as supporting M1 research without changing the active Microduck M0–M4
sequence. A live adapter would need:

1. A reviewed body model and capability profile with measured stop behavior,
   footprint, velocity/acceleration limits and obstacle-sensing coverage.
2. Timestamped observations bound to robot identity, sequence and coordinate
   frame; explicit freshness, uncertainty and missing-sensor behavior.
3. An accountable Agent converting a proposal into an `ActionIntent`; PDP
   admission and an endpoint-bound, scoped, unexpired, non-revoked token/session.
4. Local command enforcement, watchdog/interruption and native safety control;
   each updated command stays within admitted bounds. Network policy calls stay
   outside the native control loop.
5. Action-bound telemetry and receipts closed by replay/`RESULT_VERIFIER`, including
   denied, expired, revoked, interrupted, blocked and incomplete-evidence cases.

Simulation results may inform an operator's review. They cannot admit a session,
promote a learned controller or clear quarantine. Repeated deterministic gate
failure requires surfacing the verifier/runbook evidence rather than tuning away
the gate. See the [execution contract](robot_execution_contract.md),
[policy gates](../policy_gate_matrix.md) and [active queue](../current_next_steps.md).

## Local verification on 2026-10-08

- Navigation and existing multi-robot runtime tests: 70 passed.
- All three CLI scenarios produced valid JSON with the expected candidate,
  obstacle rejection and blocked-scene outcomes.
- `verify_q2_verification_contracts.sh`: passed, including Python, TypeScript,
  fixture HTTP and degraded-edge gates. Its optional Postgres integration lane
  was skipped because `SEEDCORE_ENABLE_RESULT_VERIFIER_PG_TESTS` was not enabled.
- `verify_authz_graph_rfc_phases.sh`: 79 unit tests passed; the live verification
  stage could not connect to `127.0.0.1:8002/api/v1/pkg/status` (connection refused).
  Live authorization verification remains unverified; see
  [host bring-up](../../../deploy/local/README.md) for the runtime prerequisites.

These checks establish offline software behavior, not hardware acceptance.
