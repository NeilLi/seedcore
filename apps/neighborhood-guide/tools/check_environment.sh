#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
godot_bin="${GODOT_BIN:-$(command -v godot || true)}"
blender_bin="${BLENDER_BIN:-$(command -v blender || true)}"

if [[ -z "$godot_bin" && -x /Applications/Godot.app/Contents/MacOS/Godot ]]; then
	godot_bin=/Applications/Godot.app/Contents/MacOS/Godot
fi
if [[ -z "$blender_bin" && -x /Applications/Blender.app/Contents/MacOS/Blender ]]; then
	blender_bin=/Applications/Blender.app/Contents/MacOS/Blender
fi

[[ -n "$godot_bin" ]] || { echo "Godot 4.x was not found. Install the Godot cask or set GODOT_BIN." >&2; exit 1; }
[[ -n "$blender_bin" ]] || { echo "Blender was not found. Install Blender or set BLENDER_BIN." >&2; exit 1; }

echo "Godot: $($godot_bin --version)"
echo "Blender: $($blender_bin --version | head -n 1)"
echo "Project: $project_root"
