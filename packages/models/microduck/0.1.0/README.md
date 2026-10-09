# Microduck 0.1.0 reference package

The MJCF, 38 STL meshes, export configuration and Apache-2.0 license are copied
byte-for-byte from `pollen-robotics/microduck_rl` commit
`cb70b792312d559a4da09064d92009079671815f`. The entrypoint is the upstream
`src/mjlab_microduck/robot/microduck/robot_walk.xml`; meshes come from its `assets/`
directory. `source/config_mjcf_walk.json` preserves the upstream export recipe.
No user-modified checkout files are used. SeedCore adds the manifest and this README.

Pinned source:
https://github.com/pollen-robotics/microduck_rl/tree/cb70b792312d559a4da09064d92009079671815f/src/mjlab_microduck/robot/microduck

The package retains all visual meshes, collision geometries, inertias, joint
ranges, sensors and upstream position actuators. There are 14 hinge joints and
one free base joint: `nq=21`, `nv=20`, `nu=14`, `nbody=16` including world.
The summed source inertial mass is **0.73724318 kg**, and the compiled mass must
match within 1 mg (`1e-6 kg`). This is the source
variant's modeled mass, not a measured hardware mass or a forced 800 g target.

The source Onshape URL identifies a workspace, not an immutable CAD version.
`cad_revision` is null and the exporter version is unspecified; the exported
MJCF/meshes and Git revision are pinned. No CAD fidelity certification is claimed.

This is a body model without a floor/scene. Its position actuators are preserved;
the primitive workbench torque controller must not be applied to it directly.
BAM motor dynamics, closed-loop balance, studio replay, token gating and SIM-2
qualification remain subsequent work.

To reproduce the package inventory from an upstream Git checkout, use
`git show cb70b792312d559a4da09064d92009079671815f:<upstream-path>` for each
manifest file. For `source/config_mjcf_walk.json`, the upstream path is
`src/mjlab_microduck/robot/microduck/config_mjcf_walk.json`; `LICENSE` is at the
repository root. Every other path is relative to the source model directory.
Compare SHA-256 and byte lengths against `manifest.json` before accepting a copy.
