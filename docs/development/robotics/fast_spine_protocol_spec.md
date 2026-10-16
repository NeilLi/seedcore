# Fast Spine Protocol: Simulation v1 and Hardware Proposal

Date: 2026-10-15
Status: Host simulation v1 framing/schemas/session/evidence implemented; MCU firmware and physical WebSerial bridge remain open

## Implemented Simulation Freeze

The [simulation-first acceptance guide](simulation_first_acceptance.md) records
policy paths, parity provenance, reproducible checks and open native/hardware
gates. Generated [v1 contracts](../../../packages/robotics-profiles/fast-spine-v1/)
freeze the localhost rehearsal only. They cannot address a hardware endpoint.

The actual wire envelope is COBS encoded and zero terminated. Before COBS:

```text
header <2sBBIH, little endian (10 bytes)
  magic "SC", version u8=1, type u8, sequence u32, payload_length u16
canonical ASCII JSON payload (maximum 4096 bytes)
HMAC-SHA256("seedcore.fast-spine.wire.v1\0" || header || payload) (32 bytes)
CRC32/IEEE(header || payload || MAC), little-endian u32 (4 bytes)
```

The decoder bounds encoded/decoded buffers, rejects unknown versions/types,
duplicate JSON keys and noncanonical payloads, verifies CRC and MAC before
dispatch, and resynchronizes at a delimiter after an oversized frame. A
provisioned 32-byte host key is mandatory. The public golden-vector key is test
material and must never be enrolled. No reusable key is delivered to the browser.

| Implemented type ID | Payload / effect |
| --- | --- |
| 1 `HELLO` | Non-actuating simulation discovery, sequence 0 |
| 2 `SESSION_OPEN` | Frozen spec plus existing signed ExecutionToken; sequence 0; verify exact spec binding and durably claim once |
| 3 `CHUNK` | Session/endpoint/boot/token digest, strict increasing sequence, relative generated time and 1–32 waypoints |
| 4 `HEARTBEAT` | Same bindings and shared sequence; refresh transport health only |
| 5 `CANCEL` | Fence and discard queued simulated motion |
| 6 `REVOKE` | Persist token revocation, fence and discard queue |
| 7 `STATE` | Reserved; incoming attempts reject as unsupported control |
| 8 `SESSION_END` | Explicit completion only after admitted queued motion has applied |

The host receiver pins issuer keys, requires Ed25519 and the existing frozen
token constraint/precondition shapes, checks endpoint/principal/MOVE/scope,
rejects unsupported live obligations, and binds the canonical spec digest using
existing `payload_hash`. It adds no production token fields or gateway route.
The localhost issuer is explicitly a simulation admission fixture, not a live
PDP. Durable SQLite claim/revocation storage fails closed; consumed tokens stay
consumed after interruption and process restart.

The lesson profile fixes a 1000 ms session, 250 ms command age, 300 ms heartbeat
and 250 ms authority freshness. A separate host thread polls every 5 ms; this is
a scheduling interval, not a measured worst-case response guarantee. Each
session has an immutable monotonic deadline bounded by token expiry. Heartbeat
and fresh commands cannot extend it. Revocation, stale authority/command,
heartbeat loss, clock rollback and local stop fence the attempt. Reconnect
cannot resume it. In-memory pose holds at the last observation after fencing;
that is not a qualified physical stop policy.

The controller appends to a maximum 64-point queue, validates each entire chunk
before mutation, and interpolates zero-end-velocity/acceleration quintics.
For distance d and interval T, extrema are 1.875d/T velocity,
10d/(sqrt(3)T²) acceleration and 60d/T³ jerk. Bounds apply between endpoints.
Queue exhaustion holds pose until fresh intent or the command-age fence; it
does not replay an old segment. Event capture is bounded at 2048 records;
overflow fences and prevents a complete evidence claim.

Host-signed, action-bound simulation receipts have Python and Rust verification.
They capture controller state, not Wasm preview state or physical telemetry.
Incomplete/conflicting evidence quarantines. `physical_acceptance` is always
false. Actual MCU key establishment, hardware signers, native M2 integration,
production RESULT_VERIFIER closure and timing qualification remain open.

## Scope And Profiles

The [Central World schedule](central_world_remaining_delivery_schedule.md)
adds custom-build admission in CW-G01 and conditional configuration/installer
work in CW-F01/CW-F02. Its
[acceptance matrix](central_world_acceptance_matrix.md) owns planned NVS, device
and replay-binding cases. These do not extend the implemented simulation v1
wire schemas. A physical configuration/admission format needs version review,
actual board/firmware compatibility and enrolled trust roots.

Pin the configuration ABI and partition layout; compare generated NVS against
the official generator before using it. A browser configuration blob is not a
trusted grant. Device limits must remain enforced independently; configuration
digest, firmware/body identity, admission and captured evidence must agree.
No private enrollment/issuer key belongs in a public image or generated NVS.

Specify the minimum boundary for a supervised 1–3 DOF tabletop fixture. Use
one ESP32-S3 board, USB CDC / WebSerial and a reviewed Feetech STS3215 TTL
bus. BLE is a later transport qualification. The proposed RP2350 variant
requires its own build, flashing and security profile.

This protocol supports the
[18-month execution schedule](../strategy/seedcore_physical_ai_execution_plan_2026_2028.md).
It does not replace [Microduck's native `robotd` integration](microduck_integration_plan.md),
its controller or its bus ownership. A Microduck bridge must map admitted
bounded intent to the pinned native RPC contract. Raw servo chunks are for the
separate arm fixture, not an alternative remote Microduck motor interface.

The current `tree-lab.html` is a planar research simulator with a 3D camera.
The separate `session-lab.html` pairs it with the host simulation rehearsal.
WebSerial, firmware flashing and physical robot receipts remain proposed.
No current simulator export is a signed physical receipt.

## Authority And Trust Boundary

```text
Browser / model proposal
  -> accountable Agent / ActionIntent
  -> trusted PDP / existing ExecutionToken
  -> enrolled execution boundary: validate, claim once, bind session
  -> authenticated device admission and command channel
  -> MCU local limits / deadline / watchdog
  -> captured telemetry and signer
  -> evidence bundle / Rust verification / RESULT_VERIFIER
```

The browser is a client and transport, not a trusted signer or policy issuer.
Serial-port permission grants communication only. A classroom release must
reject unsigned writes and isolate debug/raw motor interfaces at the actual
device boundary. A CRC-only demonstration is a protocol fixture, not a governed
hardware product.

Reuse the existing `ExecutionToken` and single-use claim semantics. Robot
session bindings and any device admission artifact require versioned schema
review against the [execution proposal](robot_execution_contract.md),
[token lifecycle](../trust-runtime/execution_token_lifecycle_management.md) and
[frozen policy gates](../policy_gate_matrix.md). The simulation reuses existing
token fields; hardware-only extensions below remain proposals, not shipped
device messages or production gateway APIs.

The device must either validate the original token and applicable context, or
validate a reviewed boundary-signed admission record cryptographically bound
to that token and no broader authority. Before choosing the latter, define the
trusted issuer, issuer key provisioning, verification algorithm, scope binding,
durable claim/replay storage and failure behavior. Never accept a browser's
assertion that a token was checked.

## Proposed Hardware Message Extensions (Not Implemented)

| Message | Direction | Required behavior |
| --- | --- | --- |
| `HELLO` / `CAPABILITIES` | Client ↔ device | Non-actuating discovery: device/profile identity, firmware/model digests, boot nonce, protocol version, buffer limits and supported telemetry |
| `ENROLL_STATUS` | Device → boundary | Report registered device/key identity and enrollment status; discovery never enrolls or enables motors automatically |
| `SESSION_OPEN` | Boundary → device | Bind one claimed action/token to device, boot nonce, principal, policy/model/calibration, admitted bounds and a non-extendable local deadline |
| `SESSION_ACK` | Device → boundary | Authenticated acceptance/refusal with session identity, monotonic clock mapping and exact accepted bounds; receipt is not motion completion |
| `CHUNK` | Boundary → device | Authenticated session/sequence and bounded, timestamped waypoints; validate the entire chunk before placing it in a fixed-capacity queue |
| `CHUNK_ACK` | Device → boundary | Separate queued, applied and rejected states; include applied device time and sequence without pretending a queue ACK proves physical success |
| `HEARTBEAT` | Boundary ↔ device | Transport health and authority-context freshness; cannot refresh stale intent or extend a session |
| `CANCEL` / `REVOKE` | Boundary → device | Fence the session and discard queued motion; apply the reviewed local stop behavior; delayed messages cannot resume it |
| `STATE` / `EVENT` | Device → boundary | Sequenced measurements, units, capture time, faults, overflow, local preemption and stop events |
| `SESSION_END` | Device → boundary | Report completion/interruption/fault and observed state with coverage/gaps; verifier separately decides whether evidence is sufficient |

Local operator stop must work without a network request or a valid motion
token. The stop control must not grant permission to resume or to move to a new
posture. Authenticated remote cancellation follows the admitted halt path.

## Proposed Framing And Binding

For the first bench implementation, evaluate a length-bounded binary envelope
with COBS framing and a CRC for corruption detection. Freeze its byte order,
maximum encoded/decoded frame size and canonical authentication input during
the first planning week. Payload schemas and golden byte fixtures must be
reviewed before interoperable firmware is claimed.

Every authority-bearing frame must bind protocol version, message type, device
and boot identities, session/action/token references, sequence, payload length,
payload bytes and authentication context. The MAC/signature covers those
bindings; CRC, USB VID/PID, a serial number or a token hash alone cannot
authenticate a command.

Use bounded parsing, fixed buffers and explicit overflow rejection. Reject
unsupported versions, non-finite values, undeclared joints, bad units, malformed
lengths and unauthenticated frames before motion queue mutation. Decode and
authenticate outside the time-critical interpolation tick. Record rejection
and rate-limit malformed traffic without starving local stop processing.

Prefer an authenticated session key for chunks only after a reviewed key
establishment bound to device, boot nonce and admitted action. The browser must
not possess a reusable device or issuer private key. Key compromise and debug
firmware are separate profiles with explicit limitations, not exceptions to
the classroom release's enforcement.

## Session And Chunk Semantics

1. Boot and connect enter a non-moving state. Querying capabilities, flashing
   firmware, receiving a heartbeat or reconnecting cannot enable motion.
2. Validate/claim the existing token once. Check signature, endpoint, policy,
   freshness, expiry, scope and revocation before a device session is opened.
3. Establish a conservative monotonic deadline from authenticated time and the
   remaining admitted lifetime. Define clock uncertainty/skew; missing valid
   time context refuses admission. Refresh or wall-clock rollback cannot extend
   that deadline.
4. Chunks carry strictly ordered session sequences and an application window.
   Reject old/duplicate/out-of-order commands and late/overlong chunks. Specify
   exact queue-replacement rules; never apply a mixture of rejected and accepted
   waypoints. Sequence exhaustion terminates the session.
5. Joint order, radians, timestamps, velocity/acceleration/jerk limits and
   interpolation rules belong to the pinned profile. Check spline extrema
   between waypoints as well as endpoints; endpoint bounds alone are inadequate.
6. Check command age, queued horizon, authority-context age, local deadline and
   heartbeat independently. An authenticated heartbeat does not prove that the
   planner is still generating fresh intent.
7. Cancel, revoke, local stop, expiry, queue underrun or declared faults fence
   the session. The selected body determines hold, deceleration, torque-off or
   another reviewed local response. Returning to home is an action and may be
   unsafe in the current configuration.
8. Reconnect/restart discards pending motion. A new boot nonce and durable
   boundary claim state prevent replay; stale authority/claim state refuses
   admission. A fresh session requires fresh authorization and reconciliation.

Prefer denial for an out-of-envelope proposal in the hero demo. If a reviewed
transform projects/clamps a trajectory, bind the resulting trajectory digest
and validate its full path before dispatch. It must fit the admitted transform
semantics or return for renewed PDP admission; never silently modify a signed
plan and claim that the original receipt covers it.

Remote revocation cannot arrive instantly through a disconnected link. Bound
the disconnected authority window with local freshness/deadline controls and
measure propagation, response initiation and observed physical stopping
separately. No cloud service is required for the MCU's local stop.

## Timing And Electrical Qualification

| Parameter | Initial planning target | Required measurement / freeze |
| --- | --- | --- |
| MCU interpolation | 200 Hz baseline, evaluate 500 Hz | Worst observed tick jitter, missed deadlines and load including parser/authentication activity |
| Servo bus | Part-specific TTL baud and half-duplex timing | Per-servo write/read cadence, utilization, retries and worst-case 1/3-servo traffic |
| Chunk horizon / refresh | Evaluate 0.5–1.0 s buffered planning | Stop behavior, stale-intent window and queue underrun under measured host/browser stalls |
| Watchdog / command age | No universal numeric limit selected | Set separate limits before acceptance; test failure and disconnected operation |
| Authentication / admission | Outside the interpolation tick | p50/p95/p99 and peak cost on the actual board; no sub-millisecond end-to-end promise |
| Evidence retention | Profile-specific required samples and bounded event buffer | Storage capacity, mandatory coverage, gaps and overflow behavior |

STS3215 uses a TTL interface; an RS-485 transceiver is not the correct bus
interface for that profile. Use reviewed voltage/current, grounding, level
handling and half-duplex direction control. USB host power is not an assumed
servo power supply. Source: [Feetech STS3215 description](https://www.feetechrc.com/20210430-56680.html).

Interpolation rate, bus transaction rate and telemetry rate are separate. The
13,242-byte browser Wasm artifact neither measures MCU firmware size nor
establishes a 500 Hz physical control loop.

## Telemetry And Proof

Extend the existing [physical telemetry contract](../evidence/physical_telemetry_processing_contract.md)
and [hardware evidence contract](../evidence/hardware_anchored_telemetry_mvp_contract.md).
Retain action/token/session binding, device/boot/firmware/model/calibration,
policy and principal references, command/trajectory digest, monotonic capture
times, sequence coverage, observed state, stop/fault events and signer
provenance. Distinguish a host-signed observation from device-rooted evidence.

The Microduck 61/14 policy mapping is not a mandatory arm payload. Each body
declares its measurement/action dimensions and missing-data representation.
Keep denied admission, command acknowledgement, physical outcome and verifier
disposition distinct. Rust verifies signed artifacts; it does not sign sensor
data simply by receiving it. A configured signer seals the applicable receipt.

Missing/stale/conflicting telemetry or failed capture cannot become verified
completion. Signatures establish integrity/provenance under key assumptions;
they do not establish sensor calibration or physical truth. A hash cannot
reconstruct discarded samples.

## Conformance And Web Flashing

Before G2, reproduce token forgery/expiry/replay/revocation, wrong device/boot,
sequence and clock faults, buffer overflow, spline overshoot, unplug, hidden-tab
stalls, MCU restart, local preemption, stale sensors and missing evidence.
Show that no rejection causes motion or automatic resume. Test alternate
ingress and debug firmware separately from the admitted release.

For ESP32-S3, prepare a pinned `esp-web-tools` build and a release manifest with
chip/board identity, image digests, firmware/profile version and recovery path.
Flashing remains separate from enrolling keys and admitting motion. Do not put
fleet signing secrets in static assets or share one reusable device identity.
Qualify secure-boot/update/recovery together on the actual USB configuration.

Public flashing needs HTTPS and compatible Web Serial support. The port chooser
requires a user gesture; managed-device restrictions must be tested. Sources:
[ESP Web Tools](https://esphome.github.io/esp-web-tools/) and
[Chrome Web Serial](https://developer.chrome.com/docs/capabilities/serial).
The RP2350 UF2 route and BLE transport need their own later acceptance.

The first-week review must freeze framing/authentication choices, deployment
trust model, artifact schemas, command limits and stop semantics before
firmware implementation. This proposal is not a ready-to-flash binary.
