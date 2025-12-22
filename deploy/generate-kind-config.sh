#!/usr/bin/env bash
set -euo pipefail

# Generate kind-config.yaml with dynamic project root path
# Usage: ./generate-kind-config.sh [output_path]
# Default output: same directory as script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEEDCORE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUTPUT_PATH="${1:-${SCRIPT_DIR}/kind-config.yaml}"

cat > "$OUTPUT_PATH" <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    image: kindest/node:v1.30.0
    extraMounts:
      - hostPath: ${SEEDCORE_ROOT}
        containerPath: /project
EOF

echo "✅ Generated kind-config.yaml at ${OUTPUT_PATH}"
echo "   Project root: ${SEEDCORE_ROOT}"

