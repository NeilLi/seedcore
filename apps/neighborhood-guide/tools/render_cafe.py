"""Render views of the actual saved café model; never saves over the source.
blender --background assets/blender/courtyard_cafe.blend --python tools/render_cafe.py
Optional: -- --view Interior (or Exterior / RoofOff).
"""
from pathlib import Path
import argparse
import sys
import bpy

args=argparse.ArgumentParser()
args.add_argument("--view",choices=["Exterior","Interior","RoofOff"],default="Exterior")
args.add_argument("--samples",type=int,default=48)
parsed=args.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])
root=Path(__file__).resolve().parents[1]
output=root/"artifacts/cafe"
output.mkdir(parents=True,exist_ok=True)
scene=bpy.context.scene
scene.camera=bpy.data.objects[parsed.view]
scene.cycles.samples=parsed.samples
if parsed.view=="RoofOff":
    bpy.data.collections["CafeRoof"].hide_render=True
scene.render.filepath=str(output/(parsed.view.lower()+".png"))
bpy.ops.render.render(write_still=True)
print("CAFE_RENDER:",scene.render.filepath)
