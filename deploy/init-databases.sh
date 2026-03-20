#!/bin/bash
set -euo pipefail

# Get the directory of this script so we can call the others reliably
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Preflighting PostgreSQL + Bootstrapping Auxiliary Stores ==="
bash "$SCRIPT_DIR/init-basic-db.sh" "${NAMESPACE:-seedcore-dev}"

echo "=== Applying Comprehensive PostgreSQL Schema ==="
bash "$SCRIPT_DIR/init-full-db.sh"

echo "✅ All databases initialized successfully."
