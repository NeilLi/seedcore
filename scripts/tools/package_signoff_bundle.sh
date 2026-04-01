#!/usr/bin/env bash
# Package the canonical RCT sign-off bundle into an immutable demo artifact.
# This bundle contains the irrefutable evidence chains for allow, deny, quarantine, and escalate cases.

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../" && pwd -P)"
CAPTURE_ROOT="${PROJECT_ROOT}/.local-runtime/rct_live_signoff/20260330T061828Z"
OUTPUT_DIR="${PROJECT_ROOT}/tests/fixtures/demo/rct_signoff_v1"
TARBALL_NAME="rct_signoff_bundle_v1.tar.gz"

echo "📦 Packaging RCT Sign-Off Bundle..."

if [ ! -d "${CAPTURE_ROOT}" ]; then
    echo "❌ Capture root not found: ${CAPTURE_ROOT}"
    exit 1
fi

# 1. Create target directory
mkdir -p "${OUTPUT_DIR}"

# 2. Sync cases and matrix metadata
echo "   - Copying canonical cases..."
for case_dir in allow_case deny_missing_approval quarantine_stale_telemetry escalate_break_glass; do
    if [ -d "${CAPTURE_ROOT}/${case_dir}" ]; then
        rm -rf "${OUTPUT_DIR:?}/${case_dir}"
        cp -R "${CAPTURE_ROOT}/${case_dir}" "${OUTPUT_DIR}/"
    else
        echo "⚠️  Warning: Case directory ${case_dir} missing from capture"
    fi
done

cp "${CAPTURE_ROOT}/matrix_summary.json" "${OUTPUT_DIR}/"

# 3. Generate Manifest with Checksums
echo "   - Generating manifest.json..."
(
    cd "${OUTPUT_DIR}"
    artifact_count=$(find . -type f ! -name "manifest.json" | sort | wc -l | awk '{print $1}')

    {
        echo "{"
        echo "  \"bundle_version\": \"1.0.0\","
        echo "  \"captured_at\": \"2026-03-30T06:18:28Z\","
        echo "  \"source_capture\": \"20260330T061828Z\","
        echo "  \"artifacts\": ["

        # Emit a stable artifact list with commas only between entries.
        i=0
        find . -type f ! -name "manifest.json" | sort | while read -r file; do
            suffix=","
            i=$((i + 1))
            if [ "${i}" -eq "${artifact_count}" ]; then
                suffix=""
            fi

            rel_path="${file#./}"
            sha256=$(shasum -a 256 "${file}" | awk '{print $1}')
            printf '    {"path": "%s", "sha256": "%s"}%s\n' "${rel_path}" "${sha256}" "${suffix}"
        done

        echo "  ]"
        echo "}"
    } > manifest.json
)

# 4. Create compressed tarball for distribution
echo "   - Creating tarball ${TARBALL_NAME}..."
tar -czf "${PROJECT_ROOT}/tests/fixtures/demo/${TARBALL_NAME}" -C "${PROJECT_ROOT}/tests/fixtures/demo" rct_signoff_v1

echo "✅ Success! Immutable demo artifact created at:"
echo "   Directory: ${OUTPUT_DIR}"
echo "   Tarball:   ${PROJECT_ROOT}/tests/fixtures/demo/${TARBALL_NAME}"
echo ""
echo "Pin verification: python scripts/tools/verify_rct_signoff_bundle.py"
echo "Release packaging: bash scripts/tools/package_frozen_signoff_tarball.sh"
