"""Render an edited entrance .blend and export camera-aligned Godot hotspots.

blender --background assets/blender/neighborhood_entrance.blend \
    --python tools/render_entrance_blender.py
Does not overwrite the .blend. Save any Blender edits before running this.
"""
from pathlib import Path
import bpy
from bpy_extras.object_utils import world_to_camera_view

ROOT = Path(__file__).resolve().parents[1]
scene = bpy.context.scene
if scene.camera is None or scene.camera.data.type != 'ORTHO':
    raise RuntimeError('Entrance render requires its orthographic camera.')
if scene.render.resolution_x * 2 != scene.render.resolution_y * 3:
    raise RuntimeError('Use a 3:2 render aspect to match the app entrance.')
bpy.context.view_layer.update()
lines = ['extends RefCounted', '', '# Generated from Blender navigation anchors. Re-render to update.', 'const POINTS := {']
for key in ['explore', 'textile', 'wood', 'guide']:
    anchor = bpy.data.objects.get('Navigation_' + key)
    if anchor is None:
        raise RuntimeError('Missing camera projection anchor: ' + key)
    p = world_to_camera_view(scene,scene.camera,anchor.matrix_world.translation)
    if p.z <= 0 or not (0 <= p.x <= 1 and 0 <= p.y <= 1):
        raise RuntimeError('Navigation anchor is outside the camera: ' + key)
    lines.append(f'\t"{key}": Vector2({p.x:.6f}, {1-p.y:.6f}),')
lines.append('}')
scene.render.filepath = str(ROOT / 'assets/illustrations/entrance_render.png')
scene.render.film_transparent = True
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
bpy.ops.render.render(write_still=True)
(ROOT / 'scripts/entrance_layout.gd').write_text('\n'.join(lines)+'\n')
print('ENTRANCE_RENDER:', scene.render.filepath, flush=True)
print('ENTRANCE_LAYOUT: scripts/entrance_layout.gd', flush=True)
