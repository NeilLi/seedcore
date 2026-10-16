# Assembly v2 authoring contract

Status: offline proxy implementation; software verification candidate

`tabletop-starter.sc-assembly.json` is the current five-part reference. The
supported schema is [v2.sc-assembly.schema.json](../schema/v2.sc-assembly.schema.json),
identified by `seedcore.assembly.v2`. It supports one rooted mechanical tree,
rigid mounts and directly actuated revolute joints, and declared electrical
net proposals. It grants no execution authority or hardware qualification.

## Versions and identity

The unaccepted v1 draft remains in Git at `9c5aaf7`, with canonical starter digest
`1a4451a2664ef4368c5f1664b74a17d9b1db2f3b81601448517fef3ebeeaac8c`.
Its schema file is retained as historical material; current validators reject
v1. The exported TypeScript v1 constant identifies that historical version only.
Migration requires explicit output declarations and reviewed mating transforms;
it is not an automatic schema-tag replacement.

The current v2 starter is assembly revision `0.2.0`, with digest
`2550d184c44a064c6ad6a2245a08f430f257c40ca8f3627e73eeb3fedd452acb`.
The digest changed because part pins now use exact catalog bytes, mating poses
were corrected and the v2 profile/output fields were added. The original v1
component schema, twelve part records and catalog index remain unchanged.

Every node resolves its part ID, part version and SHA-256 against the exact
file bytes already pinned by `catalog.json`. Reformatting a part changes its
artifact hash even when its parsed values are unchanged; an existing assembly
must then fail its old pin. Assembly JSON whitespace/property order, by contrast,
is removed by the assembly canonical profile before hashing.

## Canonical bytes and bounds

`seedcore.jcs-safe-integers.v1` uses RFC 8785 string, number and UTF-16 property
ordering, with an additional safe-integral domain: every integral number must
be within `[-9007199254740991, 9007199254740991]`. Numbers are finite binary64;
negative zero serializes as `0`. Invalid Unicode and non-JSON values reject.
Python uses pinned `rfc8785==0.1.4`; JavaScript uses native primitive JSON
serialization and explicitly emits sorted properties, including numeric keys.
This format is separate from existing execution-token/receipt formats.

The serializer rejects more than 262144 UTF-8 bytes, depth above 32 or more than
50000 visited JSON values/keys. The schema further bounds nodes to 256,
mechanical edges to 255, nets to 64, net endpoints to 32 and actuator outputs to
32. Array order is significant. Content-identical revisions reproduce the same
digest; CW-A02 owns revision history and invalidation of prior admission on edits.

## Mechanical connections

All positions use meters, axes use the right-handed part frame, and quaternions
are active `[w,x,y,z]`. Every edge requires a relative transform and an explicit
connection type. Rigid mounts cannot contain a joint; articulated edges require
one. Initial support is fixed mounting plus revolute articulation; prismatic,
continuous and coupled transmissions are not supported.

A port's +Z points outward. V2's `opposed_z_rx_pi` convention fixes the mating
rotation to a half-turn around port X:

```text
T_rest = T_parent_port * Rx(pi) * inverse(T_child_port)
T(q) = Translate(pivot) * Rotate(axis, q - rest_angle_rad)
       * Translate(-pivot) * T_rest
```

`axis`, `pivot_m` and the joint's `frame: parent_part` refer to the parent part.
The authored relative transform is the mated rest pose, where the joint
coordinate equals `rest_angle_rad`. The rest-pose helper does not step dynamics.
Only `seedcore.proxy_mount_v1` is supported by the semantic validator initially;
additional mating standards/twists need reviewed support.

`actuator_outputs` explicitly declares a logical output channel, part port,
rotation axis and pivot with `basis: simulation_proxy`. This is an assembly-owned
simulation assumption, not a manufacturer horn definition or servo bus ID.
The output must belong to the joint's parent actuator, use the parent connection
port and agree with the joint frame. Its pivot must equal that proxy port's
position. Channels are integers 1–32 as an authoring bound, not a hardware channel
rating. Unknown channels, duplicate channel/port declarations, reused channels
and output ports used as housing mounts reject. Requested angle, velocity and
torque limits cannot exceed the part's complete simulation limits. Those values
do not establish hardware limits.

The corrected reference centers are Z = 0, 0.011, 0.036, 0.060 and 0.068 m for
base, bracket, servo, hat and MCU. The bracket's bottom touches the base's top
at 0.006 m; the original overlapping pose is not retained as a passing fixture.

## Electrical proposals

Supported kinds are TTL UART, I2C, PWM, power and ground. Signal kinds must match
the declared interface kind and controller/peripheral role. Power/ground use
`POWER_RAIL` interfaces with source/sink roles and explicit declared pins.
Unknown pins, duplicate endpoints, overlapping cross-net resources and multiple
controllers on a supported signal bus reject. Power and ground may share a
connector interface only with distinct pins. A signal interface cannot become
power merely by changing the net label. Protocol/voltage/address/current and
actual routing qualification remain CW-A04/CW-D01 requirements.

## Validation and reproducible checks

Python `load_assembly_catalog()` preserves verified byte artifacts.
`validate_assembly()` checks schema, topology, artifact references, mechanical
connections, output mappings, limits and electrical references, returning a
separate candidate copy. Explicit `AssemblyCatalog(..., provenance="synthetic_fixture")`
can carry synthetic byte artifacts for tests; it still validates part data/assets
and conveys no trust or qualification.

TypeScript `validateAssemblyStructure()` applies the same generated schema and
catalog-independent topology/output checks, returning a detached copy. Its pass
is not the catalog-dependent semantic result. The schema mirror is generated
and checked by `tools/robotics/generate-assembly-schema.cjs`; do not edit the mirror
by hand. Raw-text importers must reject duplicate JSON keys before these parsed
object APIs; Python's existing `parse_json` does so. CW-A02 owns the browser
text-import/store flow and its atomic state update.

From the repository root, with project Python and TypeScript dependencies:

```bash
node tools/robotics/verify-assembly.cjs
```

The runner checks schema generation, builds contracts before running tests,
runs Python/catalog and Node/shared conformance, and performs live Python/JS
canonical comparisons. It writes source/build hashes and check dispositions to
`artifacts/robotics/cw-a01/verification.json`. CI also runs the Node/build/parity
lane after installing dependencies; the Python suite is covered by its test step.
No ignored preexisting `dist` build is required. The software exit and remaining
scope are recorded in the [acceptance plan](../../../docs/development/robotics/central_world_cw_a01_acceptance_plan.md).
