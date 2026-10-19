# Robot canvas and authoring store

`AssemblyStore` owns immutable accepted v2 revisions, selection, bounded undo/redo
and generation-fenced asynchronous loads. `prepareProxyScene` uses the local
catalog-aware authoring service and verifies exact part/mesh bytes. `RobotCanvas`
is a replaceable Three.js rest-pose adapter; it does not mutate the store.

No module grants execution authority. `snapping.ts` supplies pure 15 mm candidate discovery, opposed-normal mating,
proposal checks and an epoch-bound commit helper. The UI exposes build-name
edits, proxy additions and non-root subtree placement. DRC, dynamics and
hardware interfaces remain later packages.
See the [CW-A02 record](../../../docs/development/robotics/central_world_cw_a02_authoring.md).

The [CW-A03 record](../../../docs/development/robotics/central_world_cw_a03_snapping.md)
defines supported ports, angular capture, ghost isolation and drop evidence.
