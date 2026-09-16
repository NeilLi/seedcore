"""Build and render SeedCore's original, editable 2D entrance in local Blender.

blender --background --python tools/build_entrance.py
Rebuild: append -- --replace-generated. Copies of hand edits should be saved first.
The PNG is a transparent orthographic render, not an AI image or the reference.
"""
from pathlib import Path
import argparse
import runpy
import math
import random
import sys
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'assets/blender/neighborhood_entrance.blend'
OUTPUT = ROOT / 'assets/illustrations/entrance_render.png'
PINS = ROOT / 'scripts/entrance_layout.gd'
parser = argparse.ArgumentParser()
parser.add_argument('--replace-generated', action='store_true')
parser.add_argument('--samples', type=int, default=48)
parser.add_argument('--width', type=int, default=1800)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
if any(p.exists() for p in [SOURCE, OUTPUT, PINS]) and not args.replace_generated:
    raise RuntimeError('Generated entrance exists. Save hand edits separately, then use --replace-generated.')
random.seed(27)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.scale_length = 1.0
materials = {}

def material(name, hex_color, roughness=.65, metal=0, emission=0):
    rgb = [int(hex_color[i:i+2], 16)/255 for i in (0, 2, 4)]
    linear = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in rgb]
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*linear, 1)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (*linear, 1)
    bsdf.inputs['Roughness'].default_value = roughness
    bsdf.inputs['Metallic'].default_value = metal
    if emission:
        bsdf.inputs['Emission Color'].default_value = (*linear, 1)
        bsdf.inputs['Emission Strength'].default_value = emission
    materials[name] = mat
    return mat

for name, color in {
    'Limestone':'ead5b0', 'Paving':'f2e2c7', 'Ivory':'fff0d4',
    'Terracotta':'d88263', 'Clay shadow':'a7523d', 'Sage':'899d78',
    'Forest':'395e47', 'Leaf':'749057', 'Leaf light':'a4ad63',
    'Lavender':'ac8faa', 'Bark':'876044', 'Oak':'ba8b59',
    'Honey':'eab768', 'Window':'52848a', 'Ink':'28483f',
    'Fabric':'edc494', 'Coral fabric':'bd6e54', 'Map green':'aab889',
}.items(): material(name, color)
material('Canal', '5e9baf', .21, .18)
material('Ripple', 'b5d7d7', .3)
material('Ceramic', '438d8a', .23)
material('Brass', 'c99852', .28, .6)
material('Lamp', 'ffe2a1', .3, emission=2)
material('Screen', '173848', .2)
material('Digital blue', '78d9ee', .3, emission=1)

active = None

def group(name):
    global active
    active = bpy.data.collections.new(name)
    scene.collection.children.link(active)
    return active

def finish(obj, name, mat=None):
    obj.name = name
    if mat: obj.data.materials.append(materials[mat])
    for c in list(obj.users_collection): c.objects.unlink(obj)
    active.objects.link(obj)
    return obj

def smooth(obj):
    for p in obj.data.polygons: p.use_smooth = True
    return obj

def bevel(obj, amount=.08, segments=3):
    mod = obj.modifiers.new('Soft handcrafted edges', 'BEVEL')
    mod.width, mod.segments = amount, segments
    obj.modifiers.new('Weighted corner normals', 'WEIGHTED_NORMAL')
    return obj

def box(name, pos, size, mat, rounding=.06):
    bpy.ops.mesh.primitive_cube_add(size=1, location=pos)
    obj = bpy.context.object
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if rounding: bevel(obj, rounding)
    return finish(obj, name, mat)

def sphere(name, pos, scale, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=12, radius=1, location=pos)
    obj = bpy.context.object
    obj.scale = scale
    return smooth(finish(obj, name, mat))

def cylinder(name, pos, radius, depth, mat, vertices=48):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=pos)
    return bevel(smooth(finish(bpy.context.object, name, mat)), .035, 2)

def rod(name, a, b, radius, mat):
    a, b = Vector(a), Vector(b)
    obj = cylinder(name, (a+b)/2, radius, (b-a).length, mat, 16)
    obj.rotation_euler = (b-a).to_track_quat('Z', 'Y').to_euler()
    return obj

def mesh(name, vertices, faces, mat):
    data = bpy.data.meshes.new(name)
    data.from_pydata(vertices, [], faces)
    data.update()
    obj = bpy.data.objects.new(name, data)
    active.objects.link(obj)
    obj.data.materials.append(materials[mat])
    return obj

def rounded_prism(name, pos, width, depth, height, radius, mat, upright=False):
    # Rounded XY footprint, optionally rotated into a kiosk's XZ facade.
    points = []
    for cx, cy, start in [(width/2-radius,depth/2-radius,0),(-width/2+radius,depth/2-radius,90),(-width/2+radius,-depth/2+radius,180),(width/2-radius,-depth/2+radius,270)]:
        for i in range(9):
            a = math.radians(start+i*90/8)
            points.append((cx+radius*math.cos(a), cy+radius*math.sin(a)))
    n = len(points)
    vertices = [(x,y,z) for z in (-height/2,height/2) for x,y in points]
    faces = [tuple(reversed(range(n))), tuple(range(n,2*n))]
    faces += [(i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n)]
    obj = mesh(name, vertices, faces, mat)
    obj.location = pos
    if upright: obj.rotation_euler.x = math.pi/2
    return bevel(obj, .045, 3)

def curve(name, points, radius, mat):
    data = bpy.data.curves.new(name, 'CURVE')
    data.dimensions = '3D'
    data.bevel_depth = radius
    data.bevel_resolution = 3
    spline = data.splines.new('POLY')
    spline.points.add(len(points)-1)
    for p, co in zip(spline.points, points): p.co = (*co, 1)
    obj = bpy.data.objects.new(name, data)
    active.objects.link(obj)
    data.materials.append(materials[mat])
    return obj

def text(name, value, pos, size, mat):
    data = bpy.data.curves.new(name, 'FONT')
    data.body = value
    data.align_x = 'CENTER'
    data.size = size
    data.extrude = .002
    obj = bpy.data.objects.new(name, data)
    active.objects.link(obj)
    data.materials.append(materials[mat])
    obj.location = pos
    obj.rotation_euler.x = math.pi/2
    return obj

def lathe(name, pos, profile, mat):
    n = 48
    vertices = [(r*math.cos(i*2*math.pi/n), r*math.sin(i*2*math.pi/n), z) for r,z in profile for i in range(n)]
    faces = []
    for j in range(len(profile)-1):
        for i in range(n):
            a, b = j*n+i, j*n+(i+1)%n
            faces.append((a,b,b+n,a+n))
    obj = mesh(name, vertices, faces, mat)
    obj.location = pos
    return smooth(obj)

def planter(x,y,z=.55,scale=1):
    lathe('Terracotta planter',(x,y,z),[(.22*scale,0),(.32*scale,.48*scale),(.34*scale,.49*scale),(.29*scale,.44*scale),(.24*scale,.06*scale)],'Terracotta')
    for i in range(7):
        a = i*2.4
        leaf = sphere('Sculpted leaf',(x+.20*scale*math.cos(a),y+.20*scale*math.sin(a),z+.65*scale),(.09*scale,.12*scale,.39*scale),'Leaf' if i%2 else 'Forest')
        leaf.rotation_euler = (.45*math.cos(a),.45*math.sin(a),a)

def tree(x,y,z=.55,height=3.8,lavender=False):
    cylinder('Tree planter',(x,y,z+.12),.65,.25,'Limestone')
    cylinder('Earth',(x,y,z+.26),.57,.03,'Sage')
    rod('Tree trunk',(x,y,z+.2),(x+.1,y,z+height*.7),.12,'Bark')
    for i in range(9):
        a = i*2.4
        dx,dy = math.cos(a)*.65,math.sin(a)*.65
        top = z+height*(.68+random.random()*.23)
        rod('Branch',(x,y,z+height*.42),(x+dx,y+dy,top),.055,'Bark')
        for k in range(3):
            sphere('Clustered canopy',(x+dx+random.uniform(-.25,.25),y+dy+random.uniform(-.25,.25),top+random.uniform(-.15,.2)),(.6,.58,.57),'Lavender' if lavender else ('Leaf light' if (i+k)%3==0 else 'Leaf'))

def lamp(x,y,z=.55):
    cylinder('Lamp foot',(x,y,z+.10),.22,.2,'Brass')
    rod('Lamp post',(x,y,z+.15),(x,y,z+2.25),.055,'Ink')
    cylinder('Globe collar',(x,y,z+2.22),.17,.11,'Brass')
    sphere('Opal globe',(x,y,z+2.47),(.25,.25,.28),'Lamp')

def area(name, pos, target, energy, color, size):
    data = bpy.data.lights.new(name,'AREA')
    data.energy, data.color, data.shape, data.size = energy,color,'DISK',size
    obj = bpy.data.objects.new(name,data)
    active.objects.link(obj)
    obj.location = pos
    obj.rotation_euler = (Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler()

# One authored island; canals and paths are visual set dressing, not route data.
group('01 • Limestone island and canal')
rounded_prism('Floating limestone island',(0,0,0),17,11,.7,1.8,'Limestone')
rounded_prism('Inset paving',(0,0,.39),16.65,10.65,.12,1.65,'Paving')
# Paver joints deliberately stop short of the river banks.
for y in range(-4,5):
    for x in [-7,-5,-3,1,3,5,7]:
        box('Paver joint',(x,y,.456),(1.7,.012,.007),'Limestone',0)
river = [(-1.75+1.0*math.sin(y*.72),y,.478) for y in [-5.3+i*10.6/80 for i in range(81)]]
verts = [(x+dx,y,z) for x,y,z in river for dx in [-.65,.65]]
mesh('Blue canal',verts,[(i*2,i*2+1,i*2+3,i*2+2) for i in range(80)],'Canal')
for side in [-1,1]: curve('Rounded canal coping',[(x+side*.73,y,z+.07) for x,y,z in river],.10,'Limestone')
for i in range(0,80,5):
    x,y,z = river[i]
    curve('Water glint',[(x-.28,y,z+.012),(x+.02,y+.08,z+.012),(x+.28,y+.04,z+.012)],.013,'Ripple')
# Arched pedestrian bridge across the stream.
for i in range(17):
    x = -3.8+i*.21
    z = .53+.52*math.sin(math.pi*i/16)
    box('Bridge stone tread',(x,-2.65,z),(.22,1.20,.18),'Limestone',.025)
for y in [-3.26,-2.04]:
    curve('Bridge parapet',[(-3.8+i*.21,y,.85+.52*math.sin(math.pi*i/16)) for i in range(17)],.10,'Ivory')

# A small skyline creates depth behind the four navigation destinations.
group('02 • Courtyard architecture')
box('Cafe plaster house',(-5.6,2.5,1.98),(3.2,2.6,3.0),'Limestone',.16)
rounded_prism('Cafe inset doorway',(-5.6,1.17,1.70),1.0,2.1,.08,.44,'Window',True)
for x in [-6.65,-4.55]:
    rounded_prism('Cafe arched window',(x,1.15,2.18),.62,1.22,.09,.30,'Honey',True)
    rod('Window mullion',(x,1.06,1.60),(x,1.06,2.75),.025,'Ivory')
# Roof planes and warm barrel tiles.
for side in [-1,1]:
    roof = box('Terracotta roof',(-5.6,2.5+side*.72,3.72),(3.7,1.75,.18),'Terracotta',.05)
    roof.rotation_euler.x = -side*.35
    for i in range(19):
        x = -7.3+i*.19
        rod('Barrel roof tile',(x,2.5,4.0),(x,2.5+side*1.55,3.45),.062,'Terracotta')
text('Cafe sign','S L O W  C O F F E E',(-5.6,1.02,3.05),.17,'Ink')
planter(-7.1,1.1)
# Rounded colonnade tower.
cylinder('Tower base',(-1.7,3.3,.73),1.40,.50,'Limestone')
cylinder('Tower drum',(-1.7,3.3,1.85),1.12,2.0,'Limestone')
cylinder('Tower ledge',(-1.7,3.3,2.88),1.32,.22,'Ivory')
for i in range(8):
    a = i*math.tau/8
    cylinder('Colonnade pillar',(-1.7+math.cos(a),3.3+math.sin(a),3.77),.105,1.6,'Ivory')
cylinder('Tower cornice',(-1.7,3.3,4.61),1.25,.20,'Limestone')
sphere('Blue ceramic dome',(-1.7,3.3,4.75),(1.13,1.13,.93),'Window')
cylinder('Dome foot',(-1.7,3.3,4.76),1.16,.18,'Ivory')
rod('Dome finial',(-1.7,3.3,5.35),(-1.7,3.3,5.93),.055,'Brass')
sphere('Finial bead',(-1.7,3.3,5.88),(.12,.12,.15),'Brass')
# Terraced civic building.
rounded_prism('Garden house',(2.6,3.4,2.20),4.4,3.1,3.5,.7,'Limestone')
for x in [1.2,2.6,4.0]:
    rounded_prism('Civic arched window',(x,1.80,2.1),.85,1.8,.12,.4,'Window',True)
rounded_prism('Roof garden terrace',(2.6,3.4,4.02),4.7,3.4,.30,.85,'Ivory')
rounded_prism('Roof garden bed',(3.45,3.7,4.25),2.2,1.9,.24,.7,'Sage')
box('Upper tower',(1.25,4.0,5.1),(1.5,1.5,2.0),'Limestone',.18)
box('Upper tower cornice',(1.25,4.0,6.12),(1.75,1.75,.22),'Ivory',.12)
rounded_prism('Upper window',(1.25,3.23,5.2),.64,1.05,.08,.22,'Window',True)
for x in [2,3,4]: planter(x,2.15,4.17,.6)
tree(3.7,3.8,4.38,1.9,True)
# Scalloped terracotta awning.
for i in range(20):
    x = .45+i*.22
    curve('Awning panel',[(x,1.80,3.4),(x,1.25,3.36),(x,.9,3.08)],.14,'Terracotta')

# Map terrace — map is made from actual meshes and curves.
group('03 • Explore map terrace')
cylinder('Map plaza',(-5.5,-2.0,.58),2.35,.27,'Limestone')
cylinder('Map plaza inset',(-5.5,-2.0,.73),2.22,.06,'Paving')
for x in [-6.6,-4.4]: box('Map post',(x,-1.4,1.55),(.18,.24,1.8),'Brass')
rounded_prism('Map ivory frame',(-5.5,-1.4,2.60),3.45,2.7,.30,.40,'Ivory',True)
rounded_prism('Map sea',(-5.5,-1.575,2.60),3.15,2.4,.04,.28,'Window',True)
for i in range(12):
    x = -6.85+random.random()*2.7
    z = 1.65+random.random()*1.8
    sphere('Map relief island',(x,-1.63,z),(.16+random.random()*.18,.06,.12+random.random()*.14),'Map green')
curve('Map wandering route',[(-6.6,-1.73,2.0),(-6.2,-1.73,2.8),(-5.7,-1.73,2.6),(-5.1,-1.73,3.25),(-4.6,-1.73,2.9)],.028,'Ivory')
for x,z in [(-6.2,2.8),(-5.1,3.25),(-4.6,2.9)]: sphere('Map destination',(x,-1.78,z),(.09,.04,.09),'Terracotta')
text('Map heading','F O U N D R Y  L A N E',(-5.5,-1.63,3.51),.12,'Ivory')
lamp(-7.3,-2.4,.78)

# Textile kiosk, with a dimensional shirt and hanging fabric swatches.
group('04 • Meet the textile makers')
rounded_prism('Textile coral kiosk',(.6,-.65,2.18),3.25,3.95,1.2,.60,'Terracotta',True)
rounded_prism('Textile cream inset',(.6,-1.28,2.18),2.88,3.56,.09,.47,'Ivory',True)
rounded_prism('Textile golden backing',(.6,-1.345,2.18),2.60,3.28,.055,.37,'Fabric',True)
box('Textile shelf',(.6,-1.63,1.03),(2.58,.66,.13),'Oak')
# Extruded T-shirt silhouette.
outline = [(-.48,-.62),(.48,-.62),(.48,.2),(.72,.08),(.94,.51),(.38,.83),(.2,.73),(-.2,.73),(-.38,.83),(-.94,.51),(-.72,.08),(-.48,.2)]
vertices = [(x*.74-.03,y,z*.74+2.62) for y in [-1.48,-1.57] for x,z in outline]
n = len(outline)
faces = [tuple(reversed(range(n))),tuple(range(n,2*n))]+[(i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n)]
bevel(mesh('Handmade display shirt',vertices,faces,'Ivory'),.06,3)
sphere('Shirt sun motif',(-.03,-1.60,2.65),(.24,.018,.24),'Terracotta')
sphere('Shirt landscape motif',(-.03,-1.615,2.53),(.24,.018,.12),'Sage')
for i,mat in enumerate(['Sage','Coral fabric','Window']):
    box('Hanging fabric swatch',(1.52,-1.46,2.7-i*.42),(.37,.045,.27),mat,.03)
text('Textile label','M A K E R S',(.6,-1.46,3.55),.16,'Clay shadow')
# Small slanted touchscreen at the counter.
terminal = box('Maker touchscreen',(.7,-1.75,1.39),(.68,.48,.12),'Brass')
terminal.rotation_euler.x = .45
screen = box('Maker screen',(.7,-1.77,1.465),(.57,.37,.015),'Window',.02)
screen.rotation_euler.x = .45
planter(2.35,-1.4)
area('Kiosk glow',(.5,-1.65,3.48),(.5,-1.3,1.5),28,(1,.70,.40),1.3)

# Craft vitrine: ceramic vase, carved bird, folded textiles.
group('05 • Local craft vitrine')
rounded_prism('Craft limestone kiosk',(5.7,.55,2.2),3.25,4.0,1.3,.65,'Limestone',True)
rounded_prism('Craft brass surround',(5.7,-.14,2.2),2.98,3.7,.10,.52,'Brass',True)
rounded_prism('Craft warm alcove',(5.7,-.21,2.2),2.70,3.43,.07,.44,'Fabric',True)
box('Craft display shelf',(5.7,-.61,1.13),(2.65,.87,.18),'Oak')
lathe('Glazed artisan vase',(5.15,-.59,1.23),[(.0,0),(.33,.02),(.48,.35),(.43,.69),(.25,.94),(.21,1.19),(.27,1.24),(.22,1.25),(.17,1.17),(.19,.95)],'Ceramic')
lathe('Vase gold lip',(5.15,-.59,1.23),[(.26,1.21),(.28,1.24),(.25,1.27),(.22,1.25)],'Brass')
for i in range(3):
    box('Folded woven textile',(6.28,-.68,1.31+i*.13),(.85,.55,.12),'Coral fabric' if i%2 else 'Ivory',.055)
    for j in range(6): rod('Textile tassel',(5.97+j*.12,-.97,1.27+i*.13),(5.97+j*.12,-1.08,1.22+i*.13),.015,'Fabric')
sphere('Carved bird body',(5.43,-.97,1.43),(.26,.16,.23),'Oak')
sphere('Carved bird head',(5.24,-.97,1.66),(.13,.12,.14),'Oak')
rod('Bird beak',(5.17,-1.02,1.65),(5.00,-1.02,1.64),.045,'Honey')
sphere('Bird eye',(5.21,-1.08,1.70),(.023,.018,.023),'Ink')
text('Craft label','L O C A L  C R A F T',(5.7,-.28,3.61),.15,'Clay shadow')
area('Display glow',(5.7,-.55,3.55),(5.7,-.4,1.1),38,(1,.76,.46),1.0)

# Robot guide desk with readable face and a welcoming gesture.
group('06 • Neighborhood guide desk')
cylinder('Guide terrace',(4.2,-3.6,.62),2.0,.30,'Limestone')
rounded_prism('Guide table',(4.1,-3.95,1.25),2.85,1.45,.23,.57,'Ivory')
for x in [3.2,5.0]: cylinder('Table pedestal',(x,-3.95,.91),.23,.66,'Limestone')
sphere('Guide robot body',(3.47,-3.35,1.42),(.43,.32,.52),'Ivory')
rounded_prism('Robot head',(3.47,-3.42,2.10),1.02,.82,.68,.32,'Ivory',True)
rounded_prism('Robot face',(3.47,-3.79,2.10),.81,.55,.045,.22,'Screen',True)
for x in [3.25,3.68]:
    sphere('Bright robot eye',(x,-3.83,2.17),(.064,.018,.092),'Digital blue')
curve('Robot smile',[(3.36,-3.835,1.98),(3.47,-3.845,1.94),(3.58,-3.835,1.98)],.021,'Digital blue')
for side in [-1,1]:
    rod('Robot upper arm',(3.47+side*.42,-3.35,1.65),(3.47+side*.66,-3.60,1.40),.12,'Ivory')
    rod('Robot forearm',(3.47+side*.66,-3.60,1.40),(3.47+side*.48,-3.91,1.44),.105,'Ivory')
    sphere('Robot hand',(3.47+side*.48,-3.91,1.44),(.13,.13,.11),'Brass')
rod('Robot antenna',(3.47,-3.42,2.48),(3.47,-3.42,2.72),.025,'Brass')
sphere('Robot antenna light',(3.47,-3.42,2.76),(.065,.065,.065),'Lamp')
box('Guide open map',(4.38,-4.04,1.39),(.8,.52,.035),'Sage',.02)
for i in range(3): box('Map fold',(4.16+i*.22,-4.04,1.413),(.015,.46,.01),'Ivory',0)
sphere('Desk lamp',(5.09,-4.03,1.61),(.18,.18,.20),'Lamp')
cylinder('Desk lamp base',(5.09,-4.03,1.39),.22,.045,'Brass')
cylinder('Visitor stool',(5.60,-4.35,.86),.49,.30,'Oak')
cylinder('Visitor seat',(5.60,-4.35,1.06),.52,.10,'Fabric')
text('Guide desk inscription','A S K  M E',(4.1,-4.69,1.23),.11,'Ink')

# Plants and finishing details.
group('07 • Trees and small discoveries')
tree(-7.0,3.5,.46,4.4)
tree(7.2,3.3,.46,3.2)
for x,y,s in [(-7.5,-4.0,.8),(-3.8,.5,.8),(7.1,-2.3,.9),(1.0,-4.5,.7),(-4.0,4.7,.7)]: planter(x,y,.46,s)
lamp(7.0,-2.2)
lamp(-3.4,1.2)
# A tiny boat at the entrance of the canal.
rounded_prism('Canal boat hull',(-1.3,-4.5,.68),.68,1.38,.28,.29,'Oak')
rounded_prism('Boat ivory gunwale',(-1.3,-4.5,.84),.61,1.27,.13,.25,'Ivory')
box('Boat cabin',(-1.3,-4.31,1.02),(.48,.61,.38),'Window',.09)
rounded_prism('Boat coral roof',(-1.3,-4.31,1.25),.65,.81,.14,.16,'Terracotta')

# Transparent studio lighting allows the app's cream background to show through.
group('08 • Orthographic render studio')
scene.world.use_nodes = True
scene.world.node_tree.nodes['Background'].inputs['Color'].default_value = (.72,.81,.91,1)
scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = .55
area('Large warm key',(-8,-10,17),(0,0,0),2300,(1,.85,.65),9)
area('Cool fill',(8,-1,12),(0,0,2),1500,(.76,.86,1),8)
area('Golden rim',(-2,9,14),(0,0,2),2400,(1,.86,.66),7)
camera_data = bpy.data.cameras.new('Entrance orthographic camera')
camera = bpy.data.objects.new('Entrance orthographic camera',camera_data)
active.objects.link(camera)
camera.location = (9,-23,18)
camera.rotation_euler = (Vector((0,0,2.15))-camera.location).to_track_quat('-Z','Y').to_euler()
camera_data.type = 'ORTHO'
camera_data.ortho_scale = 22.2
scene.camera = camera
scene.render.engine = 'CYCLES'
scene.cycles.samples = args.samples
scene.cycles.use_denoising = True
scene.render.resolution_x = args.width
scene.render.resolution_y = round(args.width*2/3)
scene.render.resolution_percentage = 100
scene.render.film_transparent = True
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
scene.render.filepath = str(OUTPUT)
scene.view_settings.view_transform = 'AgX'
scene.view_settings.look = 'AgX - Medium High Contrast'
# Editable, named empties bind image navigation to the source scene.
for key,position in {'explore':(-5.5,-1.8,1.15),'textile':(.6,-1.65,.83),'wood':(5.7,-.8,.89),'guide':(4.3,-4.7,.75)}.items():
    anchor = bpy.data.objects.new('Navigation_' + key,None)
    active.objects.link(anchor)
    anchor.location = position
    anchor.empty_display_type = 'SPHERE'
    anchor.empty_display_size = .18
    anchor['purpose'] = 'Presentation-only destination anchor; no execution authority.'
for screen in bpy.data.screens:
    for area_ui in screen.areas:
        if area_ui.type == 'VIEW_3D':
            area_ui.spaces.active.region_3d.view_perspective = 'CAMERA'
bpy.ops.object.select_all(action='DESELECT')
bpy.context.preferences.filepaths.save_version = 0
SOURCE.parent.mkdir(parents=True,exist_ok=True)
OUTPUT.parent.mkdir(parents=True,exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(SOURCE))
print('ENTRANCE_SOURCE:',SOURCE, 'objects:',len(scene.objects),flush=True)
runpy.run_path(str(ROOT / 'tools/render_entrance_blender.py'), run_name='__main__')
