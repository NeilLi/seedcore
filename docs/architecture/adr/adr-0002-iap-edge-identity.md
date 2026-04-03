# ADR 0002: Use Google IAP as the First-Mile Identity Gate for Non-Public SeedCore Ingress

- Status: Proposed
- Date: 2026-04-03
- Scope: Operator/admin ingress for `seedcore-api`, internal UI entry points, and externally reachable governance/control surfaces
- Related: [Architecture Overview](../overview/architecture.md), [Zero-Trust Custody and Digital-Twin Runtime](../overview/zero_trust_custody_digital_twin_runtime.md), [SeedCore API Reference](../../references/api/seedcore-api-reference.md), [ADR 0001: Keep the PDP Stateless and Synchronous at Decision Time](./adr-0001-pdp-hot-path.md)

## Context

SeedCore already has a strong action-authorization boundary inside the runtime: externally signed intents are verified, PDP decisions are deterministic over pinned policy/context inputs, execution tokens are short-lived, and governed receipts are replayable.

SeedCore does **not** yet have an equally explicit first-mile identity boundary at HTTP ingress:

- `seedcore-api` is a FastAPI app mounted under `/api/v1`, but there is no app-level middleware that validates an IAP assertion or normalizes a human operator principal into request context.
- `src/seedcore/main.py` currently enables CORS with `CORS_ALLOW_ORIGINS="*"` by default.
- `deploy/k8s/seedcore-api.yaml` exposes `seedcore-api` as a `NodePort` service and starts `uvicorn` directly.
- `deploy/k8s/ingress-routing.yaml` and the Helm API ingress template use `nginx` ingress conventions and do not define GCLB `BackendConfig`, GKE Gateway `GCPBackendPolicy`, or Cloud Run IAP settings.
- Current ingress routing sends `/organism`, `/pipeline`, and `/orchestrator` directly to the Ray Serve service, which means public exposure of Ray Serve paths is still a deployment concern.
- SeedCore also has public verification/trust endpoints such as `/api/v1/trust/{public_id}` and `/api/v1/verify/*`. An org-only IAP wall in front of the entire API host would break that public-read use case unless the public and operator surfaces are split.

Recent platform docs and Zero Trust research point to a layered model rather than a single "IAP solves everything" boundary:

- NIST SP 800-207A recommends combining network-tier and identity-tier policies, service identity infrastructure, authorization modules, and monitoring over access requests and directory changes.
- Google Cloud now supports enabling IAP directly on Cloud Run so all ingress paths, including `run.app`, are routed through IAP before the container receives the request.
- For GKE, IAP is enabled through `BackendConfig` on Ingress or `GCPBackendPolicy` on Gateway, but those are different control planes; `BackendConfig` is not valid for Gateway, and moving an existing BackendConfig from custom OAuth credentials to a Google-managed OAuth client requires recreating the backend.
- Google Cloud requires applications to validate `x-goog-iap-jwt-assertion`; unsigned `x-goog-authenticated-user-*` headers are explicitly not sufficient as a security mechanism if IAP can be bypassed.
- IAP health checks on Compute/GKE do not include JWT headers, so any app-side IAP validator must explicitly allow health-check paths.
- Programmatic access is supported with user/service OIDC tokens or service-account signed JWTs. With a Google-managed OAuth client, programmatic access is blocked by default unless the OAuth client is allowlisted. Service-account OIDC tokens must include an `email` claim.
- A 2025 arXiv preprint, "Identity Control Plane: The Unifying Layer for Zero Trust Infrastructure," argues for a unified human/workload/automation identity plane using OIDC/SAML, workload identity, brokered transaction tokens, and ABAC policy engines such as OPA/Cedar. That direction matches "IAP for ingress identity + SeedCore PDP for action authorization" better than replacing the PDP with edge IAM alone.

## Decision

SeedCore will use **Google Identity-Aware Proxy (IAP)** as the first-mile identity-aware gate for **non-public operator/admin ingress** and internal organization-only UI entry points.

SeedCore will **not** treat IAP as the sole authorization system for governed actions, and will **not** place public trust/verification reads behind an org-only IAP boundary by default.

### Decision Shape

- IAP authenticates human operators and trusted org users before they reach protected admin/control routes.
- SeedCore's PDP, DID/delegation checks, signed-intent verification, and execution-token semantics remain the authoritative operation-level authorization boundary after ingress authentication.
- For operator-triggered governed actions, the IAP principal and the SeedCore governance principal must both be captured in the audit/replay surface. If an IAP user identity contradicts the owner/assistant principal implied by a signed intent, delegation, or policy context on a high-consequence route, the request must fail closed or be quarantined.
- Public trust and verification reads must be served from a **separate public hostname or deployment path** that is intentionally not org-IAP-gated, while write/admin/control surfaces remain IAP-protected.
- Ray Serve, Ray dashboard, and other internal control paths should be private cluster services by default. They should not be published directly to the internet unless a gateway layer validates IAP signed headers and preserves request attribution.

### Phased Rollout for the Current Baseline

#### Phase 1: Add an IAP-Protected Operator Ingress Lane for `seedcore-api`

Keep the current `nginx`/NodePort path for local development and non-prod bring-up, but introduce a separate production operator ingress lane backed by Google Cloud HTTP(S) Load Balancing + IAP for `seedcore-api` admin/control traffic.

This ADR does **not** claim the existing manifests are already IAP-ready. It requires follow-on deployment work to add one of these Google Cloud ingress patterns:

- GKE Ingress + `BackendConfig` with `spec.iap.enabled: true`
- GKE Gateway + `GCPBackendPolicy` with `default.iap.enabled: true`
- Cloud Run direct IAP once a service is actually migrated to Cloud Run

#### Phase 2: Add a Single FastAPI IAP Principal Middleware

Add one request middleware in `seedcore-api` that, when IAP enforcement is enabled by config:

- reads `x-goog-iap-jwt-assertion`
- verifies signature, issuer, expiry, and the deployment-specific expected audience
- extracts canonical fields such as `sub`, `email`, `hd`, and any `google.access_levels`
- stores a normalized operator principal on request context and emits structured logs
- rejects missing or invalid IAP assertions on protected routes
- explicitly exempts `/health` and `/readyz`
- optionally exempts public trust/verification read routes only if they are still served from the same binary during the migration window

Do **not** trust unsigned `x-goog-authenticated-user-email` or `x-goog-authenticated-user-id` as the primary security signal in production mode.

#### Phase 3: Define Machine-to-Machine Access

- Internal pod-to-pod and `seedcore-api` to Ray Serve traffic should stay on private cluster service URLs plus NetworkPolicy, not browser-oriented IAP redirects.
- External automation that must traverse IAP should use service-account JWTs or OIDC ID tokens in `Authorization: Bearer ...` or `Proxy-Authorization: Bearer ...`.
- Grant least-privilege `roles/iap.httpsResourceAccessor` to the calling identity and scope `roles/iam.serviceAccountTokenCreator` or `roles/iam.serviceAccountOpenIdTokenCreator` to specific target service accounts, not project-wide.
- If a Google-managed OAuth client is used, explicitly allowlist the OAuth client used by programmatic callers.

#### Phase 4: Cloud Run Transition Only After a Real Cloud Run Service Exists

Once a SeedCore service is migrated to Cloud Run, enable IAP directly on that service with `gcloud run deploy --iap` or `gcloud run services update --iap`, keep `--no-allow-unauthenticated`, and grant `roles/run.invoker` to the IAP service agent.

Cloud Run direct IAP protects all ingress paths for the service, including `run.app`, so public trust pages and private operator APIs should be split into separate Cloud Run services if anonymous public reads must remain available.

## Decision Boundaries

This ADR defines **ingress identity and admission** for human/operator traffic.

It does not replace:

- SeedCore PDP decisions
- owner/assistant DID and delegation semantics
- signed intent verification
- execution-token issuance
- governed receipts and replay evidence

This ADR also does not require an immediate migration of every existing `nginx` ingress route, Ray Serve route, or local dev script to IAP in one step. It requires a concrete split between protected operator surfaces and intentionally public verification surfaces, and it requires the app to cryptographically validate IAP assertions wherever IAP is expected to be the edge identity gate.

## Why

This is the most feasible interpretation of "use IAP" for the current SeedCore baseline because it preserves the existing governance architecture while fixing the weakest external boundary first.

Why this shape is preferable:

- It aligns with NIST's layered Zero Trust guidance: edge identity checks, service identity, application authorization, and monitoring should work together rather than collapse into one layer.
- It keeps SeedCore's domain-specific authorization semantics in the PDP, where custody, delegation, trust gaps, and execution-token constraints are already modeled.
- It avoids breaking public verification APIs that are meant to be consumed anonymously.
- It gives operators org-native IAM onboarding/offboarding and Cloud Audit Logging without forcing every router to implement bespoke auth.
- It creates a clean migration path from today's GKE/nginx baseline to IAP-backed GCLB/Gateway and later Cloud Run, instead of pretending Cloud Run one-click IAP is already the deployed baseline.

## Consequences

Positive:

- Human operator/admin ingress can be tied to Google Workspace/Cloud Identity principals.
- The audit trail can record both the ingress operator identity and the SeedCore governance principal, which improves forensic reconstruction without weakening PDP semantics.
- Public read surfaces and private write/control surfaces get a cleaner separation.
- External CI/MCP automation gets a supported non-browser authentication path instead of ad hoc bypasses.
- Ray Serve and Ray dashboard exposure can be reduced by keeping them private behind `seedcore-api` or an explicit gateway.

Negative:

- Dual ingress modes add deployment complexity during migration: local/dev `nginx` versus production IAP-backed GCLB/Gateway/Cloud Run.
- `seedcore-api` must own IAP assertion verification, expected-audience config, public-key caching, and test fixtures.
- Health checks, CORS preflight, and public trust endpoints need explicit route-level treatment.
- IAP adds latency and is incompatible with Cloud CDN on protected backends, so latency-sensitive direct Ray Serve paths should stay private or use a different pattern.
- Changing IAP OAuth-client mode on existing GKE backends can require backend recreation and a maintenance window.

## Implementation Notes

- Add a dedicated module for IAP verification and request-principal normalization instead of parsing headers independently in each router.
- Keep IAP disabled by default for local dev and CI unless explicitly enabled by environment variables such as `SEEDCORE_IAP_REQUIRED=true` and `SEEDCORE_IAP_AUDIENCE=...`.
- Use synthetic signed-header fixtures or a test-only bypass flag in integration tests; do not introduce production code that trusts arbitrary unsigned `x-goog-*` client headers.
- Normalize ingress identity into stable fields such as `operator_sub`, `operator_email`, `operator_hd`, `operator_access_levels`, `iap_aud`, `iap_iss`, and request correlation IDs.
- Persist ingress operator identity in governed audit rows for operator-initiated actions if existing `actor` columns are not enough to reconstruct provenance.
- For GKE Ingress using a Google-managed OAuth client, start with a new backend if possible. If an existing backend already uses custom OAuth credentials and must switch, plan a recreate window.
- For GKE Gateway, use `GCPBackendPolicy`; for classic GKE Ingress, use `BackendConfig`. Do not mix those assumptions in one manifest.
- Keep `/health` and `/readyz` unauthenticated at the pod-probe layer. If request middleware enforces IAP, explicitly bypass those paths because GKE/Compute health checks do not send JWT headers.

## Follow-On Work

- Define the split-horizon hostname plan, for example `ops.<domain>` behind IAP and `trust.<domain>` public.
- Add the production IAP ingress manifests for the chosen Google Cloud ingress controller and keep the existing `nginx` path for local/dev.
- Add FastAPI middleware for IAP JWT verification and principal extraction.
- Add integration tests for missing/invalid IAP JWTs, health-check exemptions, public-trust-route access, and IAP-principal versus DID-principal mismatch handling.
- Decide whether the MCP developer service should remain local/private only or be exposed through an IAP-protected operator hostname.
- Measure IAP latency overhead before putting latency-sensitive Ray Serve paths behind IAP.

## Alternatives Considered

### Keep `nginx` Ingress Only and Rely on App-Local Auth Later

Rejected as the production target for operator ingress. It leaves identity enforcement too implicit at the edge and pushes too much custom auth logic into application code.

### Put the Entire API Host, Including Public Trust Pages and Direct Ray Serve Paths, Behind One Org-Only IAP Boundary

Rejected for the current baseline. Public trust verification needs anonymous reads, and direct Ray Serve publication is not yet wrapped by a stable app-layer IAP principal validator or a narrow gateway contract.

### Bypass IAP for All Automation Over Private VPC Paths Only

Rejected as the only machine-to-machine pattern. Private in-cluster calls should stay private, but external CI/MCP automation still needs a first-class auditable identity path through service-account OIDC/JWT credentials.

### Replace SeedCore PDP/DID Delegation with IAP/IAM Alone

Rejected. IAP authenticates ingress users and can enforce coarse access policy, but it does not encode SeedCore's custody graph, owner DID delegation, trust-gap semantics, replay evidence, or execution-token contract.

## References

- [Configure IAP for Cloud Run](https://docs.cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run)
- [IAP release notes](https://docs.cloud.google.com/iap/docs/release-notes)
- [Programmatic authentication for IAP](https://docs.cloud.google.com/iap/docs/authentication-howto)
- [Getting the user's identity with IAP](https://docs.cloud.google.com/iap/docs/identity-howto)
- [Securing your app with signed headers](https://docs.cloud.google.com/iap/docs/signed-headers-howto)
- [GKE Ingress configuration: BackendConfig + IAP](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/ingress-configuration)
- [GKE Gateway configuration: GCPBackendPolicy + IAP](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/configure-gateway-resources)
- [NIST SP 800-207A announcement](https://www.nist.gov/news-events/news/2023/09/zero-trust-architecture-model-access-control-cloud-native-applications)
- [Identity Control Plane: The Unifying Layer for Zero Trust Infrastructure](https://arxiv.org/abs/2504.17759)
