# Robot canvas and authoring store

`AssemblyStore` owns immutable accepted v2 revisions, selection, bounded undo/redo
and generation-fenced asynchronous loads. `prepareProxyScene` uses the local
catalog-aware authoring service and verifies exact part/mesh bytes. `RobotCanvas`
is a replaceable Three.js rest-pose adapter; it does not mutate the store.

No module grants execution authority. The current UI exposes build-name edits;
magnetic placement, DRC, dynamics and hardware interfaces are later packages.
See the [CW-A02 record](../../../docs/development/robotics/central_world_cw_a02_authoring.md).
