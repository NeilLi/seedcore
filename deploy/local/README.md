# Local Host-Mode Helpers

This folder holds host-native SeedCore bring-up scripts for macOS/Linux development.

Use these when you want to run SeedCore directly on your machine without Kubernetes:

- `init-full-db-direct.sh`
- `run-api.sh`
- `run-hal.sh`
- `run-ray-head.sh`
- `run-serve-app.py`
- `run-bootstrap.sh`
- `run-ray-stack.sh`

These scripts are intentionally separate from the main `deploy/` entrypoints because they are:

- localhost-oriented
- best-effort developer workflows
- not the canonical Kubernetes deployment path
