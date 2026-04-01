#!/usr/bin/env bash
# Build a distributable tarball from the repo-frozen RCT sign-off tree (no .local-runtime capture).
# Use this when attaching Slice 1 closure evidence to a GitHub Release or external archive.
#
# Prerequisites: manifest and files already under tests/fixtures/demo/rct_signoff_v1
# (refresh from a new capture with scripts/tools/package_signoff_bundle.sh when needed).

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"
FIXTURE="${PROJECT_ROOT}/tests/fixtures/demo/rct_signoff_v1"
RELEASE_DIR="${PROJECT_ROOT}/release/rct_slice1_live_signoff_v1"
VERSION="${RCT_SIGNOFF_RELEASE_VERSION:-1.0.0}"
TARBALL_BASENAME="rct_slice1_live_signoff_v${VERSION}.tar.gz"
TARBALL_PATH="${RELEASE_DIR}/${TARBALL_BASENAME}"

if [[ ! -d "${FIXTURE}" ]]; then
  echo "ERROR: frozen fixture missing: ${FIXTURE}" >&2
  exit 1
fi

mkdir -p "${RELEASE_DIR}"

echo "==> Verifying frozen tree against manifest..."
python3 "${PROJECT_ROOT}/scripts/tools/verify_rct_signoff_bundle.py" --bundle-root "${FIXTURE}"

echo "==> Writing tarball ${TARBALL_PATH}"
rm -f "${TARBALL_PATH}"
(
  cd "${PROJECT_ROOT}/tests/fixtures/demo"
  tar -czf "${TARBALL_PATH}" rct_signoff_v1
)

echo "==> Writing ${RELEASE_DIR}/SHA256SUMS (relative paths for shasum -c)"
(
  cd "${RELEASE_DIR}"
  shasum -a 256 "${TARBALL_BASENAME}" > SHA256SUMS
)

echo "Done."
cat "${RELEASE_DIR}/SHA256SUMS"
