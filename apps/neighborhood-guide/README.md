# Neighborhood Guide — Blender + Godot local starter

An isolated, presentation-only Godot 4.7 project for the curated loop:

```text
question / mood → tag match → optional detour → walk line → POI story
```

It starts with fictional POIs and primitive geometry so the interaction and
asset pipeline can be validated before any real neighborhood data or content
is introduced. It does not call SeedCore services and cannot authorize a
booking, payment, custody transition, policy decision, or evidence claim.

## Installed local tools

The supported local baseline is:

| Tool | Version | Role |
| --- | --- | --- |
| Godot | 4.7.2 | scene composition, route prototype, desktop smoke test |
| Blender | 5.2.1 LTS | modular source meshes, material baking, GLB export |

Godot is used with the GL Compatibility renderer for fast desktop iteration;
profile the Mobile renderer on the actual target before making mobile or web
claims. Keep Godot and any future OpenXR plugins pinned in this document and
rerun the device gate when they change.

## First run

```bash
cd /Users/ningli/project/seedcore/apps/neighborhood-guide
./tools/check_environment.sh
./tools/validate_project.sh
godot --path . --editor
```

In the editor, open `scenes/Main.tscn` and press **F6** or run the project with
**F5**. Enter a request such as `quiet artisan coffee and fresh air`, then press
**Find a walk**. The yellow line is an advisory preview through one nearby
detour to the best matching fictional POI.

## Blender workflow

1. Open Blender and create `assets/blender/neighborhood_kit.blend`.
2. Set Units to Metric, Unit Scale to 1.0, and model in meters.
3. Snap street, sidewalk, and facade modules to the 2 m grid. Keep origins at
   module bottoms so placement is predictable.
4. Name collision proxies with `-col` (for example `facade_cafe-col`) and keep
   them simple, separate meshes. Do not export them as visible detail.
5. Use a compact material palette/atlas. Bake AO or soft directional light only
   when the target profile needs it; preserve the unbaked source in `.blend`.
6. Export a reviewed selection as `assets/models/<kit-or-landmark>.glb` using
   the script below or Blender's glTF exporter with embedded textures.

From Blender’s **Scripting** workspace, run:

```python
exec(open("/Users/ningli/project/seedcore/apps/neighborhood-guide/tools/export_selected_glb.py").read())
```

The exporter writes `assets/models/neighborhood_selection.glb`. Rename it to a
meaningful reviewed asset name before committing. Import `.glb` files into
`scenes/` as small reusable instances; do not use a giant single city scene.

## Project shape

```text
assets/blender/     Blender source files and notes
assets/models/      reviewed GLB exports
data/               future POI/catalog resources
scenes/             composed Godot scenes
scripts/            route, POI, and presentation behavior
tools/              deterministic local checks and Blender export helper
```

`NavigationRegion3D` is present in the starter scene as the navigation boundary.
After sidewalk geometry exists, assign/bake a pedestrian navmesh in Godot with
approximately a 0.35 m agent radius and 20° maximum slope. The starter route
renderer intentionally uses an explicit advisory waypoint sequence until that
navmesh is baked.

## Asset and content boundary

All models, generated geometry, story copy, routes, audio, and camera output
are presentation artifacts. For real POIs, use only reviewed public-safe
projections and attach source/consent/freshness in the canonical discovery
service. This project must consume a narrow read-only projection if it later
displays verified status; it must never receive an `ExecutionToken` or use
scene state as authority or evidence.
