# CubeSandbox Dependency Integration Sketch

Date: 2026-07-02
Status: Investigation sketch
Upstream: [TencentCloud/CubeSandbox](https://github.com/TencentCloud/CubeSandbox)

## Recommendation

**Pilot next, do not make it a core dependency yet.**

CubeSandbox is a reasonable dependency candidate for SeedCore's isolated
execution substrate, especially for untrusted code execution, agent-eval
rehearsal, self-healing dry runs, and high-concurrency sandbox fan-out. It
should not become a SeedCore authority source. The authority path remains:

```text
ActionIntent -> PDP allow/deny/quarantine -> scoped ExecutionToken
-> sandboxed actuator attempt -> receipt/evidence -> replay/RESULT_VERIFIER
```

CubeSandbox can host the attempt and produce execution, network, log, snapshot,
and egress-audit artifacts. It must not decide admissibility, mint or widen an
`ExecutionToken`, clear quarantine, or replace replay/verifier outcomes.

## Why It Is Relevant

CubeSandbox is designed as an AI-agent sandbox service built on RustVMM and
KVM. Its README advertises hardware-isolated sandboxes, E2B SDK compatibility,
sub-60ms sandbox creation, high density, snapshot/clone/rollback, and a Python
SDK. The current public service release is `v0.4.0`, while the PyPI Python SDK
is `cubesandbox==0.3.0` and requires Python >= 3.9.

The upstream features that map cleanly onto SeedCore are:

- **MicroVM isolation:** each sandbox runs its own Linux kernel under KVM rather
  than sharing the host kernel like a normal container.
- **E2B-compatible API/SDK:** useful for a thin adapter, especially for code
  execution and existing agent-eval harnesses.
- **Network policy:** sandbox creation can carry `allow_internet_access`,
  `allow_out`, `deny_out`, and L7 `rules`; CubeVS enforces L3/L4 policy and
  CubeEgress handles HTTP/HTTPS L7 policy.
- **Credential vault / egress proxy:** CubeEgress can inject outbound headers so
  secrets are not present in sandbox files, environment variables, or model
  context, while writing JSONL audit logs.
- **Snapshot, clone, rollback:** useful for deterministic retry, toxic-path
  reproduction, and parallel branch evaluation, if every snapshot and rollback
  is bound back to SeedCore evidence.
- **Structured logs:** the OpenAPI surface includes sandbox listing and log
  retrieval endpoints, which can become replay-linked evidence inputs.

## Fit In SeedCore

Treat CubeSandbox as a **sandbox execution provider** behind a SeedCore-owned
adapter:

```text
SeedCore governed caller
  -> ActionIntent for "run isolated attempt"
  -> PDP evaluates scope, template, network, secret, TTL, and evidence policy
  -> ExecutionToken binds request hash + template ID + network-policy hash
  -> CubeSandbox adapter creates/runs sandbox
  -> adapter collects logs, egress audit refs, snapshot refs, and exit result
  -> EvidenceBundle / receipt materializer records the attempt
  -> replay / RESULT_VERIFIER accepts, rejects, reviews, or quarantines
```

The adapter should be optional and profile-gated. It belongs near the current
sandbox hardening lane, not in the PDP hot path:

- `docs/development/gvisor_and_sandbox_hardening_strategy.md` remains the
  current sandbox strategy for container runtime hardening and verifier bridge
  compatibility.
- CubeSandbox is a future substrate option for stronger isolation and fast
  fan-out, not a replacement for PDP, `ExecutionToken`, evidence closure, or
  the subprocess-first verifier bridge decision.
- A Python dependency should be introduced only as an optional extra, for
  example a future `sandbox` or `sandbox-cube` extra, after the adapter contract
  and fixtures are written.

## Candidate MVP

The smallest useful SeedCore slice is a local or remote pilot adapter that can
run one non-production attempt and return a deterministic evidence summary.

1. **Adapter contract first**

   Define a SeedCore-owned `SandboxExecutionProvider` interface with explicit
   inputs:

   - `intent_id`
   - `execution_token_id`
   - `template_id`
   - command or code payload hash
   - TTL / idle timeout
   - network policy hash
   - secret-injection policy refs, not raw secrets
   - expected evidence obligations

   Outputs should include:

   - provider name and version
   - sandbox ID
   - template ID or snapshot ID
   - lifecycle state
   - exit code / timeout / provider error
   - stdout/stderr log refs or hashes
   - egress audit refs or hashes
   - snapshot/rollback refs when used
   - cleanup result

2. **Policy-gated creation**

   The adapter may call CubeSandbox only after PDP allow and token validation.
   Deny, quarantine, stale, expired, or preflight-only decisions must produce no
   sandbox creation. Network policy should be derived from policy constraints,
   not from model output.

3. **Evidence materialization**

   Persist the sandbox result as evidence, not authority. Required fields should
   include `sandbox_id`, `template_id`, `network_policy_hash`,
   `egress_audit_hash`, `log_hash`, `exit_status`, `created_at`, `terminated_at`,
   and `cleanup_status`.

4. **Negative fixtures**

   Add fixture coverage for:

   - missing token -> no sandbox create
   - token scope mismatch -> no sandbox create
   - unauthorized egress -> attempt returns fail-closed evidence
   - missing egress audit -> verifier review/quarantine
   - timeout -> cleanup attempted and evidence records non-closure
   - snapshot rollback used -> snapshot ID is visible to replay

5. **Dependency gate**

   Add the Python SDK only after the tests can run with a fake provider. The
   initial dependency should be optional because real CubeSandbox requires an
   x86_64 Linux host, KVM/PVM support, XFS-backed `/data/cubelet`, root-level
   installation, Redis/MySQL support services, and network hardening before any
   untrusted exposure.

## Policy Shape

CubeSandbox policy should be compiled from SeedCore policy inputs:

```json
{
  "sandbox_provider": "cubesandbox",
  "template_id": "tpl-code-rct-fixture",
  "allow_internet_access": false,
  "allow_out": ["api.example.internal"],
  "deny_out": ["169.254.0.0/16", "10.0.0.0/8"],
  "rules": [
    {
      "name": "allow_fixture_api",
      "match": {
        "scheme": "https",
        "sni": "api.example.internal",
        "host": "api.example.internal",
        "method": ["POST"],
        "path": "/v1/fixture/*"
      },
      "action": {
        "allow": true,
        "audit": "metadata"
      }
    }
  ]
}
```

The policy hash, not the raw mutable object, should be bound into the
`ExecutionToken` constraints and the post-execution evidence summary.

## Open Questions

- **Attestation:** CubeSandbox provides microVM isolation, but SeedCore still
  needs a profile-specific attestation story before treating sandbox runtime
  posture as strong closure evidence.
- **Audit ingestion:** CubeEgress writes per-host JSONL audit logs. SeedCore
  needs a stable collection path and hash strategy before making those logs
  verifier-readable.
- **Secret lifecycle:** credential injection is useful, but SeedCore should
  pass only secret refs or policy refs. Raw secret material should stay outside
  action intents, logs, model context, and replay exports.
- **Host mounts:** Cube-specific host mounts are powerful but risky. Treat
  writable host mounts as out of scope for the first pilot; read-only mounts
  require explicit policy and evidence hashing.
- **Platform fit:** this is not a macOS-local dependency. The real service needs
  a Linux/KVM host or PVM deployment path.
- **SDK/service skew:** service release and Python SDK release numbers are not
  identical. Pin and test the SDK separately from service rollout.

## Adoption Judgment

| Choice | Judgment | Reason |
| --- | --- | --- |
| Core hot-path dependency | Defer | The PDP/token path must stay small, deterministic, and independent of sandbox provider availability. |
| Optional provider adapter | Pilot next | The SDK/API shape is a good fit for isolated attempts and evidence capture. |
| Governance-learning / eval fan-out | Pick for pilot | Snapshot, clone, rollback, and high concurrency are useful for replay-derived negative drills and candidate repair. |
| Production actuator substrate | Track, do not pick yet | Needs attestation, audit ingestion, cleanup guarantees, and fail-closed evidence tests first. |

## Source Notes

- CubeSandbox README:
  [https://github.com/TencentCloud/CubeSandbox](https://github.com/TencentCloud/CubeSandbox)
- Architecture overview:
  [https://github.com/TencentCloud/CubeSandbox/blob/master/docs/architecture/overview.md](https://github.com/TencentCloud/CubeSandbox/blob/master/docs/architecture/overview.md)
- Security proxy:
  [https://github.com/TencentCloud/CubeSandbox/blob/master/docs/guide/security-proxy.md](https://github.com/TencentCloud/CubeSandbox/blob/master/docs/guide/security-proxy.md)
- Network policy:
  [https://github.com/TencentCloud/CubeSandbox/blob/master/docs/guide/network-policy.md](https://github.com/TencentCloud/CubeSandbox/blob/master/docs/guide/network-policy.md)
- Snapshot / rollback / clone:
  [https://github.com/TencentCloud/CubeSandbox/blob/master/docs/guide/snapshot-rollback-clone.md](https://github.com/TencentCloud/CubeSandbox/blob/master/docs/guide/snapshot-rollback-clone.md)
- Python SDK on PyPI:
  [https://pypi.org/project/cubesandbox/](https://pypi.org/project/cubesandbox/)
