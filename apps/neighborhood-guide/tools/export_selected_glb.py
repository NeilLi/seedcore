"""Blender helper: export the current reviewed selection as a GLB.

Run from Blender's Scripting workspace. The file is deliberately simple: it
does not bake, generate, or mutate source meshes. Review/apply transforms in
the `.blend` source before running this export.
"""

from pathlib import Path
import bpy

PROJECT_ROOT = Path("/Users/ningli/project/seedcore/apps/neighborhood-guide")
OUTPUT = PROJECT_ROOT / "assets" / "models" / "neighborhood_selection.glb"

if not bpy.context.selected_objects:
    raise RuntimeError("Select one or more reviewed objects before exporting.")

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(
    filepath=str(OUTPUT),
    export_format="GLB",
    use_selection=True,
    export_materials="EXPORT",
    export_apply=True,
)
print(f"Exported {len(bpy.context.selected_objects)} object(s) to {OUTPUT}")
