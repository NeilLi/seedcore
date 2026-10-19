# M0 / CW-D01: 14–20 October source-register review

Date: 2026-10-19
Status: Inventory recorded before the 20 October boundary; qualification open
Owner roles: Integration lead and catalog/mechanical curator

The [machine-readable register](../../../packages/robotics-profiles/reviews/2026-10-19-m0-cw-d01.json)
pins the reviewed local inputs and separates reference facts from physical
acceptance. No hardware is connected, selected for purchase, or qualified.
Existing catalog documents, assembly byte pins and Fast Spine contracts are unchanged.
CW-D01 remains open; this record closes the window's **inventory task**, not G0.

## First bench candidates and unresolved facts

| Item | Reference fact / candidate | Open before a hardware profile |
| --- | --- | --- |
| Controller | ESP32-S3-DevKitC-1-N8R8, using WROOM-1-N8R8, is an identified ordering variant. The historical v1.0 guide maps native USB to GPIO19/20 and notes octal-memory GPIO35–37 restrictions. | Actual PCB revision and module marking; pinned schematic/layout/dimensions; boot/debug/USB ownership; UART direction/buffer circuit; supply isolation and quote. No GPIO assignments are frozen. |
| Servo | STS3215 manufacturer specification A/0 (2020-04-10) identifies a TTL half-duplex interface. Its input-voltage table lists 4–7.4 V; 6 V and 7.4 V are operating-point columns. | Exact supplier SKU/applicable unit revision, current drawing, connector view/polarity, electrical tolerances, loaded limits and stop response. It is not an RS-485 device. |
| Power | No battery/BEC, fuse, cable or connector SKU is selected. MCU and servo loads need separately reviewed rails and a defined signal reference. | Full-charge/source transients, regulated rail setpoint, derated continuous/peak capacity, conversion losses, wiring/fusing, stop path and USB backfeed isolation. Unknown capacity stays blocked. |

Sources reviewed on 19 October: [Espressif v1.0 guide](https://documentation.espressif.com/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.0.html)
(the page also identifies a newer v1.1) and [Feetech A/0 specification](https://www.feetechrc.com/Data/feetechrc/upload/file/20200611/6372749961523760249976542.pdf).
The servo document's SHA-256 is retained in the register; drawings were visually
reviewed on PDF pages 4, 6 and 8. The table and example schematic use different
connector numbering, and the schematic supply label differs from the input
limit. These may involve drawing conventions or revision differences; they
must be reconciled with the actual harness and applicable specification.
**No connector polarity or higher supply voltage is approved by this review.**
A nominal 2S description is insufficient to approve a direct servo supply.
No supplier document becomes a catalog qualification through this register.

The controller's recurring parts BOM remains a **$12 target**, with no quote,
not a development-board price or a measured production cost. Hardware access,
assembly effort and supplier lead times remain unknown. Engineering scope is
one reference bench candidate; no procurement or external contact occurred.

## M0 candidate pins rechecked locally

| Input | Reviewed candidate | Result |
| --- | --- | --- |
| Runtime | `pollen-robotics/microduck` at `2703e0900da3e3d84114461ca91400c374d1d741` | Three source files match manifest hashes at the pinned commit |
| RL/export | `pollen-robotics/microduck_rl` at `cb70b792312d559a4da09064d92009079671815f` | Four source files match at the pinned commit |
| Body | `packages/models/microduck/0.1.0/manifest.json` | Manifest byte hash matches |
| ONNX artifact | `alpha_walking.onnx`, HF revision `665ae4eb20bfe13bca1ef4ea6d4bb6b4a096e448` | Cached 793705-byte candidate hash matches; artifact replay only |
| Historical runtime | `768e1922715942d8c6aa5254c6d1cd35cf099482` | Still unavailable in the local checkout; no silent substitution |
| Fast Spine simulation | Frozen `fast-spine-v1` schemas, framing vector and profile | Generator check passes; physical fields remain null |

Reproduce the pin inventory without network fetches:

```bash
.venv/bin/python scripts/robotics/review_m0_pins.py
.venv/bin/python scripts/robotics/freeze_fast_spine_protocol.py
```

The first command checks **pinned git objects**, not sibling worktree HEADs,
and writes `artifacts/robotics/m0-cw-d01/pin-review.json`. Optional
`--runtime-repo` and `--rl-repo` arguments locate existing checkouts. Missing or
mismatched candidates fail the command; the report contains relative artifact
references, not private machine paths. Register input hashes are review facts;
a changed profile requires a new dated review.

The [deployment profile](../../../packages/robotics-profiles/microduck-sim-v1.json)
retains 61 observations (48 state/action components plus 13 command components),
14 policy actions and 15 physical servo channels, the mouth insertion, home
values and action scaling. No ABI or behavior limit changed in this review.
Independent training/checkpoint/export references, runtime/body/policy
compatibility, native parity, MCU firmware/enrollment and physical watchdog
measurements remain open. Use the [Fast Spine protocol](fast_spine_protocol_spec.md)
for the implemented simulation contract; its 5 ms watchdog poll is not a measured
physical stopping time. Progress one servo to three only after the required
native and fixture gates pass.

Next review: 20 October inventory boundary, then the CW-D01 drawing/pin/rail
qualification window (26 October–1 November). Missing hardware does not block
CW-A02's offline proxy-authoring work.

CW-A03 adds no physical qualification. The machine register now names the
26 October–1 November follow-up for harness numbering, applicable input limits
and regulated/derated servo rail/BEC design; all remain open.
