# CW-A01: acceptance closure and CW-A02 handoff

Date: 2026-10-16
Status: Implemented v2; software exit checks passed
Owner roles: Integration + Studio; verification reviewer for the exit packet

## Task and baseline

Close the eight review findings in the assembly contract committed as
`9c5aaf7`, then hand an accepted authoring contract to CW-A02's immutable store
and import/export flow. Start with **canonical digest and catalog pin parity**.
This is a subplan of CW-A01, not a new milestone or a second calendar. The
[remaining schedule](central_world_remaining_delivery_schedule.md) retains the
work-package order and the [acceptance matrix](central_world_acceptance_matrix.md)
owns CW-ASM-01.

The draft includes a schema, Python validator, TypeScript structural validator,
starter assembly and tests. Its 56 combined assembly/catalog Python tests,
four Node tests and contracts build passed during review. Additional targeted
checks reproduced eight gaps below; those passing baseline tests do not close
CW-A01. The v2 implementation now addresses those findings and passes the
software exit below. The initial plan and historical baseline are retained here
to explain the repair order.

Use the existing draft catalog and explicit simulation/proxy assumptions.
Hardware qualification and missing Microduck training references do not block
this authoring work. The resulting contract grants no execution authority.

## Ordered repair batches

Complete and review each batch before changing the next dependent contract.

| Batch | Review findings / required work | Exit artifact |
| --- | --- | --- |
| A — Digests and pins; start here | R1: replace the Python/JS serialization mismatch with one declared cross-language canonical profile. R2: resolve part references using exact catalog file-byte hashes, not hashes of reserialized objects. | Independent expected-byte/hash vectors, catalog-pin success and changed-byte rejection report; regenerated draft fixture with old/new digest provenance |
| B — Schema and graph conformance | R3: add root traversal and cycle/disconnection rejection to browser structural validation. R4: encode rigid/articulated variants in JSON Schema and align required-field/type/bounds validation across consumers. | Shared valid/invalid fixtures with expected structural outcomes in Python and TypeScript; schema-only conditional tests and atomic-import rejection evidence |
| C — Connection semantics | R5: specify mating/rest frames and correct the overlapping golden pose. R6: declare actuator output/channel ownership and reject invalid or duplicate mappings. R7: check angular, velocity and torque bounds against the selected proxy/profile. R8: define compatibility for every supported electrical net kind. | Numeric mating/pose fixtures, explicit proxy output binding, limit-boundary tests and electrical compatibility matrix; unsupported configurations reject explicitly |
| D — Acceptance and handoff | Wire the shared fixtures into a reproducible verification command, document supported scope/version handling and reconcile queue/status documents. | Retained CW-ASM-01 report, reviewed contract/fixture digests and CW-A02 input checklist |

### Batch A: exact acceptance requirements

Keep assembly canonicalization distinct from raw component artifact hashing.
The assembly serializer must reproduce independently frozen canonical bytes in
Python and JavaScript, including non-ASCII strings, small/exponent-form numbers,
negative zero and numeric rounding boundaries. Define rejection for non-finite
values, unsupported integers and invalid Unicode rather than allowing parser
differences. Reference the [RFC 8785 profile](https://www.rfc-editor.org/rfc/rfc8785)
if adopting JCS; the current integer-float normalization is insufficient.

A node's part ID, version and SHA-256 must resolve to the same entry and exact
bytes verified by the catalog loader. A parsed part dictionary alone is not
evidence of an original file digest. Preserve an explicit provenance path for
synthetic test catalogs. Reject a changed component artifact under its old pin;
never substitute a newly computed digest to make an imported candidate pass.

Preserve `9c5aaf7` as the historical draft reference. Record why fixture digests
change; do not silently rewrite old expected evidence. Review schema/version
and canonical-profile changes before declaring the corrected contract stable.
Keep existing token/receipt serialization contracts separate from this repair.

### Batches B and C: required counterexamples

- A disconnected two-node cycle with valid edge count and unique parents must
  fail in both structural validators. Missing identity/node fields, malformed
  hashes, null nets and duplicate stable IDs must also fail.
- Schema-only validation must reject a rigid mount containing a joint and an
  articulated edge missing one. Restrict the initial joint kinds to those with
  defined units and supported semantics; radian limits do not define a prismatic
  joint. Catalog-dependent semantic checks remain explicit, separate checks.
- Define the mating rotation and axis/pivot/rest-frame conventions. Derive or
  require an unambiguous transform; omission must not silently mean identity
  when the referenced ports imply another pose. Test rotated/translated parents,
  opposing port normals, known contact poses and displaced connected ports.
  The corrected starter must not place its bracket inside the base.
- An actuator binding must identify a declared output/channel and its driven
  joint. Reject negative/unknown channels and one channel assigned to multiple
  joints without a supported transmission. If the component contract needs an
  output extension, create a reviewed version/proxy declaration and fixtures;
  do not invent manufacturer horn geometry in the frozen draft catalog.
- Reject requested bounds above the selected actuator's declared angle,
  velocity and torque limits. Keep units and unknown-value behavior explicit;
  proxy simulation limits do not become qualified hardware limits.
- Define an explicit mapping for all supported net kinds, including power and
  ground, with declared endpoint/pin references. UART interfaces cannot pass as
  a power net by changing its label. Unsupported bus/net combinations reject;
  full power/pinout routing and physical readiness remain CW-A04/CW-D01 work.

## Verification and completion

Run the assembly and component-registry Python suites, build/typecheck the
contracts package, then run the Node conformance suite against that build.
New shared fixtures must test real cross-language behavior and the reproduced
failures, not just compare two outputs generated by the same implementation.
Add an entry point that builds the required contracts before running Node tests
so clean checkouts do not depend on an ignored `dist` directory from a prior run.

Verify failed imports leave the candidate and the retained accepted revision
unchanged. CW-A01 can establish pure, nonmutating validation; CW-A02 implements
the persistent immutable store, undo/redo and stale asynchronous-result handling.
Record skipped checks as open, not passed. Run additional trust-runtime gates
only if implementation extends into those surfaces.

Mark CW-A01 accepted only when R1–R8 have retained regression evidence, the
supported schema/joint/net subset is documented, Python/JS digest and structural
fixtures agree, exact part-byte references resolve and the corrected starter's
numeric geometry passes. Record the source revision, fixture/build hashes and
remaining exclusions in the exit packet.

## Following task: CW-A02

After that exit, begin the Mini Studio authoring shell and immutable assembly
store: starter import/export, selection, revision history, undo/redo and rejection
of stale/failed asset loads. Review canvas dependencies as part of CW-A02.
Magnetic snapping, DRC routing and general MuJoCo/ONNX runtime integration retain
their later work packages. No hardware or model export is needed for the handoff.

## Implementation result and exit record

The current candidate uses `seedcore.assembly.v2`, documented in the
[assembly contract](../../../packages/component-registry/assemblies/README.md).
It rejects the historical v1 draft, uses exact catalog-byte pins and declares
proxy actuator outputs in the assembly without changing the frozen component
catalog. The new starter revision/digest and the prior v1 digest are recorded
there. No automatic reinterpretation of saved v1 data is provided.

| Finding | Implemented regression evidence |
| --- | --- |
| R1 | Independently frozen canonical vectors for Unicode, numeric notation, UTF-16/numeric key ordering, escaping and safe integers; live Python/JS bytes agree for every valid shared assembly |
| R2 | Starter pins equal catalog file-byte hashes; whitespace-only artifact edits invalidate old catalog/assembly references; parsed dictionaries cannot substitute for byte artifacts |
| R3 | Shared disconnected-cycle, root, edge-count, multi-parent, duplicate-ID and occupied-port cases reject in Python and TypeScript |
| R4 | Both consumers use the same schema; missing fields, malformed hashes/null nets and rigid/articulated variant violations reject; unsupported joint kinds reject |
| R5 | Required mating/rest transforms, opposing normals, transformed-parent numeric fixtures and corrected independent starter heights; displaced ports reject |
| R6 | Explicit proxy outputs, direct parent ownership, frame agreement, channel bounds, duplicate assignments and housing/output separation checks |
| R7 | Complete simulation bounds required; excessive angle, velocity and torque reject; hardware qualification remains open |
| R8 | Explicit signal versus POWER_RAIL kind/role mappings, declared pins, endpoint uniqueness, resource reuse and controller-count tests |

On 16 October the build-from-source runner passed **117 Python tests**
(assembly plus component registry) and **71 Node tests**, with zero skips.
It was exercised with no preexisting contracts `dist` directory, using Python
3.12.3 and Node v25.9.0. All workspace TypeScript typechecks and the existing
25 TypeScript tests passed. Ruff and whitespace checks passed. Remote CI was
not run by this local acceptance; the new workflow step targets its Node 22 lane.
That test job now uses Python 3.12, matching the repository's existing minimum
and avoiding an incompatible Python 3.11 package-install step.

Reproduce with `node tools/robotics/verify-assembly.cjs`. The ignored local
`artifacts/robotics/cw-a01/verification.json` records check counts, runtime
versions, source/build/fixture hashes, base Git revision and working-tree state.
The report deliberately labels the scope `offline_assembly_v2_authoring` and
`physical_acceptance: false`. The reference is `9c5aaf7` plus the recorded
candidate hashes, not a claim that the old commit contains these repairs.

The software handoff is ready for CW-A02: consume v2 only, distinguish structural
checks from catalog-dependent validation, reject duplicate keys in browser raw
JSON import, and add the immutable store/undo/stale-load tests. The CW-A02 store,
canvas/browser UX, DRC readiness, simulation dynamics, live authority and physical
acceptance have not been delivered by this contract milestone.

## 19 October handoff follow-through

The [CW-A02 offline authoring slice](central_world_cw_a02_authoring.md) now
consumes this v2 baseline with raw-text duplicate-key rejection, immutable
history and local browser/state evidence. The original starter content digest
and component bytes are unchanged. Later DRC, dynamics and physical gates remain open.
