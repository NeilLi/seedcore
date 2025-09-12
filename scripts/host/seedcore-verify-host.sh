#!/usr/bin/env bash
set -euo pipefail

# SeedCore host-side verification orchestrator
# Requires: curl, jq, python3

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/../.. && pwd)"
cd "$ROOT_DIR"

echo "🔧 SeedCore host verification started"
echo "📦 Project root: $ROOT_DIR"

# Ensure env
if [[ -f scripts/host/env.host.sh ]]; then
  # Users typically 'source' this already. We won't override, just hint.
  echo "ℹ️  Tip: run 'source scripts/host/env.host.sh' before this script if you haven't."
fi

# Defaults (can be overridden via env)
RAY_DASH_URL="${RAY_DASH_URL:-http://127.0.0.1:8265}"
GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:8000}"

echo "🌐 Ray Dashboard: $RAY_DASH_URL"
echo "🌐 Gateway base:  $GATEWAY_URL"

echo "① Check Ray Serve topology..."
python3 scripts/host/seedcore_verify_topology.py --ray-dash "$RAY_DASH_URL"

echo "② Check forwarded ports..."
python3 scripts/host/seedcore_verify_ports.py \
  --host 127.0.0.1 \
  --ports 3306 5432 8265 10001 7474 7687 8000 8002 6379

echo "③ HTTP smoke checks..."
python3 scripts/host/seedcore_smoke_endpoints.py --gateway "$GATEWAY_URL"

echo "✅ All basic host verifications passed."
echo "💡 Optional: run synthetic energy experiments:"
echo "    python3 scripts/host/seedcore_energy_experiments.py --help"

