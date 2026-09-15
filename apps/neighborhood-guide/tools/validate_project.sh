#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
godot_bin="${GODOT_BIN:-$(command -v godot || true)}"
if [[ -z "$godot_bin" && -x /Applications/Godot.app/Contents/MacOS/Godot ]]; then
	godot_bin=/Applications/Godot.app/Contents/MacOS/Godot
fi
[[ -n "$godot_bin" ]] || { echo "Godot 4.x was not found. Run tools/check_environment.sh." >&2; exit 1; }

log_dir="$(mktemp -d)"
trap 'rm -rf "$log_dir"' EXIT
log_file="$log_dir/godot-validation.log"

"$godot_bin" --headless --path "$project_root" --editor --quit 2>&1 | tee "$log_file"
"$godot_bin" --headless --path "$project_root" --quit-after 2 2>&1 | tee -a "$log_file"
if rg -q 'SCRIPT ERROR:|Parse Error:|Compile Error:|^ERROR:' "$log_file"; then
	echo "Godot reported a project error; see output above." >&2
	exit 1
fi
echo "Godot project parsed and completed a headless smoke run."
