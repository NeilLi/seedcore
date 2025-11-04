# Routing Issue Fix Summary

## Problem

The dispatcher was failing to route tasks to the coordinator with the error:
```
[Errno -2] Name or service not known
```

This happened because the `CoordinatorHttpRouter` was trying to connect to `seedcore-svc-stable-svc:8000`, a Kubernetes service name that doesn't resolve in local environments.

## Root Cause

1. The dispatchers were created without the `SERVE_GATEWAY` environment variable being passed to them
2. When `SERVE_GATEWAY` was not available, `ray_utils.py` would fall back to the Kubernetes service name as a default
3. In local environments, this hostname cannot be resolved, causing DNS errors

## Fixes Applied

### 1. Updated `bootstraps/bootstrap_dispatchers.py`
- Added `SERVE_GATEWAY` and `RAY_ADDRESS` to `ENV_KEYS` list
- These environment variables are now passed to the dispatcher actors

### 2. Updated `deploy/k8s/bootstrap-dispatchers-job.yaml`
- Added explicit `SERVE_GATEWAY` environment variable set to `http://seedcore-svc-stable-svc:8000`
- This ensures proper configuration when running in Kubernetes

### 3. Enhanced Router Logging
- Improved `CoordinatorHttpRouter` initialization logging
- Now checks environment variable first, then falls back to `ray_utils`
- Better error messages to help with debugging

## How to Apply Locally

When running locally (not in Kubernetes), you need to set the `SERVE_GATEWAY` environment variable before starting the dispatchers:

```bash
export SERVE_GATEWAY=http://127.0.0.1:8000
```

Or when running the bootstrap script:

```bash
SERVE_GATEWAY=http://127.0.0.1:8000 python bootstraps/bootstrap_entry.py
```

## For Kubernetes Deployments

The `deploy/k8s/bootstrap-dispatchers-job.yaml` now includes `SERVE_GATEWAY` explicitly, so no additional changes are needed for Kubernetes deployments.

## Verification

After applying this fix, you should see logs like:
```
CoordinatorHttpRouter will connect to: http://127.0.0.1:8000/pipeline
CoordinatorHttpRouter initialized successfully with base_url: http://127.0.0.1:8000/pipeline
```

Instead of the DNS resolution errors.

