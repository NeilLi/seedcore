# Fast Spine WebSerial Protocol Proposal

Date: 2026-10-14
Status: M2/M4 design proposal; no matching MCU firmware, wire schema or physical bridge is implemented

## Scope And Profiles

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
WebSerial, firmware flashing, authorization and robot receipts are proposed
additions. No current simulator export is a signed physical receipt.

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
[frozen policy gates](../policy_gate_matrix.md). None of the field/message names
below is a shipped token field or gateway API.

The device must either validate the original token and applicable context, or
validate a reviewed boundary-signed admission record cryptographically bound
to that token and no broader authority. Before choosing the latter, define the
trusted issuer, issuer key provisioning, verification algorithm, scope binding,
durable claim/replay storage and failure behavior. Never accept a browser's
assertion that a token was checked.

## Proposed Message Set

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
