#!/bin/bash
set -euo pipefail

# Get the directory of this script so we can call the others reliably
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Initializing Basic Database ==="
bash "$SCRIPT_DIR/init_basic_db.sh"

echo "=== Initializing Comprehensive Database ==="
bash "$SCRIPT_DIR/init_full_db.sh"

echo "✅ All databases initialized successfully."

