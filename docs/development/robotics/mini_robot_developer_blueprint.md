# Mini-Robotics Developer Blueprint: The Golden Reference

Date: 2026-10-14
Status: Proposed engineering profile and delivery sequence; no Fast Spine firmware or WebSerial robot bridge is implemented

## Goal And Present Foundation

Build one supervised browser-to-robot experiment whose proposal, permission,
attempt and outcome are distinguishable. The existing planar browser lessons,
1/2/3-link orbit studio and dual-ABI C++/Wasm core supply simulation. The
Microduck MJCF package supplies a separate native MuJoCo reference; the current
browser core cannot simulate that floating-base robot.

The [18-month execution plan](../strategy/seedcore_physical_ai_execution_plan_2026_2028.md)
owns dates, cost targets and phase gates. The
[Fast Spine protocol proposal](fast_spine_protocol_spec.md) owns proposed MCU
sessions, framing/authentication review, interruption and evidence requirements.
This blueprint is neither a ready-to-flash binary nor a tested hardware design.

## Reference Profiles

| Profile | Proposed hardware / runtime | Purpose and acceptance |
| --- | --- | --- |
| Planar learning fixture | Current C++/Wasm 1/2/3-link arm, no hardware | Local simulation lessons; broader SIM-3 gates remain open |
| Fast Spine bench | One ESP32-S3 board, 1 → 3 STS3215 servos, USB CDC / WebSerial | Qualify admitted chunks, local deadlines/watchdog, physical stop and evidence for this fixture |
| Native Microduck | Pinned body/policy/runtime, native RPC and `robotd` | M0–M5 native acceptance; preserve balance, control and sole bus ownership |
| Later portability | RP2350 or one LeRobot/SO-100-family profile | Add only after independent integration, actual demand and support capacity |

The ESP32-S3 is the first proposed board because its browser-flashing path can
be qualified with `esp-web-tools`. RP2350 uses a separate UF2/update route.
BLE and additional MCU families are later work; chipset availability alone
does not establish compatible firmware.

## Cost And Electrical Register

| Item | Planning assumption | Evidence before freezing |
| --- | --- | --- |
| Controller | $12 recurring board parts BOM target at quoted volume | Itemize MCU/module, USB, TTL interface, watchdog/stop input, protection and connectors; record assembly/test/yield separately |
| Servos | STS3215 for the small arm; founder-proposed $8–$12 unit sourcing target | Current quotation, electrical variant, torque/speed, load, feedback coverage, cables and failure behavior |
| Mechanics | Printed arm and bounded bench workspace | Pinch/fall/load assessment, joint limits and reproducible CAD/build manifest |
| Servo power | Separate reviewed supply and distribution | Actual voltage/current budget, brownout, grounding, level compatibility and protection |
| Host | Existing supported laptop/Chromebook | Web Serial access, managed-device policy and first-time/repeat onboarding tests |
| Complete kit | Selected kit target below $300 excluding existing host | Landed BOM, assembly/test, enclosure, packaging, freight/tax, repair and support costs |

Targets are not supplier prices or purchase authorization. Do not apply a
small-arm BOM to a 14-actuator Microduck. Record engineering and provisioning
costs separately from recurring hardware.

STS3215 uses **TTL**, not RS-485. Qualify half-duplex direction and logic levels
for the selected board/servo revision; an RS-485 servo requires a separate
electrical profile. Source: [Feetech STS3215 description](https://www.feetechrc.com/20210430-56680.html).
USB-C does not establish that the host can power the servo load.

Small mass and compliant materials can reduce impact energy, but they do not
make stall contact harmless. Review force/pinch, thermal/electrical and fall
behavior on the actual mechanism before supervised operation.

## Brain, Boundary And Spine

```text
host/browser/cloud model proposes
  -> accountable Agent / ActionIntent
  -> PDP admits or denies
  -> existing ExecutionToken
  -> enrolled execution boundary claims and binds one session
  -> authenticated chunks to MCU
  -> local bounds, deadline and watchdog
  -> captured measurements / configured signer
  -> verifier outcome and operator timeline
```

The browser may display permissions and transport messages; it must not carry
issuer/private fleet keys or mint trusted authority. Serial-port permission and
packet CRC do not authorize motion. The release needs actual device enforcement
and rejection of unsigned/raw development paths.

Microduck follows the native RPC/`robotd` route instead of the arm's MCU raw
joint interface. Reuse existing token/receipt contracts; proposed robot fields
must be versioned and reviewed rather than silently added to frozen constraints.

## Firmware Work Packages

1. **Discovery and enrollment:** boot/connect/flash are non-moving states;
   report pinned device, firmware and profile identities. Provision trust roots
   and a distinct device identity through a reviewed enrollment flow.
2. **Bounded parsing and authentication:** validate full messages before queue
   mutation; fixed buffers and explicit overflow behavior. Keep crypto/parser
   work outside the interpolation tick.
3. **Session enforcement:** claim one token once; bind endpoint, policy/model,
   boot nonce, sequence and deadline. Refresh cannot widen scope, extend expiry
   or revive a revoked/completed session. Restart/reconnect discards motion.
4. **Interpolation and bus:** evaluate a 200 Hz baseline and 500 Hz target;
   validate spline extrema, velocity/acceleration/jerk and transition behavior.
   Measure servo write/read cadence and bus utilization independently.
5. **Local interruption:** heartbeat, command freshness, authority freshness
   and session deadline are separate controls. Freeze their limits before
   tests. Stop response is body-specific; returning home or cutting torque
   is not universally safe. A new packet must never clear a latched stop.
6. **Evidence:** retain required command/state/events and coverage/gaps;
   enrolled signing and verification are separate from motor-loop timing.
   Missing capture cannot become verified completion.

No illustrative CRC-only watchdog snippet is a substitute for these requirements.
The [protocol proposal](fast_spine_protocol_spec.md) contains the acceptance
matrix and first-week design decisions.

## Browser And Flasher Delivery

Start with a split-screen experiment: planar simulation on one side, explicitly
labeled fixture or accepted physical state on the other, and an admission/
interruption/evidence timeline. An out-of-envelope proposal is denied; any
changed trajectory must fit admitted transform semantics or be re-admitted.

For ESP32-S3, prepare a pinned `esp-web-tools` release and board/chip-specific
manifest with image digests, version and recovery instructions. Flashing is
separate from key enrollment and motor admission. Check wrong-board,
interrupted-flash and recovery behavior; motor enable remains unavailable
during update. Secure boot and the USB update path need joint qualification.

Public hosting requires HTTPS and compatible Web Serial support; first access
uses a user-selected port. Test managed Chromebooks and actual OS/browser
combinations. Sources: [ESP Web Tools](https://esphome.github.io/esp-web-tools/)
and [Chrome Web Serial](https://developer.chrome.com/docs/capabilities/serial).
The 10-second repeat connect and 30-second flash goals must report permission,
enrollment, verification and recovery separately.

## Evidence And Delivery Gates

The Microduck 61/14 mapping is policy-specific. Arm telemetry uses its own units,
dimensions, joint order and calibration under the shared evidence envelope.
Retain the samples required by the declared result predicate, not just a hash.
A Rust verification result does not itself sign a sensor frame; identify the
actual signer and distinguish host assertions from device-rooted capture.

G1 authority/session acceptance precedes bench motion; G2 evidence and measured
hardware acceptance precede a physical showcase/pilot. Validate denied, expired,
forged, replayed, revoked, wrong-endpoint, unplugged, restarted, stale-sensor,
local-stop and incomplete-evidence cases on the actual ingress.

Scale one supervised lesson and one live pilot before 3–5 sites. Produce
10 → 25 → up to 100 cumulative kits only after manufacturing QA, demand, cash
and support reviews. Open core/firmware and optional paid provisioning,
conformance/support and hosted governance are separate offers.

## Related Documents

- [Physical AI strategy](physical_ai_strategy.md)
- [Microduck integration plan](microduck_integration_plan.md)
- [Robot execution contract](robot_execution_contract.md)
- [Mini simulator implementation plan](mini_robot_simulator_implementation_plan.md)
- [Service operating plan](robot_service_operating_plan.md)
- [OEM partnership brief](../../application/oem_partnership_brief.md)
