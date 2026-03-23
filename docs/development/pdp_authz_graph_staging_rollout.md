# Staging Rollout Guide: `SEEDCORE_PDP_USE_ACTIVE_AUTHZ_GRAPH=true`

This guide describes a safe staged rollout for enabling automatic PDP use of the active compiled authorization graph.

## Goal

Enable:

```env
SEEDCORE_PDP_USE_ACTIVE_AUTHZ_GRAPH=true
```

in staging first, verify that the active PKG snapshot and active authz graph stay aligned, and only then promote the same behavior to production.

## Preconditions

Before enabling the flag in staging, confirm all of the following:

1. The active PKG snapshot loads successfully.
2. The authz graph builds successfully for that snapshot.
3. The new PKG operational endpoints are reachable:
   - `GET /api/v1/pkg/status`
   - `GET /api/v1/pkg/authz-graph/status`
   - `POST /api/v1/pkg/authz-graph/refresh`
4. The staging dataset contains the minimum authorization facts needed for controlled actions:
   - role facts
   - permission facts
   - resource-zone facts where applicable
5. The current staging flow is already green without the flag enabled.

## Recommended Rollout Order

### Step 1: Deploy Code With The Flag Disabled

Deploy the current build to staging with:

```env
SEEDCORE_PDP_USE_ACTIVE_AUTHZ_GRAPH=false
```

Then verify baseline health:

```bash
curl http://<staging-host>/api/v1/pkg/status
curl http://<staging-host>/api/v1/pkg/authz-graph/status
```

Expected result:

- PKG is healthy
- authz graph is present or can be refreshed manually
- no unexpected deny spike is visible in staging logs

If the authz graph is missing or stale, refresh it before moving on:

```bash
curl -X POST http://<staging-host>/api/v1/pkg/authz-graph/refresh
```

### Step 2: Validate Snapshot Alignment

Check that these match:

- `policy_snapshot` in governed decisions
- `active_version` from `GET /api/v1/pkg/status`
- `active_snapshot_version` from `GET /api/v1/pkg/authz-graph/status`

If they do not match, do not enable the flag yet.

## Step 3: Enable In One Staging Environment

Set:

```env
SEEDCORE_PDP_USE_ACTIVE_AUTHZ_GRAPH=true
```

Restart only the staging environment that is intended for authz-graph validation.

Immediately verify:

```bash
curl http://<staging-host>/api/v1/pkg/status
curl http://<staging-host>/api/v1/pkg/authz-graph/status
```

Expected result:

- `authz_graph_ready` is `true`
- active PKG snapshot and active authz graph snapshot versions match
- no initialization failures in the API logs

## Step 4: Run Targeted Governed Checks

Use a small fixed validation set of known requests:

1. one request that must be allowed
2. one request that must be denied
3. one request that depends on zone constraints
4. one request that depends on source-registration approval

For each request, confirm:

- the PDP result matches expectation
- `policy_snapshot` is correct
- no unexpected `authz_graph_snapshot_mismatch`
- no unexpected `authz_graph_denied`

## Step 5: Watch For These Failure Signals

Treat any of the following as rollout blockers:

- `authz_graph_snapshot_mismatch`
- unexpected `authz_graph_denied`
- repeated authz-graph refresh failures
- PKG snapshot activation succeeds but authz graph activation is unhealthy
- staging behavior diverges from the known allow/deny matrix

## Fast Rollback

If staging behavior is wrong, rollback is simple:

1. Set:

```env
SEEDCORE_PDP_USE_ACTIVE_AUTHZ_GRAPH=false
```

2. Restart the staging API deployment.
3. Re-run:

```bash
curl http://<staging-host>/api/v1/pkg/status
curl http://<staging-host>/api/v1/pkg/authz-graph/status
```

Disabling the flag returns the PDP to the prior behavior unless callers explicitly pass a compiled authz index.

## Production Promotion Criteria

Promote to production only after staging shows all of the following:

1. stable PKG and authz-graph health over at least one full deployment cycle
2. expected allow/deny behavior on the fixed governed validation set
3. successful manual authz-graph refresh during runtime
4. no snapshot mismatch errors
5. no unexplained policy deny increase

## Minimal Operator Checklist

- PKG status healthy
- authz graph status healthy
- snapshot versions aligned
- allow/deny smoke tests pass
- rollback path tested once in staging
