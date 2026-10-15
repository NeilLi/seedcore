# Simulation-first Microduck and Fast Spine acceptance

Date: 2026-10-15
Status: Offline candidate and controller rehearsal delivered; physical qualification open

No robot is connected. These tools open no serial ports, native robot RPCs or
motor interfaces. The Microduck adapter is read-only; the Fast Spine runtime
updates mathematical joint state in memory. Neither completes native Microduck
M2–M4 or authorizes a physical attempt.

## Source and policy inspection

The [candidate deployment manifest](../../../packages/robotics-profiles/microduck-sim-v1.json)
records source revisions, source-file hashes, body integrity, joint ordering,
full-precision home, action scale, policy period and tolerances.

| Input | Inspected pin / disposition |
| --- | --- |
| Runtime | `pollen-robotics/microduck` at `2703e0900da3e3d84114461ca91400c374d1d741` |
| Earlier documented runtime | `768e1922715942d8c6aa5254c6d1cd35cf099482` is unavailable in the local checkout; not silently treated as verified |
| RL reference | `pollen-robotics/microduck_rl` at `cb70b792312d559a4da09064d92009079671815f` |
| Body | Existing Microduck 0.1.0 MJCF package, independently pinned by manifest digest |
| Policy repository | `pollen-robotics/microduck-policies` at `665ae4eb20bfe13bca1ef4ea6d4bb6b4a096e448` |
| Selected offline policy | `alpha_walking.onnx`; SHA-256 `e36332d383997d51401897734cd3e79cf5038406feddb18b4d57ecfb141daa6c` |
| Additional inspected policy | `velstand.onnx`; SHA-256 `2fc7f8ee6acd7d0d3f66a99927b5d5a56589aeed02ec714de329b252d5ccf492` |

Both ONNX files are 793,705 bytes, accept float32 `obs[1,61]` and return
float32 `actions[1,14]`. Normalization is embedded in the graph. Rounded ONNX
home metadata is checked with a separate tolerance; it never replaces the
full-precision runtime home vector. `velstand` declares a different training
commit and backlash task from the RL reference above. Do not substitute it into
the selected candidate without a new compatibility review.

Local paths, relative to the SeedCore repository root:

```text
artifacts/microduck/665ae4eb20bfe13bca1ef4ea6d4bb6b4a096e448/alpha_walking.onnx
artifacts/microduck/665ae4eb20bfe13bca1ef4ea6d4bb6b4a096e448/velstand.onnx
artifacts/microduck/665ae4eb20bfe13bca1ef4ea6d4bb6b4a096e448/manifest.json
tests/fixtures/microduck/golden-v1.json
```

The ignored `artifacts` cache is local, not a committed model distribution.
To reproduce the official download with an installed Hugging Face CLI:

```bash
hf download pollen-robotics/microduck-policies \
  manifest.json README.md alpha_walking.onnx velstand.onnx \
  --revision 665ae4eb20bfe13bca1ef4ea6d4bb6b4a096e448 \
  --local-dir artifacts/microduck/665ae4eb20bfe13bca1ef4ea6d4bb6b4a096e448
```

**Matching training-checkpoint outputs are not available.** The committed 16
golden cases are generated from the pinned, unmodified upstream Rust
`Observation::build` and ONNX's independent `ReferenceEvaluator`. Tests compare
SeedCore's observation builder and ONNX Runtime against those outputs. This
checks observation semantics and artifact inference replay, not checkpoint to
export parity or compatibility of the runtime/body/policy combination.

To close training parity, obtain the exact checkpoint and training revision,
export configuration and normalization state, plus raw observations and expected
actions from that checkpoint. Preserve original float32 inputs, joint/command
order, previous-action convention, tolerances and provenance. Freeze those
independent outputs before comparing them with the export.

## M1 read-only profile

`MicroduckReadOnlyDriver` supports `offline_mujoco` and an explicitly supplied
`daemon_fake_io` snapshot provider. Selecting `hardware` fails without falling
back to simulation. Native startup sets offline home state and calls
`mj_forward`; it does not call `mj_step`, run a policy or enable motors.
The named `imu_ang_vel` sensor supplies the trunk gyro. All motion methods deny.
Fake snapshots reject stale, future, replayed, malformed and non-finite values.

The raw 61-vector is 48 state/history components followed by 13 command
components. It is not a temporal stack of 48 frames. Positions are relative to
home; velocities are rad/s; previous actions remain raw policy outputs. Fourteen
policy joints omit the mouth from the 15 physical channel order. Body x/y/yaw
remain uncommandable in this contract.

The existing HAL simulation service selects this adapter with
`HAL_SIM_BACKEND=microduck_readonly`. Its hardware configuration is unchanged.

## Run the bounded session studio

Use the project virtual environment. The optional `robotics-policy` dependency
group supplies ONNX tooling; native read-only checks also need the existing
MuJoCo workbench dependency. Build the verifier with Rust 1.89.0 or a compatible
installed toolchain:

```bash
RUSTUP_TOOLCHAIN=1.89.0 cargo build --locked --manifest-path rust/Cargo.toml -p seedcore-verify
.venv/bin/python scripts/robotics/serve_session_lab.py
```

Open `http://127.0.0.1:8766/studio/session-lab.html`. Select one simulated servo
before three. Try a bounded move, forged/expired/wrong-endpoint admission and an
out-of-envelope proposal. Revoke an admitted attempt, or hide/close the tab to
stop command refresh. Download the receipt and Python/Rust dispositions after
the attempt is fenced.

The host owns ephemeral simulation issuer, receipt and channel keys. The
browser receives no private keys and cannot submit arbitrary joint targets.
Its proposal fixtures do not invoke the production Agent Gateway or PDP.
Production identity, registration and approval context are not emulated as live
authority. This adapter refuses unsupported live token obligations.

The left pane is an independent planar Wasm dynamics preview. The right pane
records the bounded quintic controller simulation; the preview is not the source
of receipt observations and is not a Microduck digital twin. The host watchdog
polls independently of browser timers. Hiding the tab stops refresh and does not
automatically resume an attempt when the tab returns.

Receipts bind spec, token, principal, endpoint, boot, model, policy and runtime
digests with contiguous integer-time/microradian events. An admitted host signer
seals them with Ed25519. Both verifiers require caller-supplied expected spec
and token digest; missing, conflicting or out-of-envelope evidence quarantines.
The downloadable public trust bundle describes this local host identity. A
recipient must establish key trust independently; a bundle delivered with an
artifact is not an external trust anchor. Every result explicitly reports
`physical_acceptance: false`. This is not production RESULT_VERIFIER closure.

## Reproduce the checks

```bash
.venv/bin/python scripts/robotics/freeze_fast_spine_protocol.py
.venv/bin/python -m pytest -q \
  tests/test_microduck_readonly.py tests/test_fast_spine_protocol.py \
  tests/test_fast_spine_sessions.py tests/test_fast_spine_rust.py \
  tests/test_fast_spine_studio.py tests/test_fast_spine_release.py
node tools/mini-sim/verify.cjs
```

The policy replay test skips explicitly when its local cached policy or optional
runtime dependency is absent. It never downloads a model during tests. Rust
integration tests similarly require the built verifier; missing-tool skips must
not be reported as parity acceptance.

Regenerate the independent golden cases only after reviewing changed pins:

```bash
.venv/bin/python scripts/robotics/generate_microduck_golden.py \
  --runtime-checkout ../microduck \
  --policy artifacts/microduck/665ae4eb20bfe13bca1ef4ea6d4bb6b4a096e448/alpha_walking.onnx \
  --output tests/fixtures/microduck/golden-v1.json
```

## Firmware review preparation and open gates

There is no matching ESP32-S3 firmware source/image, connected fixture or
available `idf.py` here. No install button or placeholder binary is published.
The [release packet preparer](../../../scripts/robotics/prepare_fast_spine_release.py)
accepts an existing ESP-IDF build, an independently hashed merged image and a
declared full source revision. It checks target metadata, contained paths,
bounded/nonoverlapping layout and hashes, then snapshots a new local review
directory with an ESP Web Tools candidate manifest. It never marks it released,
qualified or hardware-tested. It does not validate binary format, boot trust,
firmware behavior or source-to-binary correspondence.

Use `--help` for arguments. Prepare/pin the merged image with the actual board's
reviewed flash settings first, following [ESP Web Tools firmware preparation](https://esphome.github.io/esp-web-tools/#preparing-your-firmware).
The build inventory follows the [ESP-IDF build system](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-guides/build-system.html).
Do not run a generated candidate through a flasher before its open release gates
are reviewed.

Next dependent work remains:

1. Obtain independent checkpoint outputs and reconcile the runtime/body/policy
   pair before declaring full M0/G0 or training parity.
2. Bind native Microduck M2 to actual gateway/PDP/revocation context and the
   pinned `robotd` boundary. The separate simulation fixture does not close it.
3. Implement and cross-build reviewed MCU enforcement, identity enrollment,
   every motor ingress restriction, local watchdog/stop and bounded capture.
4. Qualify one servo before three; record revocation propagation, response
   initiation and observed stopping separately under unplug/restart/fault/load.
5. Complete device-signer provenance, minimum physical M3, production verifier
   closure, flash recovery and M4 before a physical demo or classroom release.

The $12 controller BOM remains an unquoted target. Hardware access, board/pinout,
calibration, supplier quotes and procurement are unset. No partner outreach,
purchase, public deployment or firmware flashing occurred.
