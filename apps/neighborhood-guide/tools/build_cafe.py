"""Create a detailed, original Japanese courtyard café for Foundry Lane.

Reference: https://www.youtube.com/watch?v=SsBLhNgqTqQ (villa, adapted to café).
Run with Blender --background --python tools/build_cafe.py. Rebuilding existing
outputs requires -- --replace-generated. Copy hand-edited assets before doing so.
The saved .blend retains every authored object; the GLB batches by material and
semantic group for real-time use. Helpers accept Godot XYZ in meters.
"""
from pathlib import Path
import json
import math
import random
import sys
import bpy
import numpy as np
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/blender/courtyard_cafe.blend"
EXPORT = ROOT / "assets/models/courtyard_cafe.glb"
TEX_DIR = ROOT / "assets/models/cafe_textures"
if (SOURCE.exists() or EXPORT.exists()) and "--replace-generated" not in sys.argv:
    raise RuntimeError("Café assets exist. Preserve manual edits before using -- --replace-generated.")
random.seed(34)
rng = np.random.default_rng(34)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 1
scene.unit_settings.length_unit = "METERS"
TEX_DIR.mkdir(parents=True, exist_ok=True)

def linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def texture(name, rgb, kind):
    """Author tileable material swatches, not photographs or reference pixels."""
    n = 512
    y, x = np.mgrid[0:n, 0:n] / n
    noise = rng.normal(0, 0.014, (n, n))
    if kind == "wood":
        grain = np.sin(2 * math.pi * (x * 50 + 0.3 * np.sin(y * 2 * math.pi) + 0.14 * np.sin(y * 8 * math.pi)))
        detail = grain * 0.05 + 0.04 * np.sin(2 * math.pi * (x * 9 + 0.08 * np.sin(y * 2 * math.pi))) + noise
    elif kind == "stone":
        detail = noise * 2 + np.sin(x * 2 * math.pi + np.sin(y * 4 * math.pi)) * 0.028
    else:
        detail = noise * 0.6
    pixels = np.ones((n, n, 4), dtype=np.float32)
    for channel in range(3):
        pixels[:, :, channel] = np.clip(rgb[channel] + detail, 0.01, 0.99)
    image = bpy.data.images.new(name, width=n, height=n)
    image.pixels.foreach_set(pixels.ravel())
    image.filepath_raw = str(TEX_DIR / (name + ".png"))
    image.file_format = "PNG"
    image.save()
    image.pack()
    return image

mats = {}
def material(name, rgb, roughness=0.6, metallic=0, pattern=None):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = (*[linear(c) for c in rgb], 1)
    shader = mat.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = mat.diffuse_color
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = metallic
    if pattern:
        tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = texture(name, rgb, pattern)
        mat.node_tree.links.new(tex.outputs["Color"], shader.inputs["Base Color"])
        # Fine relief in Cycles; GLB retains the portable albedo/roughness.
        bump = mat.node_tree.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.16
        bump.inputs["Distance"].default_value = 0.008
        mat.node_tree.links.new(tex.outputs["Color"], bump.inputs["Height"])
        mat.node_tree.links.new(bump.outputs["Normal"], shader.inputs["Normal"])
    mats[name] = mat
    return mat

material("Warm oak", (0.56, 0.39, 0.24), 0.48, pattern="wood")
material("Smoked cedar", (0.29, 0.21, 0.15), 0.58, pattern="wood")
material("Lime plaster", (0.81, 0.78, 0.70), 0.88, pattern="plaster")
material("Honed limestone", (0.62, 0.61, 0.56), 0.8, pattern="stone")
material("Charcoal roof", (0.14, 0.17, 0.17), 0.48, 0.35)
material("Bronze metal", (0.24, 0.18, 0.12), 0.30, 0.7)
material("Porcelain", (0.9, 0.86, 0.76), 0.22)
material("Coffee", (0.14, 0.067, 0.026), 0.27)
material("Sage upholstery", (0.35, 0.42, 0.32), 0.95)
material("Black steel", (0.07, 0.085, 0.08), 0.32, 0.7)
material("Brushed stainless", (0.55, 0.57, 0.56), 0.3, 0.86)
material("Soil", (0.16, 0.12, 0.08), 1)
material("Gravel", (0.68, 0.67, 0.60), 1, pattern="stone")
for name, color in [("Leaf light", (0.41, 0.50, 0.23)), ("Leaf dark", (0.17, 0.31, 0.13)), ("Leaf mid", (0.26, 0.4, 0.18))]:
    material(name, color, 0.9)
glass = material("Clear glass", (0.65, 0.78, 0.76), 0.13)
glass.surface_render_method = "DITHERED"
glass_shader = glass.node_tree.nodes.get("Principled BSDF")
glass_shader.inputs["Alpha"].default_value = 0.16
glass_shader.inputs["Transmission Weight"].default_value = 0.25
glass_shader.inputs["IOR"].default_value = 1.45
lamp = material("Warm lamp", (1, 0.76, 0.4), 0.5)
lamp_shader = lamp.node_tree.nodes.get("Principled BSDF")
lamp_shader.inputs["Emission Color"].default_value = (1, 0.55, 0.20, 1)
lamp_shader.inputs["Emission Strength"].default_value = 2.5

groups = {}
for name in ("CafeShell", "CafeRoof", "CafeGlazing", "CafeFurniture", "CafeCounter", "CafeGarden", "CafeDetails"):
    col = bpy.data.collections.new(name)
    scene.collection.children.link(col)
    empty = bpy.data.objects.new(name, None)
    col.objects.link(empty)
    groups[name] = (col, empty)
active = "CafeShell"

def godot(v):
    return Vector((v[0], -v[2], v[1]))

def finish(obj, name, mat):
    obj.name = name
    obj.data.materials.append(mats[mat])
    for col in list(obj.users_collection):
        col.objects.unlink(obj)
    groups[active][0].objects.link(obj)
    obj.parent = groups[active][1]
    return obj

def uv_project(obj):
    # Object-space planar coordinates keep the material grain at a metric scale.
    mesh = obj.data
    if not mesh.uv_layers:
        mesh.uv_layers.new()
    uv = mesh.uv_layers.active.data
    for face in mesh.polygons:
        axis = max(range(3), key=lambda i: abs(face.normal[i]))
        axes = [i for i in range(3) if i != axis]
        for index in face.loop_indices:
            co = mesh.vertices[mesh.loops[index].vertex_index].co
            uv[index].uv = (co[axes[0]] * 1.2, co[axes[1]] * 0.45)

def box(name, center, dims, mat, bevel=0.012):
    bpy.ops.mesh.primitive_cube_add(size=1, location=godot(center))
    obj = bpy.context.object
    obj.dimensions = (dims[0], dims[2], dims[1])
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    uv_project(obj)
    if bevel:
        mod = obj.modifiers.new("Edge highlights", "BEVEL")
        mod.width = bevel
        mod.segments = 3
    return finish(obj, name, mat)

def cylinder(name, center, radius, depth, mat, vertices=24):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=godot(center))
    return finish(bpy.context.object, name, mat)

def rod(name, start, end, radius, mat):
    a, b = godot(start), godot(end)
    bpy.ops.mesh.primitive_cylinder_add(vertices=10, radius=radius, depth=(b-a).length, location=(a+b)/2)
    obj = bpy.context.object
    obj.rotation_euler = (b-a).to_track_quat("Z", "Y").to_euler()
    return finish(obj, name, mat)

def sphere(name, center, dims, mat, detail=2):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=detail, radius=1, location=godot(center))
    obj = bpy.context.object
    obj.scale = (dims[0], dims[2], dims[1])
    for poly in obj.data.polygons:
        poly.use_smooth = True
    return finish(obj, name, mat)

def quad(name, points, mat):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([godot(p) for p in points], [], [(0, 1, 2, 3)])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    uv_project(obj)
    return finish(obj, name, mat)

def text(name, words, position, height, mat):
    # Text faces the street (+Z in Godot).
    bpy.ops.object.text_add(location=godot(position), rotation=(math.pi/2, 0, 0))
    obj = bpy.context.object
    obj.data.body = words
    obj.data.align_x = "CENTER"
    obj.data.size = height
    obj.data.extrude = 0.0015
    obj.data.bevel_depth = 0.0005
    return finish(obj, name, mat)

def cup(x, y, z):
    cylinder("Cup body", (x, y + .043, z), .038, .08, "Porcelain")
    cylinder("Coffee surface", (x, y + .085, z), .032, .001, "Coffee")
    cylinder("Saucer", (x, y+.006, z), .067, .01, "Porcelain")
    bpy.ops.mesh.primitive_torus_add(major_radius=.023, minor_radius=.007, major_segments=16, minor_segments=8,
                                   location=godot((x+.042,y+.045,z)), rotation=(math.pi/2,0,0))
    finish(bpy.context.object, "Cup handle", "Porcelain")

def chair(x, z, angle=0):
    # Assemble in local coordinates then rotate around seat center.
    before = set(bpy.data.objects)
    box("Chair cushion", (x,.72,z), (.43,.09,.43), "Sage upholstery", .05)
    for dx in (-.18,.18):
        for dz in (-.18,.18):
            rod("Chair leg", (x+dx*1.2,.27,z+dz*1.2), (x+dx,.71,z+dz), .022, "Warm oak")
    box("Chair back", (x,1.03,z-.2), (.45,.39,.065), "Warm oak", .03)
    for obj in set(bpy.data.objects) - before:
        delta = obj.location - godot((x,0,z))
        from mathutils import Matrix
        rotation = Matrix.Rotation(angle, 4, "Z")
        obj.location = godot((x,0,z)) + rotation @ delta
        obj.rotation_euler.rotate_axis("Z", angle)

# 6 x 6 m main room, with a 0.8 m timber veranda and real openings.
box("Stone foundation", (0,.10,0), (6.35,.2,6.35), "Honed limestone", .025)
for index in range(38):
    x = -3.03 + index * .164
    box("Individual oak floorboard", (x,.24,.28), (.158,.08,6.8), "Warm oak", .004)
box("Entry tread", (.65,.10,3.8), (1.4,.2,.7), "Honed limestone", .015)
box("Back plaster wall", (0,1.70,-3), (6,.18+2.66,.18), "Lime plaster")
box("Left plaster wall", (-3,1.70,-.3), (.18,2.84,5.4), "Lime plaster")
box("Right wall rear pier", (3,1.70,-2.6), (.18,2.84,.8), "Lime plaster")
for x in (-2.94,-.45,1.3,2.94):
    box("Structural oak post", (x,1.73,2.94), (.14,2.94,.14), "Smoked cedar")
for x in (-2.94,2.94):
    for z in (-2.94,-.4,1.2):
        box("Structural side post", (x,1.73,z), (.14,2.94,.14), "Smoked cedar")
for z in (-2.94,2.94):
    box("Front-back lintel", (0,3.05,z), (6.1,.22,.19), "Smoked cedar")
for x in (-2.94,2.94):
    box("Side lintel", (x,3.05,0), (.19,.22,6.1), "Smoked cedar")
# Left facade has an open timber lattice; right is glazed with a doorway between.
for index in range(21):
    box("Vertical timber screen", (-2.78+index*.11,1.66,3.08), (.035,2.63,.075), "Warm oak", .003)
for y in (.40,1.65,2.93):
    box("Screen horizontal rail", (-1.68,y,3.08), (2.3,.045,.075), "Smoked cedar", .003)
active = "CafeGlazing"
for x, width in [(-1.7,2.30),(2.13,1.43)]:
    box("Facade glass", (x,1.68,2.96), (width,2.66,.015), "Clear glass", 0)
for z in (-1.4,.25,1.92):
    box("Right sliding glass", (2.99,1.68,z), (.015,2.66,1.51), "Clear glass", 0)
active = "CafeShell"
for z in (-2.2,-.6,1.1,2.9):
    box("Sliding glass mullion", (3.01,1.68,z), (.045,2.7,.045), "Bronze metal", .003)
for y in (.34,2.98):
    box("Side window rail", (3.01,y,.35), (.05,.05,5.18), "Bronze metal", .003)
box("Open sliding door leaf", (1.07,1.6,2.72), (.37,2.56,.05), "Warm oak")
rod("Door pull", (.94,1.25,2.78), (.94,1.65,2.78), .013, "Bronze metal")

# Hipped roof with a central open-to-sky planted court. Four trapezoid slopes,
# individually modeled raised seams, gutters, hip caps, soffits and rafters.
active = "CafeRoof"
outer = [(-3.65,3.18,-3.65),(3.65,3.18,-3.65),(3.65,3.18,3.65),(-3.65,3.18,3.65)]
inner = [(-1.15,3.98,-.95),(.55,3.98,-.95),(.55,3.98,.75),(-1.15,3.98,.75)]
for index in range(4):
    nxt = (index+1)%4
    quad("Roof slope", [outer[index],outer[nxt],inner[nxt],inner[index]], "Charcoal roof")
    # A second surface is the warm timber underside.
    quad("Timber soffit", [(x,y-.055,z) for x,y,z in [outer[index],inner[index],inner[nxt],outer[nxt]]], "Smoked cedar")
    for step in range(25):
        t = step/24
        a = Vector(outer[index]).lerp(Vector(outer[nxt]), t)
        b = Vector(inner[index]).lerp(Vector(inner[nxt]), t)
        a.y += .018
        b.y += .018
        rod("Raised standing seam", a, b, .012, "Charcoal roof")
    rod("Hip cap", outer[index], inner[index], .035, "Charcoal roof")
    rod("Eave gutter", outer[index], outer[nxt], .046, "Charcoal roof")
    rod("Courtyard upstand", inner[index], inner[nxt], .055, "Charcoal roof")
for x in (-3.45,3.45):
    rod("Rainwater pipe", (x,.22,-3.35), (x,3.16,-3.35), .034, "Charcoal roof")
for x in np.arange(-2.9,3.0,.48):
    box("Exposed roof rafter", (float(x),3.06,0), (.055,.12,6.9), "Warm oak", .003)

active = "CafeCounter"
box("Bar base", (-1.9,.74,-1.15), (1.25,.94,2.72), "Smoked cedar")
for z in np.arange(-2.45,.19,.082):
    box("Fluted counter face", (-1.257,.73,float(z)), (.035,.85,.035), "Warm oak", .003)
box("Stone counter", (-1.9,1.24,-1.15), (1.39,.085,2.86), "Honed limestone", .02)
box("Service back counter", (-1.2,.78,-2.56), (2.8,1,.62), "Warm oak")
box("Back counter worktop", (-1.2,1.31,-2.56), (2.84,.07,.66), "Honed limestone")
for x in (-2.35,-1.7,-1.05,-.4):
    rod("Drawer handle", (x-.16,1.08,-2.21), (x+.16,1.08,-2.21), .013, "Bronze metal")
# Espresso machine oriented toward the room, complete with brew heads and cups.
box("Espresso machine", (-1.25,1.6,-2.51), (.75,.48,.40), "Brushed stainless", .045)
box("Machine black face", (-1.25,1.61,-2.285), (.66,.29,.02), "Black steel")
box("Drip tray", (-1.25,1.36,-2.2), (.76,.035,.25), "Brushed stainless")
for x in (-1.46,-1.09):
    rod("Portafilter handle", (x,1.51,-2.22), (x,1.51,-2.06), .021, "Black steel")
    cup(x,1.38,-2.2)
    cup(x,1.84,-2.51)
for x in (-2.3,-1.94):
    box("Grinder base", (x,1.43,-2.53), (.23,.24,.25), "Black steel")
    cylinder("Bean hopper", (x,1.71,-2.53), .105,.32,"Clear glass")
    cylinder("Roasted beans", (x,1.68,-2.53), .09,.21,"Coffee")
    cylinder("Hopper lid", (x,1.88,-2.53), .11,.02,"Black steel")
for y in (1.85,2.38):
    box("Display shelf", (-1.6,y,-2.8), (2.36,.055,.30), "Warm oak")
    for j in range(7):
        cylinder("Ceramic jar", (-2.53+j*.29,y+.13,-2.76), .07,.22,"Porcelain")
        cylinder("Jar lid", (-2.53+j*.29,y+.25,-2.76), .072,.02,"Warm oak")
box("Pastry tray", (-1.8,1.305,-.4), (.7,.025,.45), "Bronze metal")
for x in (-2.0,-1.78,-1.56):
    sphere("Pastry", (x,1.37,-.4), (.085,.055,.065), "Warm oak")
cup(-1.75,1.29,.08)

active = "CafeFurniture"
for x,z in [(1.85,-1.35),(1.85,1.30)]:
    cylinder("Cafe oak tabletop", (x,1.01,z), .44,.065,"Warm oak",48)
    cylinder("Table pedestal", (x,.63,z), .045,.70,"Black steel")
    cylinder("Table foot", (x,.30,z), .23,.025,"Black steel")
    chair(x,z-.78)
    chair(x,z+.78,math.pi)
    cup(x-.12,1.05,z+.06)
    cup(x+.17,1.05,z-.06)
box("Window bench", (.42,.55,-2.5), (1.0,.55,.67), "Warm oak", .03)
box("Bench cushion", (.42,.87,-2.5), (.94,.12,.60), "Sage upholstery", .04)
for x in (-1.9,-.9):
    cylinder("Veranda stool", (x,.70,3.35), .23,.09,"Warm oak")
    for dx,dz in [(-.13,-.13),(.13,-.13),(-.13,.13),(.13,.13)]:
        rod("Stool leg",(x+dx,.2,3.35+dz),(x+dx,.68,3.35+dz),.02,"Black steel")

active = "CafeGarden"
box("Courtyard planter", (-.3,.36,-.1), (1.65,.2,1.65), "Honed limestone", .025)
box("Courtyard soil", (-.3,.48,-.1), (1.5,.06,1.5), "Soil")
rod("Courtyard tree trunk", (-.30,.51,-.1),(-.43,2.45,-.14),.035,"Smoked cedar")
for k in range(13):
    angle = k*2.4
    z = -.1+math.sin(angle)*random.uniform(.25,.6)
    x = -.30+math.cos(angle)*random.uniform(.25,.7)
    y = random.uniform(1.65,2.75)
    rod("Maple branch",(-.4,1.5,-.12),(x,y,z),.011,"Smoked cedar")
    for leaf in range(15):
        sphere("Maple foliage",(x+random.uniform(-.25,.25),y+random.uniform(-.12,.22),z+random.uniform(-.25,.25)),(.09,.025,.07),random.choice(["Leaf light","Leaf mid","Leaf dark"]),1)
for k in range(35):
    sphere("Courtyard pebble",(-.3+random.uniform(-.65,.65),.52,-.1+random.uniform(-.65,.65)),(.045,.023,.037),"Gravel",1)
for x in (-2.95,2.95):
    cylinder("Entry planter",(x,.43,3.35),.24,.50,"Honed limestone")
    for k in range(28):
        a=k*2.4
        rod("Planter stem",(x,.63,3.35),(x+.17*math.cos(a),1+random.random()*.3,3.35+.17*math.sin(a)),.006,"Leaf dark")
        sphere("Planter leaf",(x+.18*math.cos(a),1+random.random()*.25,3.35+.18*math.sin(a)),(.11,.03,.04),"Leaf mid",1)

active = "CafeDetails"
box("Cafe fascia sign",(.4,2.71,3.05),(1.37,.33,.06),"Smoked cedar")
text("Cafe name", "K O M O R E B I",(.4,2.66,3.09),.12,"Porcelain")
text("Cafe descriptor", "C O F F E E  &  C R A F T",(.4,2.51,3.08),.055,"Porcelain")
box("Chalk menu board",(-2.4,.87,3.72),(.56,.84,.05),"Black steel")
for x in (-2.72,-2.08):
    rod("Menu frame",(x,.23,3.62),(x,1.37,3.72),.022,"Warm oak")
text("Menu title","COFFEE",(-2.4,1.12,3.77),.085,"Porcelain")
text("Menu items","POUR OVER\nESPRESSO\nMATCHA\n\nSLOW DOWN",(-2.4,.98,3.77),.044,"Porcelain")
for x,z in [(-1.85,-.55),(1.85,-1.35),(1.85,1.3)]:
    rod("Pendant cable",(x,3.02,z),(x,2.3,z),.008,"Black steel")
    cylinder("Pendant shade",(x,2.32,z),.18,.12,"Bronze metal")
    cylinder("Pendant diffuser",(x,2.25,z),.145,.018,"Warm lamp")
    light_data=bpy.data.lights.new("Pendant light","POINT")
    light_data.energy=28
    light_data.color=(1,.70,.40)
    light_data.shadow_soft_size=.22
    light=bpy.data.objects.new("Pendant light",light_data)
    scene.collection.objects.link(light)
    light.location=godot((x,2.18,z))

# Render stage and lighting are saved in Blender, excluded from the GLB.
stage=bpy.data.collections.new("RenderStage")
scene.collection.children.link(stage)
bpy.ops.mesh.primitive_plane_add(size=200, location=(0,0,-.04))
ground=bpy.context.object
ground.name="Render ground"
ground.data.materials.append(mats["Gravel"])
for col in list(ground.users_collection): col.objects.unlink(ground)
stage.objects.link(ground)
scene.world.use_nodes=True
scene.world.node_tree.nodes["Background"].inputs["Color"].default_value=(.68,.76,.85,1)
scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value=.45
sun_data=bpy.data.lights.new("Afternoon sun","SUN")
sun_data.energy=2.2
sun_data.angle=math.radians(12)
sun=bpy.data.objects.new("Afternoon sun",sun_data)
scene.collection.objects.link(sun)
sun.rotation_euler=(math.radians(28),math.radians(-25),math.radians(-35))
area_data=bpy.data.lights.new("Soft sky","AREA")
area_data.energy=850
area_data.shape="DISK"
area_data.size=8
area=bpy.data.objects.new("Soft sky",area_data)
scene.collection.objects.link(area)
area.location=godot((2,7,5))
area.rotation_euler=(godot((0,1,0))-area.location).to_track_quat("-Z","Y").to_euler()
for name, location, target, lens in [
    ("Exterior",(8.8,5.1,11),(0,1.4,0),48),
    ("Interior",(2.3,1.9,2.55),(-1.0,1.35,-1.1),19),
    ("RoofOff",(7,9,9),(0,0.8,0),48),
]:
    data=bpy.data.cameras.new(name)
    camera=bpy.data.objects.new(name,data)
    scene.collection.objects.link(camera)
    camera.location=godot(location)
    camera.rotation_euler=(godot(target)-camera.location).to_track_quat("-Z","Y").to_euler()
    data.lens=lens
scene.camera=bpy.data.objects["Exterior"]
scene.render.engine="CYCLES"
scene.cycles.samples=48
scene.cycles.use_denoising=True
scene.render.resolution_x=1600
scene.render.resolution_y=1100
scene.render.resolution_percentage=100
scene.view_settings.view_transform="AgX"
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type=="VIEW_3D":
            area.spaces.active.region_3d.view_distance=14
            area.spaces.active.region_3d.view_location=(0,0,1.5)
            area.spaces.active.clip_end=500
bpy.ops.object.select_all(action="DESELECT")
bpy.context.preferences.filepaths.save_version=0
SOURCE.parent.mkdir(parents=True,exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(SOURCE))

# Evaluate bevels/text and batch by material under stable semantic parent nodes.
# This mutates only the in-memory export copy, after the editable file was saved.
authored_count=sum(len(c.objects)-1 for c,e in groups.values())
for group,(collection,parent) in groups.items():
    buckets={}
    for obj in list(collection.objects):
        if obj.type not in {"MESH","FONT"}: continue
        buckets.setdefault(obj.active_material.name,[]).append(obj)
    for material_name,objects in buckets.items():
        bpy.ops.object.select_all(action="DESELECT")
        for obj in objects: obj.select_set(True)
        bpy.context.view_layer.objects.active=objects[0]
        bpy.ops.object.convert(target="MESH")
        bpy.ops.object.join()
        bpy.context.object.name=group+"_"+material_name.replace(" ","_")
bpy.ops.object.select_all(action="DESELECT")
for col,parent in groups.values():
    for obj in col.objects: obj.select_set(True)
EXPORT.parent.mkdir(parents=True,exist_ok=True)
bpy.ops.export_scene.gltf(filepath=str(EXPORT),export_format="GLB",use_selection=True,
                          export_apply=True,export_yup=True,export_animations=False,
                          export_cameras=False,export_lights=False)
print("CAFE_READY:", authored_count,"authored parts;",SOURCE,"->",EXPORT)
