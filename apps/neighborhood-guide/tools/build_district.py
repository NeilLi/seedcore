"""Build the fictional Foundry Lane fixture in Blender, then export to Godot.

Run: blender --background --python tools/build_district.py
One unit is one meter. Helpers accept Godot XYZ (Y up); Blender stores Z up.
Rebuilding refuses to replace existing source assets unless -- --replace-generated
is passed. Edit a copy of the blend if you want to retain hand-authored changes.
"""
from pathlib import Path
import sys
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/blender/foundry_lane.blend"
EXPORT = ROOT / "assets/environment/foundry_lane.glb"
if any(p.exists() for p in (SOURCE, EXPORT)) and "--replace-generated" not in sys.argv:
    raise RuntimeError("Assets already exist; copy any manual edits first, then use -- --replace-generated")
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 1.0
scene.unit_settings.length_unit = "METERS"
palette = {}
for name, color in {
    "ivory": (0.88, 0.82, 0.66), "coral": (0.76, 0.30, 0.20),
    "sage": (0.38, 0.57, 0.46), "pine": (0.09, 0.25, 0.20),
    "glass": (0.12, 0.28, 0.28), "gold": (0.93, 0.62, 0.22),
    "pavement": (0.72, 0.71, 0.61), "road": (0.25, 0.34, 0.32),
    "wood": (0.40, 0.24, 0.12), "white": (0.96, 0.93, 0.81),
    "grass": (0.47, 0.61, 0.39), "leaf": (0.22, 0.44, 0.28),
}.items():
    mat = bpy.data.materials.new(name)
    # Palette swatches are sRGB; Blender shader factors are scene-linear.
    linear = tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in color)
    mat.diffuse_color = (*linear, 1)
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*linear, 1)
    shader.inputs["Roughness"].default_value = 0.85
    palette[name] = mat

def collection(name):
    c = bpy.data.collections.new(name)
    scene.collection.children.link(c)
    return c

active = collection("01 • Street infrastructure")

def finish(obj, name, material):
    obj.name = name
    obj.data.materials.append(palette[material])
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    active.objects.link(obj)
    return obj

def box(name, center, size, material, bevel=0.03):
    x, y, z = center
    w, h, d = size
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, -z, y))
    obj = bpy.context.object
    obj.dimensions = (w, d, h)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel:
        modifier = obj.modifiers.new("Soft edges", "BEVEL")
        modifier.width = bevel
        modifier.segments = 2
    return finish(obj, name, material)

def cylinder(name, center, radius, depth, material):
    x, y, z = center
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=radius, depth=depth, location=(x, -z, y))
    return finish(bpy.context.object, name, material)

def tree(x, z, size=1.0):
    cylinder("Tree trunk", (x, 1.3, z), 0.14, 2.6, "wood")
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=1.3 * size, location=(x, -z, 3.0))
    finish(bpy.context.object, "Faceted canopy", "leaf")
    box("Tree bed", (x, 0.25, z), (1.5, 0.3, 1.5), "grass", 0.1)

box("Diorama plinth", (0, -0.65, 0), (38, 1.2, 23), "pine", 0.35)
box("District ground", (0, -0.08, 0), (37.6, 0.12, 22.6), "grass", 0.1)
for x in range(-16, 17, 4):
    box("Road_Straight_4m", (x, -0.1, 3), (4, 0.2, 4), "road", 0)
    # Rotated 2 x 4 m sidewalks, curb top at +0.15 m.
    for z in (0, 6):
        box("Sidewalk_Straight_2x4m", (x, 0.075, z), (4, 0.15, 2), "pavement", 0.02)
    if abs(x) < 10:
        box("Lane marker", (x, 0.012, 3), (1.4, 0.02, 0.08), "white", 0)
for x in (-12, 12):
    for z in (1.35, 2.0, 2.65, 3.3, 3.95, 4.6):
        box("Crossing", (x, 0.02, z), (1.8, 0.025, 0.3), "white", 0)

for index, (x, h, color, title) in enumerate([
    (-8, 3.5, "ivory", "01 • Local cafe"),
    (0, 6.5, "coral", "02 • Textile studio"),
    (8, 3.5, "sage", "03 • Wood workshop"),
]):
    # The detailed café is a separately editable GLB instance in City.tscn.
    if index == 0:
        continue
    active = collection(title)
    box("Storefront-col", (x, h / 2, -4), (4, h, 4), color, 0.09)
    box("Flat parapet roof", (x, h + 0.22, -4), (4.3, 0.44, 4.3), "white", 0.06)
    for offset in (-1.18, 0):
        box("Shop window", (x + offset, 1.8, -1.975), (0.9, 1.6, 0.08), "glass")
        box("Window sill", (x + offset, 0.92, -1.88), (1.05, 0.1, 0.24), "white")
    box("Door 1m x 2.1m", (x + 1.15, 1.2, -1.955), (1.0, 2.1, 0.10), "pine")
    box("Door handle", (x + 1.42, 1.2, -1.85), (0.05, 0.32, 0.07), "gold")
    box("Storefront sign backing", (x, 2.95, -1.86), (3.4, 0.45, 0.15), "pine")
    if index == 1:
        for offset in (-1.1, 1.1):
            box("Upper floor window", (x + offset, 4.9, -1.95), (0.9, 1.2, 0.10), "gold", 0.12)
        for offset, fabric in ((-0.8, "ivory"), (0, "gold"), (0.8, "sage")):
            box("Fabric display", (x + offset, 1.55, -1.76), (0.36, 1.1, 0.05), fabric)
    if index == 2:
        box("Workshop bench", (x + 2.9, 0.9, -3), (1.4, 0.15, 2.0), "wood")
        for dx in (2.35, 3.45):
            for z in (-3.75, -2.25):
                box("Bench leg", (x + dx, 0.45, z), (0.1, 0.9, 0.1), "pine")
        for n in range(3):
            box("Timber stack", (x + 3, 0.18 + n * 0.18, -5), (1.7, 0.16, 0.6), "wood")

active = collection("04 • Courtyard and street furniture")
box("Pocket park", (-15, 0.12, -3), (5, 0.24, 6), "pavement", 0.1)
for x, z in [(-16, -5), (-14, -5), (-16, -1), (4, -4), (15, -5), (-15, 8.8), (15, 8.8), (-6, 8.8), (6, 8.8)]:
    tree(x, z)
for x in (-14, -4, 4, 14):
    cylinder("Streetlamp 3.8m", (x, 1.95, 7.1), 0.055, 3.8, "pine")
    box("Lantern", (x, 3.8, 7.1), (0.38, 0.48, 0.38), "gold", 0.04)
    box("Lantern cap", (x, 4.08, 7.1), (0.5, 0.1, 0.5), "pine")
for x in (-9, 9):
    box("Bench seat", (x, 0.6, 8.2), (2, 0.18, 0.5), "wood")
    box("Bench back", (x, 1.0, 8.5), (2, 0.6, 0.12), "wood")
    for dx in (-0.75, 0.75):
        box("Bench support", (x + dx, 0.3, 8.2), (0.12, 0.6, 0.5), "pine")

# Floor-facing asset origins make every module straightforward to reposition.
for obj in list(scene.objects):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    scene.cursor.location = (obj.location.x, obj.location.y, min(v.z for v in corners))
    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
scene.cursor.location = (0, 0, 0)
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type == "VIEW_3D":
            area.spaces.active.overlay.grid_scale = 1.0
            area.spaces.active.overlay.grid_subdivisions = 4
bpy.ops.object.select_all(action="SELECT")
SOURCE.parent.mkdir(parents=True, exist_ok=True)
EXPORT.parent.mkdir(parents=True, exist_ok=True)
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(SOURCE))
bpy.ops.export_scene.gltf(filepath=str(EXPORT), export_format="GLB", use_selection=True,
                          export_apply=True, export_yup=True, export_animations=False,
                          export_cameras=False, export_lights=False)
print(f"DISTRICT_READY: {SOURCE} -> {EXPORT}")
