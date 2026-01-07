#!/usr/bin/env bash
set -euo pipefail

RAY_ADDR="${RAY_ADDR:-http://127.0.0.1:8265}"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <actor-name-or-class-substring> [out|err] [--tail] [--all]"
  exit 1
fi

QUERY="$1"
STREAM="out"
TAIL=false
ALL=false

# parse remaining args
for arg in "${@:2}"; do
  case "$arg" in
    out|err) STREAM="$arg" ;;
    --tail)  TAIL=true ;;
    --all)   ALL=true ;;
    *)
      echo "Unknown arg: $arg"
      exit 1
      ;;
  esac
done

ACTORS_JSON="$(curl -s "$RAY_ADDR/api/v0/actors")"

# Collect matching PIDs (your Ray shape: .data.result.result[])
mapfile -t PIDS < <(echo "$ACTORS_JSON" | jq -r --arg q "$QUERY" '
  .data.result.result[]
  | select(.state=="ALIVE")
  | select((.name // "" | contains($q)) or (.class_name // "" | contains($q)))
  | .pid
')

if [[ ${#PIDS[@]} -eq 0 ]]; then
  echo "❌ No ALIVE actor found matching: $QUERY"
  echo
  echo "Tip: inspect available class_name values:"
  echo "$ACTORS_JSON" | jq -r '.data.result.result[].class_name' | sort -u
  exit 1
fi

if [[ "$ALL" = false ]]; then
  PIDS=("${PIDS[0]}")
fi

for PID in "${PIDS[@]}"; do
  echo "✅ Found actor PID: $PID"

  # /logs is plain text, not JSON
  LOG_FILE="$(curl -s "$RAY_ADDR/logs" | grep -E "^worker-${PID}-.*\.${STREAM}$" | head -n 1 || true)"

  if [[ -z "$LOG_FILE" ]]; then
    echo "❌ No worker log file found for PID $PID ($STREAM)."
    echo "Available logs for this PID:"
    curl -s "$RAY_ADDR/logs" | grep "worker-${PID}-" || true
    continue
  fi

  LOG_URL="$RAY_ADDR/logs/$LOG_FILE"
  echo "📄 Log file: $LOG_FILE"
  echo "🔗 $LOG_URL"
  echo

  if [[ "$TAIL" = true ]]; then
    echo "📡 Tailing (Ctrl+C to stop)..."
    while true; do
      echo "----- [PID $PID] $(date) -----"
      curl -s "$LOG_URL" | tail -n 80
      sleep 2
    done
  else
    curl -s "$LOG_URL"
  fi
done
