#!/usr/bin/env bash
set -euo pipefail

echo "🔧 Activating Python virtual environment..."
source venv/bin/activate

echo "🌍 Loading host environment variables..."
source scripts/host/env.host

echo "🚪 Starting port forwarding..."
./deploy/port-forward.sh

echo "🧠 Verifying SeedCore architecture..."
python scripts/host/verify_seedcore_architecture.py

echo "✅ Host setup and verification completed successfully!"

