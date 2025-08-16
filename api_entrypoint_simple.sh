#!/usr/bin/env bash
set -euo pipefail

# Ensure we’re in app root
cd /app

# If your app needs any runtime tweaks, add them here (e.g., env defaults)
# : "${SOME_ENV:=default}"

# If no arguments were passed, CMD will be used; if args are passed in the Pod spec,
# they’ll replace CMD but still go through this shim.
exec "$@"
