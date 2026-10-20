# Robot canvas and authoring store

`AssemblyStore` owns immutable accepted v2 revisions, selection, bounded undo/redo
and generation-fenced asynchronous loads on the local development computer.
`prepareProxyScene` uses the local
catalog-aware authoring service and verifies exact part/mesh bytes. `RobotCanvas`
is a replaceable Three.js rest-pose adapter; it does not mutate the store.

Each accepted revision is deep-frozen. History is capped at 32 entries / 2 MiB;
accepted assembly changes advance `authorityEpoch` and clear admission. These
checks also apply to imported LLM drafts. Generation tickets reject stale
async loads; this is offline authoring state, not a live robot controller.

No module grants execution authority. `snapping.ts` supplies pure 15 mm candidate discovery, opposed-normal mating,
proposal checks and an epoch-bound commit helper. The UI exposes build-name
edits, proxy additions and non-root subtree placement. Pure DRC/BOM lives in [`@seedcore/drc-solver`](../drc-solver/README.md); dynamics (`CW-S01..S04`) and
hardware interfaces remain separate packages.
See the [CW-A02 record](../../../docs/development/robotics/central_world_cw_a02_authoring.md).

The [CW-A03 record](../../../docs/development/robotics/central_world_cw_a03_snapping.md)
defines supported ports, angular capture, ghost isolation and drop evidence.
