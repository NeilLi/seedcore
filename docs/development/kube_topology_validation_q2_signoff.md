# Kube Topology Validation Q2 Signoff

Date: 2026-04-10
Status: Remote Kind topology validated for hot-path, ingress, and HAL; verification API kube deployment lane implemented; live full-surface capture pending

## Purpose

This note records the live deployment-topology findings for the current
remote Kubernetes path so Q3 bridge work and Gemini-visible read-surface work
can start from checked-in evidence instead of memory.

It is specifically about the GCP VM + Kind topology exercised through
`build.sh` and `deploy/`.

## Topology In Scope

Validated live on 2026-04-10:

- Kind cluster on a GCP Debian VM
- image built through `build.sh`
- core deploy through `deploy/deploy-all.sh`
- Ray/KubeRay runtime
- SeedCore API
- HAL bridge in simulation mode
- nginx ingress controller plus SeedCore ingress routing

Present in this topology:

- PostgreSQL
- MySQL
- Redis
- Neo4j
- Ray head and worker
- `seedcore-api`
- `seedcore-hal-bridge`
- ingress-nginx

Not present in the last captured live run:

- Kafka broker
- verification API deployment on `:7071`

That distinction matters for signoff. This topology is now valid for
runtime-gate, hot-path, ingress, and HAL verification, but it is not yet a
complete end-to-end verification-surface topology.

## Gate Validation Result

The now-aligned live gates are green in this topology:

- `/health` returned `200`
- `/readyz` returned `200`
- `/api/v1/pdp/hot-path/status` returned `200`
- `verify_hot_path_observability.sh` passed against the live kube-backed API
- ingress routes resolved correctly for API, organism, and orchestrator paths
- HAL `/status` was healthy in simulation mode

Post-drill status snapshot:

- `runtime_ready=true`
- `authz_graph_ready=true`
- `graph_freshness_ok=true`
- `rollback_triggered=false`
- `rollback_reasons=[]`
- `alert_level="ok"`
- `mismatched=0`

This is good enough to treat the hot-path read contract as deployment-realistic
for this topology.

## Degraded And Adversarial Coverage

What was exercised live:

- Redis dependency-loss drill via `scripts/host/verify_pkg_redis_resilience.sh`
- ingress-controller routing through the in-cluster nginx service
- HAL bridge rollout and live status check

Redis outage result:

- baseline passed
- outage passed
- recovery passed
- runtime stayed operational throughout
- `/health` stayed `200`
- `/readyz` stayed `200`
- hot-path status stayed ready and non-rollback

What is still topology-limited:

- Kafka readiness/dependency drills are not meaningful here until Kafka is
  actually deployed in-cluster
- verification-surface live signoff via `verify_productized_surface.sh`
  remains incomplete in this topology because the verification API is not
  deployed

## Benchmark And Observability Baseline

The deployment-realistic hot-path benchmark is now stable enough to use as a
reference baseline for this topology.

Latest benchmark posture:

- mode: `shadow`
- requests: `40` with warmup `4` and concurrency `4`
- mismatch count: `0`
- error count: `0`
- `graph_freshness_ok=true`
- `authz_graph_ready=true`
- latency:
  - `p50=110.85ms`
  - `p95=139.12ms`
  - `p99=156.25ms`
  - `avg=111.10ms`

Latest baseline/signoff posture:

- `runtime_ready=true`
- `authz_graph_ready=true`
- `graph_freshness_ok=true`
- `alert_level="ok"`
- `mismatched=0`
- `parity_ok=88`
- `total=88`

Artifact families captured under the repo runtime directory:

- `.local-runtime/hot_path_benchmarks/`
- `.local-runtime/hot_path_baselines/`

## Verification API Integration Update

The deploy/verification lane now has first-class verification API integration:

- dedicated workload manifest:
  `deploy/k8s/verification-api.yaml` (`Deployment` + `Service` on `7071`)
- dedicated deploy runner:
  `deploy/deploy-verification-api.sh`
- orchestration wiring:
  `deploy/deploy-all.sh --deploy-verification-api`
- topology signoff upgrade:
  `deploy/verify-kube-topology.sh` now runs full
  `verify_productized_surface.sh` when verification API is reachable, with
  in-cluster audit-id fallback and full-surface gate reporting.

This means the topology can now promote to full external-agent verification
signoff as soon as the service is deployed and protocol checks are green.

## Latest Verification-Lane Evidence (2026-04-10)

Live runs on the remote Kind cluster now show the upgraded behavior:

- verification API deployment step succeeds:
  `deploy/deploy-verification-api.sh` rolled out
  `seedcore-verification-api` in `seedcore-dev`
- with verification service present, signoff reports include:
  - `verification_surface_available=true`
  - `verification_surface_protocol_passed=false`
  - `green_enough_for_full_external_agent_debugging=false`
- with verification service treated as absent (missing service name),
  signoff reports include:
  - `verification_surface_available=false`
  - `verification_surface_protocol_passed=false`
  - safe Gemini surface remains hot-path-only
- with `SEEDCORE_ENFORCE_FULL_VERIFICATION_GATE=1`, kube verification exits
  non-zero exactly as intended when full-surface criteria are not met.

Current full-surface blocker:

- runtime audit source is empty in this topology
  (`public.governed_execution_audit` has no rows), so the productized
  verification protocol cannot yet complete against runtime-backed audit IDs.

## Q3 Bridge Entry Decision

Decision for 2026-04-10:

- begin only the narrow, read-oriented Q3 bridge work
- do not widen delegated write/control surfaces based on this topology alone

Allowed next step:

- external-agent debugging against the stable hot-path read contract
- topology-aware read-only bridge work that assumes the current hot-path
  status/metrics semantics are stable enough for operator debugging

Not yet allowed from the last captured live run:

- bridge work that depends on a live verification API in this topology
- bridge work that assumes Kafka ingress/egress is available in-cluster
- widening the external authority surface or introducing contract-shaped
  write-side shortcuts for Gemini or other assistants

Operational interpretation:

- this topology is green enough for narrow read-only bridge work
- it is not yet green enough to claim full external-agent verification-surface
  signoff

## Smallest Safe Gemini-Visible Read Surface

The smallest safe Gemini-visible surface remains the exact read-only bundle
already defined in
[`src/seedcore/plugin/mcp_server.py`](/Users/ningli/project/seedcore/src/seedcore/plugin/mcp_server.py):

- `seedcore.verification.queue`
- `seedcore.verification.workflow_verification_detail`
- `seedcore.verification.workflow_replay`
- `seedcore.verification.runbook_lookup`
- `seedcore.hotpath.status`
- `seedcore.hotpath.metrics`

Safety rule (topology truth):

- only expose tools whose backing service is actually deployed in the target
  topology

Promotion logic:

- verification API unavailable or verification protocol failing:
  expose only:
  - `seedcore.hotpath.status`
  - `seedcore.hotpath.metrics`
- verification API available and verification protocol passing:
  expose the full minimal read-only bundle listed above

This keeps Gemini read access aligned with real deployment truth instead of
advertising tools that only work in fixture or host-only environments.

## Practical Next Steps

The next highest-value kube work should be:

1. run `deploy/deploy-all.sh ... --deploy-verification-api --verify-kube`
   on the target remote cluster and capture the full-surface signoff report
   (`verification_surface_available=true`,
   `verification_surface_protocol_passed=true`)
2. add Kafka only when the topology is ready to exercise real readiness-gate
   and delegated-intent ingress drills
3. keep Q3 bridge work read-only until those two topology gaps are closed
