#!/bin/bash
# sc.sh - Shortcuts for seedcore Docker exec commands

case "$1" in
  head)
    docker exec -it seedcore-ray-head /bin/bash
    ;;
  api)
    docker exec -it seedcore-api /bin/bash
    ;;
  *)
    echo "Usage: $0 {head|api}"
    exit 1
    ;;
esac

