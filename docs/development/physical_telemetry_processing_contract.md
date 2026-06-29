# Physical Telemetry Processing Contract

Date: 2026-06-29
Status: Development contract for replay-grade embodied telemetry processing

## Purpose

This document turns advanced embodied-AI data-processing patterns into a
SeedCore-native telemetry enhancement path.

The goal is to process real-world physical data into replay-grade evidence and
training sidecars without changing the authority boundary:

```text
model or agent proposes
PDP decides
ExecutionToken scopes the admitted attempt
edge / HAL telemetry proves physical closure
replay / RESULT_VERIFIER accepts, rejects, reviews, or quarantines
```

High-rate sensor processing, temporal alignment, digital-twin parity, semantic
trimming, or dataset export can improve evidence quality. They must not become
execution authority by themselves.

## Current Baseline

SeedCore already has the right primitives to extend:

- `SignedEdgeTelemetryRefV0` and `EdgeTelemetryEnvelopeV0` provide digest-bound
  signed telemetry references.
- `HALCaptureEnvelope` carries media refs, environmental telemetry, trajectory
  hash, device identity, transition receipt, and signer metadata.
- `EvidenceBundle.telemetry_refs` preserves the telemetry refs used for closure.
- `freshness_sla_edge_stress_schedule.md` defines simulator, prototype edge,
  trusted edge, and robotics handoff lanes.
- `world_action_model_architecture_reference.md` defines WAM rollout and runtime
  safety receipt sidecars without making WAMs authority-bearing.

The missing piece is a processing contract for multi-rate physical streams:
capture, alignment, episode slicing, digital-twin replay, quarantine, and
training export.

## Adoption Judgment

### Pick Now: Replay-Grade Physical Episode Contract

SeedCore should define a `PhysicalEpisodeTraceV0` contract before adopting a
specific data platform.

It should preserve:

- workflow id, `ActionIntent` ref, token id, endpoint id, and transition
  receipt id
- stream refs for camera, depth, LiDAR, IMU, encoder, joint state, motor
  current, torque, force, gripper, and zone/custody evidence
- capture clock metadata: source clock, monotonic sequence, observed-at time,
  clock skew estimate, and synchronization method
- alignment summary: target frame rate, interpolation/backfill method, maximum
  alignment error, dropped samples, and gap counts
- episode boundaries: start reason, stop reason, idle-trim view hash, raw
  archive hash, and operator/runbook annotations
- replay summary: digital-twin profile, command replay hash, physical-vs-sim
  delta, threshold, and verifier disposition
- data export refs for sidecar training datasets, clearly separated from the
  authority evidence bundle

This gives SeedCore a stable artifact even if the underlying capture stack is
ROS 2 bags, MCAP, HDF5, shared memory, Kafka, Parquet, or a vendor simulator.

### Pick Now: Alignment Quality Gates

Temporal alignment should become an explicit verifier-facing quality gate for
robotics and high-rate physical telemetry:

| Condition | Default outcome | Reason code |
| --- | --- | --- |
| Missing stream required by policy | `quarantine` | `telemetry_stream_missing` |
| Clock skew beyond profile bound | `quarantine` | `telemetry_clock_skew` |
| Alignment gap exceeds profile bound | `quarantine` | `telemetry_alignment_gap` |
| Dropped-sample rate exceeds bound | `review` / `quarantine` | `telemetry_sample_loss` |
| Physical-vs-sim delta exceeds threshold | `quarantine` | `digital_twin_parity_mismatch` |
| Episode raw archive missing | `quarantine` | `telemetry_raw_archive_missing` |
| Training export lacks replay link | reject export | `training_trace_unbound` |

These checks strengthen closure and dataset hygiene. They do not decide allow by
themselves; PDP allow still requires typed context, freshness, policy scope, and
evidence requirements.

### Pilot Now: Capture Substrate Abstraction

SeedCore should support capture-substrate adapters rather than standardize on
one storage technology too early:

- ROS 2 `rosbag2` / MCAP for robot-system capture and replay-oriented logs
- memory-mapped ring buffers or shared memory for low-latency edge-local capture
- HDF5/SWMR or equivalent chunked stores for lab archive and concurrent read
  workflows
- Parquet plus MP4-style exports for LeRobot-compatible training sidecars

The invariant is the signed digest ref and replay metadata, not the file format.
Raw data stays in an archive; public proof carries redacted digest refs.

### Pilot Next: Digital-Twin Replay Parity

Digital-twin replay should be used as a verifier input and dataset-quality
screen:

```text
physical action vector stream
-> simulator profile replay
-> physical-vs-sim delta
-> parity disposition
-> evidence bundle / quarantine / training export gate
```

Accepted deltas can enrich proof. Breached deltas should quarantine closure or
isolate the episode from positive training data until reviewed. A digital twin
does not replace physical telemetry or signer provenance; it explains whether
the recorded physics are reproducible under the declared model.

### Pick For Sidecar Training: LeRobot-Compatible Export

LeRobot-style export is useful for the WAM/VLA training lane, especially because
current LeRobot docs emphasize standardized multimodal time-series, sensorimotor
signals, multi-camera video, and rich metadata.

For SeedCore, LeRobot export should be a derived sidecar:

- export only after raw telemetry is hash-bound and replay-linked
- keep raw episode archives separate from trimmed training views
- carry labels for source type: human demo, simulator, live robot, WAM-generated,
  verifier-accepted, rejected, or quarantined
- exclude rejected/quarantined episodes from positive training unless explicitly
  used as negative examples
- store language labels as advisory annotations, not policy facts

This lets SeedCore benefit from robot-learning tooling without letting training
datasets become authority sources.

### Track Carefully: VLM Captioning And Semantic Trimming

VLM-generated captions and idle-frame filters are useful for indexing and
training, but they are easy to overtrust.

Rules:

- trimming may create a training view, never delete the raw evidence archive
- VLM captions are search and training annotations, not custody truth
- operator-facing proof should show whether captions were human-authored,
  machine-generated, or verified
- semantic filters must preserve enough pre/post context to replay why the
  episode was accepted, rejected, or quarantined

## Processing Flow

```text
Raw sensor streams
  -> capture substrate adapter
  -> signed stream refs and raw archive hash
  -> temporal alignment / synchronization summary
  -> episode chunking and training-view derivation
  -> digital-twin replay parity check
  -> PhysicalEpisodeTraceV0
  -> EvidenceBundle telemetry_refs / HALCaptureEnvelope
  -> replay / RESULT_VERIFIER disposition
  -> optional LeRobot-compatible sidecar export
```

## Contract Sketch: PhysicalEpisodeTraceV0

```json
{
  "contract_version": "seedcore.physical_episode_trace.v0",
  "episode_id": "episode:handoff:001",
  "workflow_id": "workflow:rct:001",
  "intent_ref": "intent:001",
  "execution_token_id": "token:001",
  "transition_receipt_id": "transition:001",
  "endpoint_id": "robot_sim://pybullet_r2d2_01",
  "capture_profile": "simulator",
  "raw_archive_ref": {
    "uri": "archive://episodes/001",
    "payload_sha256": "sha256:raw"
  },
  "stream_refs": [
    {
      "stream_id": "camera:wrist",
      "sensor_kind": "rgbd_camera",
      "observed_start": "2026-06-29T00:00:00Z",
      "observed_end": "2026-06-29T00:00:06Z",
      "sample_count": 180,
      "payload_sha256": "sha256:camera"
    },
    {
      "stream_id": "joint:arm",
      "sensor_kind": "joint_state",
      "observed_start": "2026-06-29T00:00:00Z",
      "observed_end": "2026-06-29T00:00:06Z",
      "sample_count": 3000,
      "payload_sha256": "sha256:joint"
    }
  ],
  "alignment_summary": {
    "method": "nearest_neighbor_with_backward_fill",
    "target_observation_rate_hz": 30,
    "max_alignment_error_ms": 8.0,
    "clock_skew_ms": 2.0,
    "dropped_sample_count": 0,
    "gap_count": 0
  },
  "episode_bounds": {
    "start_reason": "first_motion_after_token",
    "stop_reason": "transition_receipt_emitted",
    "trimmed_view_sha256": "sha256:trimmed",
    "raw_context_preserved": true
  },
  "digital_twin_replay": {
    "simulator_profile": "robot_sim_fixture",
    "command_replay_sha256": "sha256:commands",
    "state_delta_l2": 0.004,
    "threshold": 0.01,
    "disposition": "pass"
  },
  "training_export": {
    "format": "lerobot_compatible",
    "export_ref": "dataset://rct/episode-001",
    "label_source": "machine_generated_unverified",
    "admission": "sidecar_only"
  }
}
```

## Minimal Next Slice

1. Add a draft `PhysicalEpisodeTraceV0` schema in docs first.
2. Add deterministic simulator fixtures with multi-rate streams:
   - accepted aligned episode
   - missing required stream
   - clock-skew breach
   - alignment-gap breach
   - digital-twin parity mismatch
   - quarantined episode excluded from positive training export
3. Teach the evidence materializer or replay fixture path to surface
   `episode_id`, `raw_archive_ref`, alignment summary, digital-twin disposition,
   and training-export admission.
4. Export a LeRobot-compatible sidecar only after the episode trace is
   replay-linked and non-quarantined.
5. Keep runtime authority unchanged: PDP/token/evidence/verifier remain the
   settlement path.

## External References

- LeRobotDataset v3.0: <https://huggingface.co/docs/lerobot/en/lerobot-dataset-v3>
- LeRobot datasets v3 overview:
  <https://huggingface.co/blog/lerobot-datasets-v3>
- ROS 2 rosbag2: <https://github.com/ros2/rosbag2>
- MCAP ROS 2 guide: <https://mcap.dev/guides/getting-started/ros-2>
- h5py SWMR: <https://docs.h5py.org/en/latest/swmr.html>
- NVIDIA Isaac Lab: <https://developer.nvidia.com/isaac/lab>
