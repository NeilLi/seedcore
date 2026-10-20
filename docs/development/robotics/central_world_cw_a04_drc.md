# CW-A04: pure DRC worker, routing proposals, and unknown-aware BOM

Date: 2026-10-20
Owner role: Studio/TypeScript lead and verification reviewer
Status: Local CW-DRC-01..03 implementation and Phase 2 offline software exit; physical qualification remains open (CW-D01)
Entry: CW-A03 committed as `12aa49e`; README status refreshed at `7f9d846`
Effort boundary: Pure TypeScript solver/worker in `ts/packages/drc-solver` and Mini Studio `DRC & BOM` inspector; zero new runtime dependencies

## Supported DRC and BOM contract

`@seedcore/drc-solver` (`ts/packages/drc-solver/src/solver.ts` and `src/worker.ts`) evaluates `seedcore.assembly.v2` drafts against pinned `seedcore.component.v1` catalog artifacts without mutating the assembly store or minting runtime authority. Every report carries:

- `schemaVersion: "seedcore.drc.report.v1"`
- `scope: "offline_proxy_authoring"`
- `physicalAcceptance: false` and `executionAuthority: "none"`
- `catalogProvenance: "verified_local_catalog" | "synthetic_fixture"`
- `catalogDigest`: SHA-256 of the verified catalog index
- `assemblyDigest`: canonical SHA-256 (`seedcore.jcs-safe-integers.v1`) of the assembly
- `electricalPlanDigest`: canonical SHA-256 over the assembly digest, `electrical_nets`, deterministic routing proposals, and bus servo address map
- `disposition: "pass" | "blocked" | "conflict"`

Unknown physical facts (`rating_basis: "unknown"`, null voltage/current/capacity limits, unassigned board/connector pins, null protocol or I2C address, unpriced BOM components, or `simulation_proxy` geometry) produce **`blocked`** findings rather than counting as zero load, permissive voltage, or `$0.00` free parts. A `pass` disposition is reachable only when all referenced components, nets, rails, and mechanical records are fully specified and compatible (exercised in synthetic fixtures explicitly labeled `provenance: "synthetic_fixture"`).

## Rule coverage (`CW-DRC-01`, `CW-DRC-02`, `CW-DRC-03`)

### 1. `CW-DRC-01` — Bus routing, servo IDs, I2C addresses/pull-ups, and GPIO pinout

- **TTL UART servo bus (`TTL_UART_BUS`):**
  - Requires exactly one `controller` and at least one `peripheral` within the controller's reviewed bus capacity (`UART_CONTROLLER_TOPOLOGY`, `UART_BUS_CAPACITY_EXCEEDED`).
  - Rejects mixed protocols on a shared bus (`feetech_sts_ttl` vs. `dynamixel_ttl_v2` or RS-485 -> `UART_PROTOCOL_MISMATCH`) and disjoint logic voltage windows (`UART_LOGIC_VOLTAGE_MISMATCH`). Null protocols or logic bounds remain `blocked` (`UART_PROTOCOL_UNKNOWN`, `UART_LOGIC_VOLTAGE_UNKNOWN`).
  - Assigns deterministic unique servo IDs sorted by `(node_id, interface_id)` within the reviewed protocol range (`[1, 253]` default) and rejects duplicate or out-of-range IDs (`UART_DUPLICATE_SERVO_ID`, `UART_ID_OUT_OF_RANGE`).
- **I2C bus (`I2C`):**
  - Verifies 7-bit peripheral addresses (`8..119`), flagging null addresses as `blocked` (`I2C_ADDRESS_UNKNOWN`) and duplicate addresses on the same bus without a reviewed multiplexer as `conflict` (`I2C_ADDRESS_COLLISION`).
  - Verifies logic voltage overlap and pull-up rail compatibility (`I2C_VOLTAGE_MISMATCH`, `I2C_PULLUP_UNKNOWN`, `I2C_PULLUP_MISMATCH`).
- **Board GPIO and pinout (`gpio_pinout`):**
  - Unassigned signal pins (`pins: []`) remain `blocked` (`GPIO_PINS_UNASSIGNED`).
  - Rejects ESP32-S3 reserved boot/strapping (`GPIO0`, `GPIO3`, `GPIO45`, `GPIO46`), native USB (`GPIO19`, `GPIO20`), SPI flash (`GPIO26`–`GPIO32`), and octal PSRAM/flash (`GPIO35`–`GPIO37`) pins (`GPIO_RESERVED_PIN`), as well as duplicate pin reuse across signal interfaces (`GPIO_PIN_CONFLICT`).
  - Emits deterministic routing proposals for declared nets and unconnected peripherals without mutating `electrical_nets`.

### 2. `CW-DRC-02` — Power rails, conversion efficiency, derating, brownout, and wiring/fusing

- **Unknowns block readiness:** Any component with `rating_basis: "unknown"` or unconnected active power input emits `POWER_UNKNOWN_RATING` / `POWER_RAIL_UNCONNECTED` (`blocked`).
- **Single MCU load accounting:** Each sink node on a rail is counted once regardless of how many signal nets (`TTL_UART_BUS`, `I2C`, `PWM`, `SPI`) it drives; explicit double-counted MCU assertions or direct current summation across unlike voltages fail with `POWER_MCU_DOUBLE_COUNTED` / `POWER_SUMMED_UNLIKE_VOLTAGES` (`conflict`).
- **Voltage window and brownout margin:** Verifies nominal rail voltage and harness drop against sink `[min_v, max_v]` plus required brownout margin (`0.30 V` default -> `POWER_VOLTAGE_MISMATCH`, `POWER_BROWNOUT_MARGIN`).
- **Regulator derating, efficiency conversion, and wire/fuse limits:** Applies reviewed BEC derating (`0.80` default) and reflects downstream regulated rail power to upstream battery rails via $I_{\text{in}} = (V_{\text{out}} I_{\text{out}}) / (\eta V_{\text{in,min}})$ (`0.85` efficiency default). Overloaded BECs, sources, wires, or fuses emit `POWER_OVERLOAD_BEC` / `POWER_OVERLOAD_SOURCE` / `POWER_OVERLOAD_WIRE_FUSE`.
- **Distribution board boundary:** A passive distribution node without source capacity cannot supply a rail or raise upstream BEC/battery capacity (`POWER_DISTRIBUTION_NOT_SOURCE`).

### 3. `CW-DRC-03` — 3D rotated/parallel-axis mass & inertia and unknown-aware BOM

- **3D mass, COM, and full symmetric $3\times 3$ inertia tensor:**
  - Validates each part's mass, part-frame COM bounds, and symmetric positive-definite $3\times 3$ inertia tensor with principal-moment triangle inequalities ($\lambda_1 > 0$, $\lambda_3 \le \lambda_1 + \lambda_2 + \epsilon$).
  - Transforms each node's local COM into world coordinates ($\mathbf{c}_i = \mathbf{p}_i + \mathbf{R}_i \mathbf{c}_{i,\text{local}}$), rotates the full $3\times 3$ inertia tensor into the world frame ($\mathbf{I}_{i,\text{world}} = \mathbf{R}_i \mathbf{I}_{i,\text{local}} \mathbf{R}_i^\top$, preserving off-diagonal terms `ixy, ixz, iyz`), and shifts to the assembly world COM $\mathbf{C}$ via the 3D parallel-axis theorem:
    $$\mathbf{I}_{\text{total}}(\mathbf{C}) = \sum_i \left( \mathbf{I}_{i,\text{world}} + m_i \left( \|\mathbf{d}_i\|^2 \mathbf{I}_3 - \mathbf{d}_i \mathbf{d}_i^\top \right) \right)$$
- **Unknown-aware BOM:**
  - Aggregates quantities by part revision, computing `knownSubtotalUsd` over priced items only (`cost_basis !== "unknown"` and `bom_cost_usd > 0`) alongside `pricedPartCount` and `unpricedPartCount`.
  - Rejects any part that treats an unknown price as `$0.00` free (`BOM_COST_BASIS_CONFLICT`, `BOM_ZERO_OR_NEGATIVE_PRICE`) or claims `supplier_quote` without a dated SKU (`BOM_QUOTE_MISSING_DATE`).

## Worker fencing and Mini Studio integration

`DrcWorkerCoordinator` (`ts/packages/drc-solver/src/worker.ts`) bounds worker payloads to `2 MiB`, assigns monotonic generation tickets, and verifies `{ revisionDigest, assemblyDigest, catalogDigest, authorityEpoch }` before committing a report. Slow or out-of-order worker responses after a newer edit or an ABA undo/redo epoch change return `status: "stale"` and never overwrite the active report.

In Mini Studio (`ts/apps/mini-studio/src/drc.ts`), the **DRC & BOM** inspector tab displays the live disposition badge, `assemblyDigest`, `electricalPlanDigest`, `authorityEpoch`, total mass, world COM, world inertia tensor, unknown-aware BOM lines, routing proposals, and field-linked findings. Selecting a finding highlights the referenced node or mechanical edge in the assembly graph and 3D viewport without mutating the draft.

## Verification evidence (`CW-DRC-01..03`)

```bash
node tools/robotics/verify-authoring.cjs --browser
```

- **Reviewed starter (`tabletop-starter.sc-assembly.json`, digest `2550d184c44a064c6ad6a2245a08f430f257c40ca8f3627e73eeb3fedd452acb`):**
  - Disposition: `blocked` (`0` conflicts, `9` blocked findings across `CW-DRC-01`..`03`).
  - Mass & COM: `0.220 kg`, world COM `[0.00, 0.00, 22.61] mm` (`[0, 0, 0.022613636363636364] m`).
  - Unknown-aware BOM: `$0.00` known subtotal, `0` priced instances, `5` unpriced instances across `5` draft part families.
  - Servo routing: `net_servo_ttl` (`mcu_0:uart` → `servo_0:servo-bus`, assigned ID `1`).
- **Workspace & browser suite:** `97` TypeScript tests, `14` FastAPI tests, and `21` real-Chrome browser exercise groups passing, retained under `artifacts/robotics/cw-a04/`.

## Phase 2 offline exit and remaining gates

With `CW-A01 v2`, `CW-A02`, `CW-A03`, and `CW-A04` passing locally, **Central World Phase 2 (Assembly & DRC) offline software scope is complete**. Physical component qualification (`CW-D01`, 26 Oct–1 Nov window) remains open in parallel. The next implementation package is **Phase 3 `CW-S01`** (restricted assembly-to-MJCF compiler and native MuJoCo comparison in `ts/packages/wasm-sim-bridge`).
