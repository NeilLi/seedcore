# CW-A03: proxy snapping and numeric placement

Date: 2026-10-19
Owner role: Studio/TypeScript lead
Status: Local CW-SNAP-01 implementation; physical qualification remains open
Entry: CW-A02 committed as `4708e06`, including bounded HTTP-error review fixes
Effort boundary: One authoring slice on the existing proxy catalog; no new dependencies

## Supported placement contract

`ts/packages/robot-canvas/src/snapping.ts` supplies pure candidate discovery,
mating/FK math, proposal revalidation and an epoch-bound store commit helper.
The browser supports adding one of the 12 frozen catalog proxies and
reparenting a selected non-root subtree. Numeric positions are world millimeters;
quaternions are explicitly **[w, x, y, z]**, with finite components and unit
squared norm within `1e-8`. Inputs are not heuristically reordered or normalized.
A wrong-order fixture is rejected by its normal/twist mismatch; a unit norm
alone cannot identify every quaternion ordering mistake.

For `seedcore.proxy_mount_v1`, port +Z normals must oppose. The sole final twist
is zero under the existing `opposed_z_rx_pi` convention:

```text
T_rest = T_parent_port * Rx(pi) * inverse(T_child_port)
T_world_child = T_world_parent * T_rest
```

The capture proposal accepts port-origin distance up to **15 mm** inclusive,
with `1e-12 m` comparison slack. Opposing normals and projected in-plane X axes
must fall within a **5-degree** angular capture window. The ghost and committed
rest pose use the exact mate, not the approximate staged pose. This window is
an authoring choice for the illustrative proxy standard, not a physical
clearance, servo limit or workspace safety guarantee. Other standards and
nonzero final twists require a reviewed contract extension.

Candidates sort by numeric distance, then parent node ID, parent port ID and
child port ID using code-unit comparisons, without locale-dependent ordering.
Equal-distance synthetic fixtures prove stability when node/port/catalog arrays
are reordered. Occupied ports, unsupported standards, incompatible genders,
invalid quaternions, normal/twist mismatch and targets inside the moving
subtree are excluded. Moving the assembly root is unsupported.

New mounts are rigid. Existing explicit joint records may be preserved when
reattaching to the same actuator parent/output; moving that joint to another
output is blocked. Declared actuator outputs cannot become housing attachments,
and a new rigid mount cannot silently use a declared rotating output. Moving a
whole subtree preserves its internal joint/electrical records. No servo name,
mesh, normal or capability is used to infer a new axis or articulation.

## Non-committing preview and atomic drop

The local read-only `/api/placement-catalog` provides exact catalog/part bytes.
The browser binds its catalog digest to the accepted scene, verifies raw part
pins and all bounded proxy mesh bytes before enabling the palette, and keeps
catalog load failures outside the accepted assembly state. Catalog records and
the original starter remain unchanged.

The **Place parts** tab supplies catalog/source selection, explicit instance
ID and child port, XYZ/quaternion controls, a nearby staging helper and a ranked
mount selector. Green translucent geometry previews a compatible exact mate;
red geometry is an unmatched staged pose. Preview and Clear do not alter the
graph, history, content digest, authority epoch or saved draft. Reparenting
previews the entire subtree using the root-pose delta.

Keyboard/numeric example on the original starter:

1. Open **Place parts**, choose a sensor-hat proxy and a unique instance ID.
2. Use **Stage near an open mount**, or enter a nearby world pose and find candidates.
3. Inspect the mount and use **Commit mount**. The store validates the completed
   graph and local catalog/assets before replacing the current revision.
4. Undo/redo restores exact accepted graph contents. To move a subtree, select
   its root in the graph and choose **Move selected subtree**.

Shift-drag translates the staged source in the world XY plane while preserving
Z and orientation. Pointer motion only updates preview; release uses the same
atomic commit helper as the numeric button. The numeric path requires no drag.
A canceled pointer gesture does not commit a mount.

A move releases only its old incoming edge for candidate evaluation; all other
occupied ports remain unavailable. The accepted store stays fully connected
throughout preview. On commit, the proposal's full canonical source assembly,
catalog digest, local revision digest and authority epoch must still match.
The epoch prevents reuse after undo/redo returns to identical content. The
selected candidate is recomputed, tampered proposals reject, and the completed
v2 graph passes structural and catalog-aware Python validation before acceptance.
A failed or stale drop preserves the previous graph and scene. Every accepted
edit increments the store epoch; admission remains null and no token is minted.

## CW-SNAP-01 acceptance evidence

```bash
node tools/robotics/verify-authoring.cjs --browser
.venv/bin/python scripts/robotics/review_m0_pins.py
.venv/bin/python scripts/robotics/serve_mini_studio.py --port 8767
```

The authoring verifier cleans generated `dist` directories and rebuilds all
three packages before testing. Reports retain source/build hashes under
`artifacts/robotics/cw-a03/verification.json`; the CW-A02 path remains an
additive compatibility copy. The real-browser exercise writes
`browser-verification.json`, `snapping-preview.png`, `subtree-preview.png` and
other desktop/mobile views in the same CW-A03 directory. Browser binaries are
selected as documented in the [CW-A02 record](central_world_cw_a02_authoring.md).
CI retains software reports; a local browser pass is not a remote CI result.

| Acceptance group | Evidence |
| --- | --- |
| Translated/rotated parent | Independent numeric fixture: world position `[1.04, 2, 2.98]`, quaternion `[0.5, 0.5, 0.5, 0.5]`; parent/child contact origins coincide |
| Capture and determinism | 14.999/15/15.001 mm boundaries, equal-distance port/node ties, reordered inputs, zero final twist and 5/6-degree capture cases |
| Negative mounts | Non-unit/nonfinite/wrong-order fixtures, incompatible standards/genders, occupied endpoints, duplicate node IDs, changed catalog bytes, cyclic targets and unsupported root/joint rebinding |
| Drop isolation | Preview leaves graph/storage unchanged; stale/tampered/ABA proposals and rejected native validation preserve the accepted revision; undo/redo restores digests and selection |
| Native semantics | A real frozen-catalog addition passes Python `validate_assembly`; native and TS rest FK agree |
| Browser task | Keyboard staging/commit, invalid pose recovery, whole-subtree ghost/reparent, cycle-target exclusion, invalid dropdown refusal, authoritative drop rejection, Shift-drag release and desktop/mobile checks |

The initial local slice passed **88 workspace TypeScript tests** (30 CW-A03
cases), **14 authoring API tests**, and **18 browser exercise groups**, with no
skipped cases. Physical fit, interpenetration/collision clearance, electrical
routing/rail capacity and motion safety are not established by these checks.
No two-minute maker-task timing or frame-rate guarantee is claimed.

## Remaining work

CW-A04 is next: a pure worker DRC/net solver and unknown-aware BOM, with findings
bound to the exact assembly/electrical-plan digest. CW-D01's
[dated source register](m0_cw_d01_register_2026_10_19.md) retains the Feetech A/0
connector-numbering and rail/BEC questions for **26 October–1 November**.
The [machine register](../../../packages/robotics-profiles/reviews/2026-10-19-m0-cw-d01.json)
records that open follow-up explicitly. No GPIO, harness polarity, rail setpoint,
hardware profile, admission or physical qualification was issued here.
