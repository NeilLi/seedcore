# SeedCore component registry

Date: 2026-10-20
Status: Phase 1 authoring foundation; 12 illustrative drafts, zero qualified hardware parts

The [v1 schema](schema/v1.sc-part.schema.json) defines four strict blocks:
`identity`, `mechanical`, `electrical` and `hal_and_safety`. The
[catalog](catalog.json) pins the schema, part records and references by SHA-256;
each part pins its original local GLB. Unknown prices, supplier SKUs, electrical
ratings, pinouts and hard hardware limits remain unknown. A schema pass grants
no HAL binding, execution token, firmware compatibility or hardware approval.

## Role in a DIY Mini-Robot Series (Local AI Station + Remote LLM)

The catalog supports successive offline designs on a local development
computer, with optional LLM drafting assistance:

- **Reusable draft records:** boards, servos, sensors, power and brackets can be referenced in multiple supported proxy assemblies. Sensor-head and arm examples remain design candidates; the records do not establish physical interchangeability or a wiring plan.
- **Exact source identity:** every [`seedcore.assembly.v2`](assemblies/README.md) node must resolve its part ID, version and file-byte SHA-256 against the catalog. This rejects missing or altered references. Hash pinning preserves recorded data; it does not establish the truth of electrical specifications. Unknowns remain explicit and block physical readiness.

## Check and inspect

From the repository root, using the existing project environment:

```bash
.venv/bin/python scripts/robotics/build_component_catalog.py
.venv/bin/python -m pytest tests/test_component_registry.py -q
.venv/bin/python scripts/robotics/serve_component_catalog.py
```

Open `http://127.0.0.1:8770`. The read-only viewer loads the actual GLB bytes,
checks their digest, renders their triangles and port normals, and supports
search, categories, pointer/keyboard orbit and zoom. It needs no account,
external service, browser package installation or hardware. The developer host
uses Python/FastAPI; it is not a published Central World deployment. COOP/COEP
and a same-origin CSP are set by this local server. This does not establish a
MuJoCo/ONNX threading or browser performance qualification.

## Twelve draft entries

| Part family / original proxy | Category | Missing qualification |
| --- | --- | --- |
| ESP32-S3 board family | MCU | Named board/revision, GPIO ownership, bus and power ratings |
| Tuya T5 board family | MCU | Named board/revision, SDK and separate provisioning path |
| STS3215 servo family | Actuator | Exact SKU, drawings, TTL protocol/power, IDs and measured limits |
| SG90 servo family | Actuator | Exact manufacturer/SKU, PWM and power/angle limits |
| OV2640 camera module family | Sensor | Board interface/pinout, sensor mode and data-permission path |
| MPU6050 module family | Sensor | Board/pull-up voltage, address selection and frame calibration |
| 8×8 LED module | Actuator/display | Driver and bus unselected; no interface inferred |
| 2S battery pack | Power | SKU, voltage/current/connector/protection data |
| BEC regulator | Power | Input/output rails, derated capacity, efficiency and thermal data |
| Tabletop base | Chassis | Original proxy; printable CAD and mechanical fit open |
| Link bracket | Chassis | Original proxy; printable CAD and mechanical fit open |
| Sensor hat | Chassis | Original proxy; printable CAD and mechanical fit open |

The battery and BEC are separate entries, resolving the suggested list's count
to twelve. The LED uses `display.led_matrix`; it has no joint motion limits.
Capability strings are proposed authoring identifiers, not newly implemented
`seedcore.hal` capability classes or drivers. All runtime bindings are null.
Bus entries describe intended integration surfaces; unknown protocol, pin and
voltage fields prevent using them as a wiring plan.

The [Microduck reference](references/microduck-0.1.0.json) points at the existing
pinned native model package and simulation deployment profile. It is not
assembled from these draft parts. This work does not change its assets,
15 physical/14 policy channel mapping or outstanding policy compatibility gates.

## Units, geometry and consistency

Part and port frames are right handed, Z-up, in meters. A port quaternion is
`[w,x,y,z]`, active local-to-parent, unit length; its local +Z is the outward
mount normal. Inertia is the full symmetric tensor about the declared center of
mass, in the part frame, in kg·m². The validator checks positive definiteness
and principal-moment triangle inequalities. Positions, velocity and torque use
radians, rad/s and N·m. Current uses mA; cost is USD with a declared basis.

The authored GLBs follow glTF's Y-up convention. Conversion from part to mesh
is `(x,y,z) → (x,z,-y)`; the viewer applies the inverse `(x,y,z) → (x,-z,y)`.
Proxy vertex bounds must match the collision box after this conversion.
Their masses and inertias are consistent **simulation assumptions**, not
manufacturer specifications. No supplied CAD or third-party mesh was copied.
The original generated assets use the repository's Apache-2.0 license.

Both ports use `seedcore.proxy_mount_v1`. They illustrate frame orientation and
make no claim of compatibility with M2 grids, servo horns or commercial clips.
GLB visual geometry is not printable CAD or a strength/clearance assessment.

JSON Schema checks structure and bounds. The Python validator additionally
rejects duplicate JSON keys, non-finite/overflow values, duplicate ports/buses,
bad quaternions, inconsistent inertia/ranges/ratings, unproven price quotes,
asset traversal/symlinks, external schema refs and mismatched hashes.
Unknown electrical ratings cannot silently become zero load or compatible
voltage. Passive chassis parts use `not_applicable`, distinct from unknown.

## Authoring and review

1. Copy a draft record, assign a stable part ID/version and document its exact
   scope. Keep nulls for facts that have not been established.
2. Add source/license/drawing and supplier evidence before making claims about
   an exact board, rating, cost or mount. The initial v1 remains unqualified and
   cannot bind a runtime driver; later qualification needs its own reviewed
   manifest and evidence, not a change to an author-supplied boolean.
3. For original box proxies only, rebuild reviewed assets and index hashes:

   ```bash
   .venv/bin/python scripts/robotics/build_component_catalog.py --write-assets
   ```

4. Run the validator/tests and inspect every changed part in the viewer. Review
   dimensions/frames against drawings separately. A proxy render pass does not
   close that drawing/fit gate. Do not regenerate hashes to conceal a failure.
5. Review code/schema/data changes together. Major contract changes need a new
   schema version; never reinterpret a saved assembly or existing digest.

`--write-assets` is an explicit authoring operation; the default command is
read-only and detects stale parts, meshes, schema and reference files. No
remote URLs are fetched by the validator or viewer. No firmware/configuration
binary, signed profile, build ZIP or community publication is created here.

The [source review](references/upstream-sources.json) pins URDF-Studio, mjswan
and the motion-editor snapshots and inspected-file hashes. No code from those
three projects was imported. The [Central World plan](../../docs/development/robotics/central_world_engineering_plan.md)
owns assembly, DRC, simulation, governance and deployment stages.
The [remaining schedule](../../docs/development/robotics/central_world_remaining_delivery_schedule.md)
records the [assembly v2 implementation](assemblies/README.md), CW-A02–CW-A04
offline scope, CW-S01 handoff, CW-S02 fixed-preset runtime and CW-S03 preflight
as delivered locally. The [26 October active queue](../../docs/development/current_next_steps.md)
selects CW-S04 bounded gesture/replay next; full policy execution remains gated.
CW-D01 separately closes exact
physical data for the selected profile. Use the
[acceptance matrix](../../docs/development/robotics/central_world_acceptance_matrix.md)
for handoff evidence. These plans do not add fields or runtime bindings to the
current v1 part records.
