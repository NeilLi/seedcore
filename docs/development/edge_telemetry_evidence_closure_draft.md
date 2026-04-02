# Draft: signed edge telemetry and twin settlement (Workstream 3)

This note seeds **Q4 forensic-block population** and **digital-twin / physical closure** linkage. It is a design sketch, not a frozen contract.

## Signed edge telemetry (motor, load, environmental)

- **Envelope**: `EdgeTelemetryEnvelopeV0` with `telemetry_id`, `edge_node_ref`, `asset_ref`, `observed_at` (UTC), `sensor_kind` (e.g. `motor_torque`, `weight_cell`, `temperature`), `samples` (ordered numeric series or aggregate stats), `nonce`, and `signer` (`key_ref`, `algorithm`, `signature`).
- **Payload hash**: canonical JSON (stable key order) → SHA-256 → embedded in the envelope and in the **physical-presence** fingerprint component at closure.
- **Replay**: verifier holds public key material or cert chain reference; offline replay recomputes hash and checks signature before accepting telemetry as evidence.

## Twin settlement atom

- **Twin mutation record**: `twin_commit_id`, `mutation_kind`, `pre_state_hash`, `post_state_hash`, `policy_snapshot_ref`, `decision_id`.
- **Physical closure**: at operator-confirmed handover, bind `twin_commit_id` to localized evidence: custody transition receipt IDs, signed edge telemetry envelope IDs, and optional vision / scan artifact refs.
- **Invariant**: `post_state_hash` must match the twin state implied by custody + telemetry bundle; mismatch forces **quarantine** or **review_required** in the forensic block.

## Next implementation steps (non-binding)

1. Pydantic / JSON Schema for `EdgeTelemetryEnvelopeV0` under `seedcore.models` (versioned).
2. Coordinator hook to persist envelope refs on the governed receipt path.
3. Extend fixture generators to emit synthetic signed samples for HIL-style tests.
