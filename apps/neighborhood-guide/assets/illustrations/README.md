# Entrance artwork

`entrance_render.png` is an original transparent 2D orthographic render made
with local Blender. It is the artwork used by the app entrance. The editable
source is `../blender/neighborhood_entrance.blend`; the deterministic recipe is
`../../tools/build_entrance.py`.

`../../tools/render_entrance_blender.py` renders a saved Blender source and
exports the camera-projected marker positions to `../../scripts/entrance_layout.gd`.
The four navigation markers are editable empties in the Blender scene. Godot
layers native keyboard-focusable controls over the resulting PNG.

`neighborhood_entrance.png` is the user's original visual reference, retained
unchanged for comparison. It is not used by the current entrance.

Both images depict a fictional presentation scene, not a render or map of the
navigable Foundry Lane district. Navigation remains local and advisory.
