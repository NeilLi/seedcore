# World-Action Model Architecture Reference

Date: 2026-06-29
Status: Reference architecture; sidecar to the current RCT execution path

## Purpose

This note translates current World-Action Model (WAM) research signals into a
SeedCore-native architecture enhancement path.

The goal is not to replace SeedCore's current commerce-centered Restricted
Custody Transfer (RCT) wedge, the PDP hot path, the `ExecutionToken` lifecycle,
or replay / `RESULT_VERIFIER` closure. WAMs belong in the proposal,
simulation, trajectory-stress, and evidence-enrichment lanes until specific
outputs are converted into typed, policy-admitted context.

SeedCore's structural rule remains:

```text
model or agent proposes
Agent is accountable
PDP decides
ExecutionToken scopes the admitted attempt
HAL / actuator executes
evidence and replay close the loop
```

## What WAMs Add

A WAM jointly reasons over observations, future world transitions, and action
sequences. In robotics terms, it can produce candidate futures and candidate
actions from video, state, language, and embodiment context.

For SeedCore, that is valuable in four bounded ways:

- better physical-world proposal quality before `ActionIntent` creation
- richer simulation rollouts for toxic-path and trajectory-stability tests
- replay-visible world-rollout evidence for operators and verifiers
- offline training data for advisory students, model audits, and sidecar robot
  skills

Those advantages do not make the WAM an authority source. A WAM output is a
candidate plan, candidate trajectory, or candidate evidence ref until the PDP
admits a typed request and the execution boundary receives a scoped token.

## Current Repo Baseline

SeedCore already has the important authority hooks for a WAM sidecar:

- `docs/development/vla_2026_optimizations.md` keeps VLA/robotics work outside
  the critical RCT wedge.
- `src/seedcore/ml/tuning/lerobot_tuner.py` and
  `src/seedcore/ml/distillation/vla_distillation.py` provide early LeRobot and
  trace-replay training scaffolds.
- `src/seedcore/hal/robot_sim/actuator/actuator_adapter.py` blocks robot
  behavior execution unless a valid `ExecutionToken` is present.
- `tests/test_robot_sim_week4_integration.py` validates token rejection,
  endpoint constraints, transition receipts, revocation, E-STOP cutoff, and
  evidence capture for the robot-sim HAL lane.
- `docs/development/freshness_sla_edge_stress_schedule.md` defines simulator,
  Jetson, trusted-edge, and robotics-handoff stress lanes where robot telemetry
  is evidence, not authority.

This means WAM work can be added as a sidecar without changing the existing
execution spine.

## Architecture Placement

```text
World observations / operator goal / task context
  -> WAM sidecar proposes candidate rollout and action sequence
  -> SeedCore adapter compiles a typed ActionIntent
  -> PDP evaluates pinned policy, delegation, freshness, and evidence
  -> scoped ExecutionToken is minted or withheld
  -> HAL / controller enforces token, endpoint, zone, and safety bounds
  -> signed telemetry, trajectory hash, and transition receipt are emitted
  -> replay / RESULT_VERIFIER accepts, rejects, reviews, or quarantines
```

The WAM sidecar should be placed before `ActionIntent` admission or inside
simulation / verification tooling. It should not sit between PDP allow and HAL
execution in a way that can rewrite the authorized act.

## Enhancement Lanes

### 1. WAM Proposal Adapter

Add an adapter that converts WAM outputs into SeedCore request material:

- observation refs: camera, state, point cloud, force, or simulator refs
- candidate rollout refs: predicted frames, predicted state deltas, and action
  vectors
- embodiment metadata: robot profile, action dimensions, frame rate, control
  loop assumptions, and allowed tools
- risk annotations: out-of-distribution flag, trajectory anomaly, joint-limit
  proximity, contact uncertainty, and operator-review hints
- proposed `ActionIntent`: principal, asset/resource, operation, scope, TTL,
  endpoint, zone, and expected payload hash

Only the typed `ActionIntent` and policy-admitted context package enter the PDP.
The raw WAM rollout remains advisory evidence unless policy explicitly requires
and validates a signed rollout ref.

### 2. Replay-Visible Rollout Evidence

For physical or robot-adjacent workflows, WAM rollouts should become
replay-visible artifacts:

- `wam_model_ref`
- `wam_checkpoint_ref`
- `dataset_mix_ref`
- `observation_ref`
- `candidate_rollout_hash`
- `candidate_action_hash`
- `trajectory_hash`
- `safety_gate_summary`
- `sim_eval_ref`

These fields help operators explain why a candidate action was proposed and why
it later succeeded, failed, or was quarantined. They do not weaken token,
endpoint, custody, signer, freshness, or verifier requirements.

### 3. Simulation And Toxic-Path Harness

Use WAMs to generate more demanding negative drills before live hardware:

- unseen-object or wrong-asset scenarios
- wrong shelf, wrong zone, or wrong recipient trajectories
- stale camera or delayed telemetry rollouts
- joint-limit, torque, collision, and path-divergence candidates
- cross-embodiment mapping failures
- simulation-to-real mismatch cases

The output should feed the existing negative-path discipline: deny before token
minting when context is insufficient, quarantine when closure cannot be proven,
and preserve replay artifacts for external inspection.

### 4. LeRobot-Compatible Data Lane

LeRobot-style dataset formatting is useful for SeedCore because it can
standardize synchronized video, state, and action traces. SeedCore should treat
that data as a learning and evaluation substrate:

- normalize multi-camera and actuator traces into sidecar training records
- bind each training sample to the SeedCore trace or replay event that produced
  it
- separate human demo, simulator, WAM-generated, and verifier-accepted samples
- exclude failed or quarantined samples from positive policy learning unless
  they are explicitly labeled as negative examples

Dataset records must not be promoted into policy facts merely because a model
trained on them performs well. Promotion still requires the normal contract,
review, and evidence path.

### 5. Edge Runtime Split

WAM inference is likely to be slower than low-level motor control. SeedCore
should preserve a two-loop runtime shape:

- high-level WAM or planner loop proposes trajectory chunks asynchronously
- local controller loop enforces hard motion, joint, torque, collision, and
  E-STOP constraints
- HAL checks the scoped `ExecutionToken` before executing an admitted chunk
- controller safety failures emit signed telemetry and fail closed

Numeric rates such as 7-10 Hz for a heavy planner and 200-500 Hz for a local
controller are deployment-profile targets, not universal SeedCore guarantees.
The portable requirement is the authority split: slow model proposal cannot
override fast controller safety or token scope.

### 6. Model Training And Acceleration Lane

Large WAM training stacks may use DiT-style video/action backbones, distributed
training, fused attention, high-throughput video I/O, and multi-GPU sharding.
Those are infrastructure concerns for the sidecar model lane.

SeedCore should care about the governed artifacts that leave that lane:

- signed checkpoint and model-card refs
- dataset provenance and excluded-sample rationale
- evaluation summary and known failure modes
- sim-eval refs for supported embodiments
- inference endpoint identity and software profile
- rollout hashes attached to governed attempts

Training performance should not become a reason to bypass policy, evidence, or
human-reviewed promotion.

## Authority Rules

| WAM surface | Allowed role | Must not do |
| --- | --- | --- |
| Candidate rollout | Advisory proposal and simulation evidence | Mint authority or rewrite a tokenized act |
| Action vector | Input to typed request or local controller after allow | Execute without a valid token |
| Dataset filter | Training/eval hygiene | Become a policy fact by itself |
| Simulation score | Promotion and regression evidence | Override PDP deny/quarantine |
| OOD/anomaly detector | Safety hint and possible quarantine input | Replace deterministic policy gates |
| Controller safety gate | Local fail-closed enforcement | Expand PDP scope or settle custody |
| WAM checkpoint | Advisory model artifact | Become trusted merely by benchmark rank |

## Minimal Next Slice

The smallest useful implementation slice should be documentation and contract
first:

1. Define a `WamRolloutEvidenceV0` draft contract with model ref, observation
   refs, rollout hash, action hash, embodiment profile, and safety summary.
2. Add deterministic fixtures that show one accepted candidate, one stale
   observation, one endpoint mismatch, and one trajectory-divergence quarantine.
3. Feed those fixtures through the existing robot-sim or evidence-materializer
   path before integrating any live WAM inference service.
4. Only after the contract is replay-visible, connect an external WAM such as
   DreamZero, Cosmos, or a LeRobot-compatible policy as an advisory proposal
   provider.

This keeps the main RCT path intact while creating a clear landing zone for WAM
research.

## External References Checked

These sources informed the reference shape but are not SeedCore authority:

- DreamZero: <https://github.com/dreamzero0/dreamzero>
- LeRobot: <https://github.com/huggingface/lerobot>
- NVIDIA Cosmos: <https://github.com/NVIDIA/Cosmos>
- ManiSkill: <https://github.com/haosulab/ManiSkill>
- DROID robot platform and dataset pointers:
  <https://github.com/droid-dataset/droid>
