---
name: seedcore-local-runtime
description: Use when bringing up SeedCore locally, checking local runtime health, or guiding a user through host-mode verification before deeper PKG or hot-path work.
---

# Seedcore Local Runtime

Use this skill for local bring-up and readiness checks.

## Preferred checks

1. Call `seedcore.health`.
2. Call `seedcore.readyz`.
3. If PKG or hot-path work is involved, call `seedcore.pkg.status` and `seedcore.hotpath.status`.

## Fallback local flow

Use the host-mode sequence from `deploy/local/README.md`.

Key commands:

```bash
brew services start postgresql@17
brew services start redis
bash deploy/local/init-full-db-direct.sh
bash deploy/local/run-api.sh
```

Quick checks:

```bash
curl http://127.0.0.1:8002/health
curl http://127.0.0.1:8002/readyz
```

## Output expectations

- Report whether the API is healthy.
- Report whether dependencies are ready.
- If not ready, show the failing dependency and the next command to inspect.
