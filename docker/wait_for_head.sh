#!/usr/bin/env bash
# Usage inside compose:  command: ["wait_for_head.sh", "seedcore-ray-head:6379", "ray", "start", "--address=seedcore-ray-head:6379", "--block"]

set -e
HEAD_ADDR=$1 ; shift          # first arg is host:port
echo "[wait_for_head] Waiting for $HEAD_ADDR ..."
for i in {1..60}; do
  (echo > /dev/tcp/${HEAD_ADDR/:/\/}) >/dev/null 2>&1 && break
  sleep 2
done
echo "[wait_for_head] Head reachable, launching: $*"
exec "$@" 