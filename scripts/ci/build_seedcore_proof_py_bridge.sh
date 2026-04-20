#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CRATE_DIR="${PROJECT_ROOT}/rust/crates/seedcore-proof-py"
MANIFEST_PATH="${CRATE_DIR}/Cargo.toml"
PYTHON_BIN="${PYTHON_BIN:-python}"
RELEASE_BUILD="${RELEASE_BUILD:-1}"
OUTPUT_DIR="${OUTPUT_DIR:-${PROJECT_ROOT}/artifacts/wheels}"

if [[ ! -f "${MANIFEST_PATH}" ]]; then
  echo "seedcore-proof-py manifest not found at ${MANIFEST_PATH}" >&2
  exit 1
fi

mkdir -p "${OUTPUT_DIR}"

"${PYTHON_BIN}" -m pip install --upgrade pip
"${PYTHON_BIN}" -m pip install maturin

maturin_args=(build --interpreter "${PYTHON_BIN}" --out "${OUTPUT_DIR}")
if [[ "${RELEASE_BUILD}" == "1" ]]; then
  maturin_args+=(--release)
fi

(cd "${CRATE_DIR}" && "${PYTHON_BIN}" -m maturin "${maturin_args[@]}")

echo "seedcore-proof-py wheels:"
shopt -s nullglob
wheel_paths=("${OUTPUT_DIR}"/seedcore_proof_py-*.whl)
if [[ ${#wheel_paths[@]} -eq 0 ]]; then
  echo "No seedcore_proof_py wheel was produced in ${OUTPUT_DIR}" >&2
  ls -la "${OUTPUT_DIR}" >&2
  exit 1
fi
printf '%s\n' "${wheel_paths[@]}"
