#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

PLATFORM="${PLATFORM:-linux/amd64}"
IMAGE_NAME="${IMAGE_NAME:-seedcore}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE_REF="${IMAGE_NAME}:${IMAGE_TAG}"
DOCKERFILE="${DOCKERFILE:-docker/Dockerfile.optimize}"
BUILD_CONTEXT="${BUILD_CONTEXT:-.}"
ENABLE_ML="${ENABLE_ML:-0}"
LOAD_IMAGE="${LOAD_IMAGE:-1}"
NO_CACHE="${NO_CACHE:-0}"
PROGRESS="${PROGRESS:-plain}"

case "${ENABLE_ML}" in
  0|1) ;;
  *)
    echo "ENABLE_ML must be 0 or 1 (got '${ENABLE_ML}')"
    exit 1
    ;;
esac

case "${LOAD_IMAGE}" in
  0|1) ;;
  *)
    echo "LOAD_IMAGE must be 0 or 1 (got '${LOAD_IMAGE}')"
    exit 1
    ;;
esac

case "${NO_CACHE}" in
  0|1) ;;
  *)
    echo "NO_CACHE must be 0 or 1 (got '${NO_CACHE}')"
    exit 1
    ;;
esac

BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  VCS_REF="$(git rev-parse --short HEAD)"
else
  VCS_REF="unknown"
fi

if docker buildx version >/dev/null 2>&1; then
  build_cmd=(docker buildx build)
else
  export DOCKER_BUILDKIT=1
  build_cmd=(docker build)
fi

build_cmd+=(
  --platform "${PLATFORM}"
  -f "${DOCKERFILE}"
  -t "${IMAGE_REF}"
  "${BUILD_CONTEXT}"
  --build-arg "BUILD_DATE=${BUILD_DATE}"
  --build-arg "VCS_REF=${VCS_REF}"
  --build-arg "ENABLE_ML=${ENABLE_ML}"
  --progress "${PROGRESS}"
)

if [[ "${LOAD_IMAGE}" == "1" ]]; then
  build_cmd+=(--load)
fi

if [[ "${NO_CACHE}" == "1" ]]; then
  build_cmd+=(--no-cache)
fi

echo "Building ${IMAGE_REF}"
echo "  Dockerfile : ${DOCKERFILE}"
echo "  Platform   : ${PLATFORM}"
echo "  ENABLE_ML  : ${ENABLE_ML}"
echo "  Load image : ${LOAD_IMAGE}"
echo "  No cache   : ${NO_CACHE}"

"${build_cmd[@]}"
