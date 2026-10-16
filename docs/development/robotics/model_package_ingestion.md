# Model package ingestion v1

Status: implemented offline MJCF/URDF ingestion and pinned Microduck reference.

`seedcore.robotics.model_package` imports versioned robot bodies into the native
MuJoCo development workbench. Loading and simulation remain under
`OFFLINE_MUJOCO_NO_ACTUATION`; the package is data, not execution authority.

## Central World Component-To-Model Boundary

The [component registry](../../../packages/component-registry/README.md) validates
authoring parts and GLB proxies; it is a different contract from this compiled
model package. Its schema pass does not define joints or create a MuJoCo model.
[CW-A01/CW-S01](central_world_remaining_delivery_schedule.md) must declare
articulation, compile only the supported subset and compare native FK, mass,
joint/actuator ordering and limits before CW-S02 browser use. A visual port
normal or GLB URI cannot substitute for an explicit joint or qualified asset
conversion. Preserve source rights and content identity through that handoff.

Keep the existing Microduck package unchanged unless separately versioned and
reviewed. An edited body needs new model/policy compatibility evidence; neither
component provenance nor native compilation establishes trained-policy transfer.
The [acceptance matrix](central_world_acceptance_matrix.md) defines planned
SIM/POL checks without changing this implemented ingestion schema.

## Contract and identity

The [JSON schema](../../../packages/models/model-package.schema.json) is generated
from [the Pydantic contract](../../../src/seedcore/robotics/model_package/contracts.py).
Unknown fields, nonfinite values, mutable revision labels, duplicate paths and
invalid mappings fail validation.

| Manifest field | Meaning |
| --- | --- |
| `schema_version` | Exactly `seedcore.model-package.v1` |
| `package_id`, `version` | Stable robot identifier and version of the packaged model |
| `format`, `entrypoint` | MJCF or URDF; canonical path relative to the manifest directory |
| `engine`, `engine_version` | MuJoCo 3.15.0, checked at runtime |
| `source` | HTTPS repository URL, full Git object revision, original model path, license identifier, optional CAD URL/revision and exporter |
| `files` | Every declared model/include, mesh, texture, heightfield, skin, license and provenance file with SHA-256 and byte length |
| `parity` | Compiled mass/tolerance, dimensions, timestep, ordered body tree, joint types/limits and actuator-to-joint mapping, gears and control/force ranges |

Joint ranges use radians for hinge/ball joints and metres for slide joints. Null
means unlimited; free joints have null ranges. Actuator control ranges use the
source actuator's native control units. A position actuator's control is not
torque. V1 supports direct joint transmissions only; it does not infer motor
calibration or qualify actuator dynamics.

Body, joint and actuator arrays describe **compiled order**, including all joints
(even free/passive ones). Body arrays exclude world, and must be parent-first.
This pins the state-vector interpretation and catches compiler fusion/reordering
as well as missing or remapped joints. The compiled body tree must match exactly.

`manifest_sha256` hashes the original manifest bytes. A caller can supply
`expected_manifest_sha256` from an independent reviewed source. `package_sha256`
hashes canonical manifest JSON with sorted file inventory, including file hashes
and parity/source metadata. Whitespace and inventory ordering do not affect it.
Hashes detect changes against a trusted pin; a self-supplied manifest alone does
not authenticate its publisher or establish physical fidelity.

## Loader and workbench API

```python
from seedcore.robotics.model_package import verify_model_package, load_model_package
from seedcore.robotics.mujoco_workbench.runtime import require_engine

path = "packages/models/microduck/0.1.0/manifest.json"
verified = verify_model_package(path)  # works without importing MuJoCo
loaded = load_model_package(path, expected_manifest_sha256=verified.manifest_sha256)
print(loaded.report)

# Each load creates its own model; the caller owns fresh simulation state.
mj = require_engine()
data = mj.MjData(loaded.model)
mj.mj_forward(loaded.model, data)
```

For a trusted publisher check, supply a previously reviewed digest rather than
deriving it from the same manifest at load time as this API example does.
`load_model_package` returns a fresh mutable native `MjModel`, its immutable
verified input snapshot and a JSON-compatible inspection report. Mutating the
native model afterward invalidates the parity claim for that modified model.
`ModelPackageError` covers invalid manifests, integrity, unsupported XML, native
compilation and parity failures. Missing or mismatched MuJoCo raises the existing
workbench `RuntimeError` with install/version guidance.

```bash
PYTHONPATH=src .venv/bin/python scripts/robotics/mujoco_workbench.py inspect-package \
  --manifest packages/models/microduck/0.1.0/manifest.json \
  --output /tmp/microduck-inspection.json
.venv/bin/python -m pytest -q tests/test_model_package.py tests/test_mujoco_workbench.py
```

`inspect_model_package` is also available in the workbench runtime. Existing
primitive `RobotSpec` experiments and agent tools retain their authoring subset.
Package-based controller recipes need a separate actuator-aware contract before
they can reuse the PD comparison loop, which currently assumes torque motors.

## Integrity and compilation boundary

1. Validate the manifest, optional caller pin and bounded inventory.
2. Read each regular, nonsymlink file into a byte snapshot and compare size/hash.
3. Parse UTF-8 XML without DTD/entities. Expand declared MJCF includes; duplicate
   or cyclic includes fail. Includes resolve relative to the main XML directory,
   following [MuJoCo's include rules](https://mujoco.readthedocs.io/en/latest/XMLreference.html#include).
4. Resolve every resource against the verified inventory and role. Preserve
   implicit mesh names and rewrite resource references to unique flat VFS keys.
   Compile using only those verified bytes, so later source-file edits do not
   change the compiled inputs and native disk fallback has no missing dependency
   to resolve.
5. Compare native dimensions, mass, timestep, tree, joint limits, actuator
   transmissions/gears/ranges. Run `mj_forward` and reject warnings or nonfinite
   initial kinematic/dynamic state.

Supported resources are MJCF STL/OBJ meshes and other MuJoCo mesh formats,
textures (including cubemap file attributes), heightfields and skins; URDF mesh
`filename` references use the same integrity boundary. Paths are canonical and
relative; absolute paths, traversal, backslashes, URIs and symlinks fail.
Compiler `meshdir`, `texturedir`, `assetdir` and `strippath` are resolved before
resource references are normalized for the VFS. They must use supported paths.

Plugins/extensions, attached model assets and procedural `composite`, `flexcomp`
or `replicate` elements are rejected. These require another reviewed contract.
URDF uses MuJoCo's native subset, including its compiler defaults; ROS package
resolution, xacro processing and general URDF transmission conversion are not
provided. Native URDF parsing can ignore unsupported URDF metadata; parity pins
the compiled result, not the semantics of every source tag. Authors should set
`fusestatic`, `discardvisual` and `strippath` explicitly when those choices matter.

Limits: at most 512 files, 64 MiB per file, 128 MiB total; manifest and each XML
at most 2 MiB; at most 10,000 XML elements and 32 include levels; at most 256
bodies, 128 joints/actuators and 256 position/velocity dimensions; timestep
0.5–5 ms. These input limits do not bound native compiler CPU/memory allocations
or create an OS sandbox. Packages still require source review before use.

## Microduck reference and validation scope

The [Microduck 0.1.0 package](../../../packages/models/microduck/0.1.0/README.md)
preserves the full upstream body MJCF and 38 STL meshes at Git revision
`cb70b792312d559a4da09064d92009079671815f` with its Apache-2.0 license and
Onshape export configuration. Its source inertial sum is 0.73724318 kg; the
manifest pins that value rather than altering the model to match a rough 800 g
hardware description. Fourteen hinge joints plus the floating base produce
`nq=21`, `nv=20`, `nu=14`.

Tests check manifest/schema agreement, an independent baseline digest,
tampering/missing files/symlinks, unsafe XML and dependency paths, nested includes,
distinct VFS names, dimensions/mass/tree/joint/actuator mismatch rejection,
native URDF import, 32 deterministic random Microduck poses with exact kinematic
replay, and 25 finite dynamics steps without warnings. These establish package
integrity and local numerical behavior; they do not establish balance,
hardware mass, sim-to-real fidelity, SIM-2 qualification or token enforcement.
