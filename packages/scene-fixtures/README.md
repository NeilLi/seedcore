# Synthetic static scene fixtures

`mini-workbench/` contains original, generated visual data: one coarse mesh,
four detail meshes, an explicit OGC 3D Tiles 1.1 REPLACE hierarchy and a
`seedcore.static-scene.v1` byte-pin manifest. It is a small workbench illustration,
not a supplier CAD model or a collision environment. The five GLBs contain
3,168 source triangles including both levels; the root has 48 and each detail
tile has 780. Assets use `KHR_draco_mesh_compression`, with no textures, external
buffers, animation, scripts, skins, mass, inertia or actuator metadata.

All geometry is authored by SeedCore's
[`generate-static-scene.cjs`](../../tools/robotics/generate-static-scene.cjs)
under the repository's Apache-2.0 license. No Google, NASA scene data, third-party
CAD, scans or imagery is included. NASA's renderer and the Draco codec retain
their own dependency notices. glTF vertices/normals are Y-up; 3D Tiles bounds
and the studio are Z-up. The renderer performs the single Y→Z conversion.
The manifest's large origin is synthetic and has no geodetic meaning.

`decoder-runtime.json` separately freezes the two browser decoder files from
Three 0.181.1. A build rejects changed installed bytes, rather than silently
creating a new trusted decoder pin. Updating those pins is an explicit runtime
review, independent of regenerating scene geometry.

Regenerate or check exact bytes with the locked Node dependencies installed:

```bash
node tools/robotics/generate-static-scene.cjs
node tools/robotics/generate-static-scene.cjs --check
node tools/robotics/verify-static-scene.cjs --browser
```

Changing generator output changes the manifest pins and requires rebuilding the
studio. No fixture file grants physical acceptance or execution authority. See
the [streaming record](../../docs/development/robotics/static_scene_streaming.md)
for scope, limits, runtime failure behavior and remaining ingestion work.
