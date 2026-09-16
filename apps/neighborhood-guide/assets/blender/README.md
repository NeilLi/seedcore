# Blender source assets

Keep editable `.blend` source files here. The initial kit should contain:

- 2 m / 4 m sidewalk and curb segments;
- straight street, T-junction, crossing, pedestrian alley, and pocket-park
  modules;
- lamp, planter, seating, signboard, awning, and tree props; and
- generic storefront and upper-floor facade modules plus one landmark.

Use metric units, apply transforms before export, and name collision meshes
with `-col`. Export only reviewed deliverables to `../models/` as GLB; never
replace the source Blender file with the export.

## Main navigation entrance

`neighborhood_entrance.blend` is the editable source for the app's 2D main
entrance: modeled architecture, four destination displays, canal, bridge,
robot guide, vegetation, studio lights, and an orthographic camera. Collections
are numbered by scene role. `Navigation_explore`, `Navigation_textile`,
`Navigation_wood`, and `Navigation_guide` are presentation-only marker anchors.

Render saved edits with `../../tools/render_entrance_blender.py` via Blender's
`--python` option. Rebuild the source with `../../tools/build_entrance.py` only
when you intend to replace manual edits. This entrance exports a PNG and Godot
marker layout, not a GLB, because the app uses it as a 2D navigation surface.
