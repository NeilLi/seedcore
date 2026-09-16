# SeedCore Digital City — initial spatial application

The default scene opens into an **illustrated neighborhood entrance**, using
an original local Blender render with four clickable destinations. Explore
Foundry Lane, meet the textile makers, discover the wood workshop, or ask the
local guide. Each entrance leads into **Foundry Lane**, a fictional 3D district.
This is a local application scaffold for the journey/discovery layer above
SeedCore: inspect places, ask for a stop, preview a pedestrian route, and follow
the visitor through the neighborhood.

## Run

```bash
cd /Users/ningli/project/seedcore/apps/neighborhood-guide
godot --path .
```

For editing: `godot --path . --editor`, open `scenes/Landing.tscn`, and press F5. Open `scenes/City.tscn`
and press F6 to preview the district directly.
Tested with Godot **4.7.2**, GL Compatibility, and Blender **5.2.1 LTS**
on Apple Silicon. Launches in a 1280 × 800 landscape window.

## Try the application

1. Choose a scene hotspot or destination card on the entrance. **Home** returns
   here from the district. Tab and Enter/Space also activate entrance buttons.
2. Click a storefront or a place button to open its description.
3. Search for `coffee`, `handmade textile`, `wood carving`, or `fresh air`.
4. Turn **Garden detour** on or off before planning a route.
5. Click **Find a walk** or **Walk here**, then **Start walk**.
6. Watch the visitor follow sidewalks and a marked crossing. The place card
   changes at each stop. Pause/resume, replay, or reset the walk.

Right-drag orbits, middle-drag pans, and the wheel zooms. **Reset view** restores
the district framing. Unknown/empty searches explain that no match exists and
clear any previous route. Replanning begins at the marked south-side entrance;
live rerouting from an arbitrary visitor position is not implemented.

## What's implemented

- Illustrated home navigation, native keyboard-focusable buttons, and a layout
  that fits the supported landscape window sizes without cropping. The image
  is a 2D orthographic render of editable Blender geometry; the destination
  district is interactive 3D.
- Editable Blender district and imported GLB: café, textile studio, wood
  workshop, pocket garden, furniture, lamps, trees, sidewalks, and crossings.
- Native Godot 3D camera, selectable buildings, and reusable `POIResource`
  data on `POIAnchor3D` entrance markers.
- Deterministic interest-tag matching and optional garden stop.
- AStar3D pedestrian graph, visible route, metric distance, estimated walking
  time, visitor movement, and arrival interaction.
- Native Godot controls for search, inspection, and walking state.

## Architecture and extension points

| Surface | File / role |
| --- | --- |
| Entrance art source | `assets/blender/neighborhood_entrance.blend`: editable miniature town, camera, lights, and navigation anchors |
| Main entrance | `scenes/Landing.tscn` and `scripts/landing_screen.gd`: artwork, hotspots, and destination cards |
| Application scene | `scenes/City.tscn`: imported district, camera, editable POI resources and entrance markers |
| Application state | `scripts/city.gd`: selection, matching, itinerary, visitor, and interface |
| Pedestrian network | `scripts/city_routes.gd`: explicit sidewalk graph and two crossings |
| View | `scripts/city_camera.gd`: orbit, pan, zoom, and reset |
| Art source | `assets/blender/foundry_lane.blend`: editable objects organized by collection |
| Engine asset | `assets/environment/foundry_lane.glb`: portable export; no Blender needed to run |
| Rebuild recipe | `tools/build_district.py`: deterministic metric fixture generation |

Road modules are 4 × 4 m with their top at ground level; sidewalks are 2 × 4 m
with a 0.15 m curb. Storefront footprints are 4 × 4 m. The textile building adds
a 3 m upper floor to a 3.5 m ground floor. Source origins are at bottom-center.
All coordinates are meters; the exporter converts Blender Z-up to Godot Y-up.

The pedestrian network follows sidewalk centerlines and crosses the road only
at X = ±12 m. It rejects positions off that network. It is an explicit fixture
graph, **not a baked NavigationMesh or a real-world routing service**. Replace
or extend it as the district grows. See Godot's official
[3D navigation overview](https://docs.godotengine.org/en/stable/tutorials/navigation/navigation_introduction_3d.html).

`Landing.tscn` is the application entry point. The primitive `Main.tscn` remains
a design reference. Navigation passes a one-time local destination to the city;
workshop entries preview a route and the guide entry focuses the tag-based
search. No walk starts automatically.

## Blender entrance: editing and rendering

The entrance is authored in local Blender, with separate collections for the
island/canal, architecture, map terrace, textile kiosk, craft vitrine, robot guide,
plants, and render studio. Materials, mesh geometry, lighting, and an orthographic
camera are editable. The original supplied image remains a reference only.

Open `assets/blender/neighborhood_entrance.blend` in Blender. Save your edits,
then refresh the app image without rebuilding the models:

```bash
blender --background assets/blender/neighborhood_entrance.blend --python tools/render_entrance_blender.py
godot --headless --path . --editor --quit
```

This renders `assets/illustrations/entrance_render.png` with transparency and
exports `scripts/entrance_layout.gd`. Four `Navigation_*` empties project through
the camera to place the app's clickable markers. Move these anchors with their
corresponding displays when changing the composition. Keep the render at 3:2.
The PNG and generated layout are tracked; Blender is not required to run the app.

To rebuild the entire original scene from its deterministic recipe:

```bash
blender --background --python tools/build_entrance.py -- --replace-generated
```

**Save hand edits under a different filename before rebuilding.** The recipe
replaces the generated `.blend`, image, and marker layout. It refuses to replace
existing files without `--replace-generated`. Rendering an existing source with
`render_entrance_blender.py` does not overwrite the `.blend` file.

## Blender editing and asset rebuild

Open `assets/blender/foundry_lane.blend` to edit individual buildings, furniture,
and street modules. Export the environment as GLB with Y-up, modifiers applied,
and animations/cameras/lights disabled. Lighting is authored in Godot.
The source folder has `.gdignore`, so the engine imports only the GLB.

The generated model uses 12 shared solid-color materials; it does not yet use
the planned texture atlas or baked lightmaps. The entire small fixture is one
GLB for this first scaffold. Individual asset exports can replace it later.

Rebuild from the recipe:

```bash
blender --background --python tools/build_district.py -- --replace-generated
godot --headless --path . --editor --quit
```

**Copy any hand-edited source and export before rebuilding.** The command replaces
both generated files. Without `--replace-generated` the recipe refuses to
overwrite them. For meshes, `-col` adds a static concave collision with the
visible mesh; `-colonly` omits its visible mesh, and `-convcol` requests convex
collision. These are importer behaviors, not evidence or execution permissions.

## Checks and visual review

```bash
./tools/check_environment.sh
./tools/validate_project.sh
godot --path . --resolution 1440x900 --script res://tools/render_entrance.gd -- /tmp/seedcore-entrance.png
godot --path . --resolution 1440x900 --script res://tools/render_city.gd -- /tmp/seedcore-digital-city.png
```

Validation imports assets, loads the default scene, and checks matching,
unknown requests, constrained routing, off-network rejection, optional detours,
start/pause/arrival/reset, place buttons, and building selection volumes. It also
checks all four entrance destinations, keyboard activation, guide focus, and
round-trip Home navigation.
The render command saves a real GPU-rendered view of the application itself.

## SeedCore integration boundary

This is the initial **application layer scaffold**, using fictional local data.
It does not yet connect to the sovereign-city REST discovery service, real
businesses, live opening hours, AI-generated answers, booking, or commerce.

The next integration point is a narrow read-only adapter that supplies reviewed
public POI projections with stable IDs, source references, consent, and freshness.
Godot selection, routes, and local scene state remain presentation and discovery.
Consequential actions stay in SeedCore's accountable-agent → PDP →
ExecutionToken → actuator → evidence/verifier workflow.
