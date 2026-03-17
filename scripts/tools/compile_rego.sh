#!/usr/bin/env bash
set -euo pipefail

REGO_FILE="${1:-policy.rego}"
ENTRYPOINT="${2:-data.pkg.result}"

echo "[1] opa version"
opa version

echo "[2] fmt/check rego"
opa fmt --fail "$REGO_FILE"
opa check "$REGO_FILE"

echo "[3] quick eval sanity"
opa eval -d "$REGO_FILE" "data.pkg"

echo "[4] build wasm"
OUT="bundle.tar.gz"
opa build -t wasm -e "$ENTRYPOINT" -o "$OUT" "$REGO_FILE"

echo "[5] list bundle contents"
tar -tzf "$OUT"

echo "✅ OK: built $OUT"
