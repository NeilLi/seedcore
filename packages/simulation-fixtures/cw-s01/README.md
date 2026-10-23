# CW-S01 offline simulation reference

`reference.json` pins a separate two-joint serial assembly and three synthetic
component documents. Provenance is `synthetic_fixture`, physical acceptance is
false, and execution authority is none. Ideal power bookkeeping and $1 estimates
are mathematical test inputs, not supplier ratings, quotations or CW-D01 evidence.
The source is derived from the aligned CW-S01 conformance fixture; existing
owned box-proxy meshes are reused by their exact digests.

Mini Studio loads this profile explicitly. Every edit still passes the existing
assembly validator, full DRC and restricted compiler. Only proxy physical fit is
deferred by the existing simulation-readiness policy. Mixing physical and
synthetic catalog parts is rejected. The physical starter and catalog stay intact.

`node tools/robotics/verify-mjcf.cjs` exports both actuator modes for independent
native MuJoCo 3.15.0 checks. `node tools/robotics/verify-authoring.cjs --browser`
compares browser exports to fresh compiler bytes and runs native checks on the
actual downloaded bundles. CW-S02 runtime stepping remains a separate gate.
