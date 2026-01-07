#!/usr/bin/env bash
set -euo pipefail

RAY_ADDR="${RAY_ADDR:-http://127.0.0.1:8265}"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <actor-name-substring> [out|err] [--tail]"
  exit 1
fi

QUERY="$1"
STREAM="${2:-out}"
TAIL=false

for arg in "$@"; do
  [[ "$arg" == "--tail" ]] && TAIL=true
done

# 1. Get Actor Metadata and grab the Actor ID and Node ID
ACTOR_JSON=$(curl -s "$RAY_ADDR/api/v0/actors" | jq -r --arg q "$QUERY" '
  .data.result.result[] 
  | select(.state=="ALIVE") 
  | select((.name // "" | contains($q)) or (.class_name // "" | contains($q))) 
  | "\(.actor_id):\(.address.node_id)"
' | head -n 1)

if [[ -z "$ACTOR_JSON" ]]; then
  echo "❌ No ALIVE actor found matching: $QUERY"
  exit 1
fi

ACTOR_ID="${ACTOR_JSON%%:*}"
NODE_ID="${ACTOR_JSON##*:}"

echo "✅ Found Actor: $QUERY"
echo "🆔 Actor ID: $ACTOR_ID"
echo "🌐 Node ID: $NODE_ID"

# 2. Use the dedicated Actor Log API
# This avoids the "node_id must be provided" Pydantic error
LOG_URL="$RAY_ADDR/api/v0/logs/file?node_id=$NODE_ID&actor_id=$ACTOR_ID&suffix=$STREAM"

echo "🔗 $LOG_URL"
echo "----------------------------------------------------"

if [[ "$TAIL" == "true" ]]; then
  echo "📡 Tailing logs... (Ctrl+C to stop)"
  while true; do
    curl -s "$LOG_URL" | tail -n 50
    sleep 2
  done
else
  curl -s "$LOG_URL"
fi