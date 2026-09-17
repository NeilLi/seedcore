# SeedCore Proof Kernel PyO3 Bridge Decision Memo

Date: 2026-04-20

## Purpose

This memo decides whether SeedCore should introduce a native Python extension
crate, `seedcore-proof-py`, that binds the Rust proof kernel
(`seedcore-proof-core`, `seedcore-verify`) into the coordinator process via
PyO3, replacing today's subprocess-based CLI bridge in
`src/seedcore/integrations/rust_kernel.py`.

The question has been tracked in the verifier hardening plan as Phase 4 item
#1. Phase 3 in-process crypto has already landed, which changes the
cost/benefit analysis materially.

## Decision

Decision: `DEFER`

Recommendation:

- do not introduce `seedcore-proof-py` in the current milestone
- keep the subprocess CLI bridge as the sole Python-to-Rust path
- revisit only when one of the explicit revisit triggers below fires

Short version:

- yes for the long-term shape of the kernel
- no for the current execution slice, because Phase 3 removed the largest
  cost driver the bridge was going to address

## Why this is deferred

The stated motivation for `seedcore-proof-py` in the hardening plan was:

1. eliminate subprocess spawn cost per verification
2. eliminate temp-file churn (PEM, signature, message)
3. allow the coordinator to hold on to Rust structs directly without
   JSON-round-tripping them

Phase 3 already removed items (1) and (2) at the substrate level:

- RESULT_VERIFIER no longer shells out to `openssl` per signature. The new
  path is an in-process `ed25519_dalek::VerifyingKey::verify` /
  `p256::ecdsa::VerifyingKey::verify` call inside the Rust binary.
- The per-signature filesystem footprint is gone. No more `/tmp` key,
  signature, or message scratch files.

What remains is one subprocess spawn per *verification job* (not per
signature), around a verification that now fits comfortably inside a few
milliseconds of Rust CPU once the binary is warm. That spawn cost is real but
it is several orders of magnitude smaller than it was before Phase 3, and
well inside the runtime's retry and watermark-polling budgets.

Item (3) is a code ergonomics win, not a correctness or performance win. It
would let Python code hold `VerificationReport` as a native object instead
of a JSON round-trip, which matters only if the coordinator grows code paths
that consume many Rust reports per second from Python. That is not the
current workload shape.

Against that weakened motivation, PyO3 adds real cost:

- **Build surface.** Adds `maturin` (or `setuptools-rust`) to the Python
  build system. CI needs to produce wheels for Linux x86_64, Linux aarch64,
  and macOS at minimum. The existing Rust binary CI already runs, but wheel
  publication is a second axis of build complexity.
- **Release coupling.** Python code and Rust code become version-coupled at
  the ABI boundary. Today the CLI path decouples them: any compatible
  `seedcore-verify` binary works with any compatible Python caller, gated
  only by the `list-error-codes` contract. PyO3 tightens that coupling in a
  way that makes partial rollouts and hotfix rollbacks harder.
- **Deployment surface.** The coordinator image gains a compiled Python
  extension. Any regression in the proof kernel now requires rebuilding the
  Python side, not just swapping the Rust binary.
- **Risk concentration.** A PyO3 segfault or panic in the extension takes
  down the coordinator process, not just the subprocess. The CLI path gives
  us crash isolation for free.

None of those costs are disqualifying, but they are real, and they buy less
now than they would have before Phase 3 landed.

## Revisit triggers

Revisit this decision if **any** of these are observed in production or in
a load test representative of production:

- **Throughput.** Sustained verifier throughput exceeds the CLI bridge's
  capacity (current budget: a process spawn per job is acceptable up to
  ~100 jobs/sec per coordinator replica). If the verifier queue builds
  persistently at or above that rate, the subprocess amortization breaks
  down and an in-process bridge becomes the right tool.
- **Latency.** End-to-end verification job latency (journal row appearance
  → outcome row persisted) exceeds its P99 SLO by more than 20% for more
  than a week, and spawn/JSON-roundtrip cost is a material contributor in
  profiling.
- **Python-held report consumption.** Any coordinator code path emerges
  that consumes more than a handful of Rust reports per verification job
  from Python, forcing repeated JSON round-trips per job.
- **Schema churn.** The Rust error taxonomy or report field set changes
  quickly enough that maintaining the `list-error-codes` JSON contract
  becomes a drag on kernel evolution. PyO3 would let Python import the
  types directly and skip the JSON surface.
- **Security or isolation requirement.** A policy change makes
  launching subprocesses from the coordinator container unacceptable (for
  example, a seccomp profile that disallows `execve`). In that case PyO3 is
  the only available path regardless of performance.

If none of these fire within two quarters, the right next step is to look at
the coordinator/verifier split ADR instead of this memo: crash isolation and
throughput scaling are cheaper to get by running the verifier as its own
process than by changing the Rust/Python bridge.

## What we do instead

No code changes. The existing subprocess bridge keeps working and keeps
evolving through the `list-error-codes` contract. Two small things that are
worth doing anyway, regardless of this memo:

1. Ensure the `seedcore-verify` release binary is available at a pinned
   path inside the coordinator image (already true).
2. Track bridge-call latency as a metric (`rust_kernel_call_seconds_p95`)
   so the first revisit trigger has real data to fire on. This is a
   sub-day addition.

## Alternatives considered

- **Scaffold only (empty crate + maturin config + one smoke API).** Rejected
  because a scaffold that no code path actually uses is carrying cost
  (CI wheels, docs, review burden) for zero benefit until a revisit
  trigger fires. Better to add the crate when we know it will be used.
- **Full PyO3 bridge now.** Rejected because Phase 3 removed the largest
  cost driver and none of the revisit triggers above have fired yet.
  Doing it now is speculative optimization and couples the release
  surface prematurely.
- **Replace CLI with a long-lived verifier subprocess managed by Python
  (e.g., RPC over a pipe).** Interesting middle ground but rejected for
  now because it introduces a third bridge style while Phase 3 already
  addresses the main per-call cost. Keeping two bridge styles in the
  tree (subprocess CLI + PyO3) will be enough complexity if we ever do
  need to add the native bridge.

## Notes

- This memo is intentionally stronger than the hardening plan's original
  Phase 4 framing, because the Phase 3 result reshaped the evidence.
- The memo does not foreclose the long-term architectural direction. The
  north-star shape still has `seedcore-proof-py` as a clean boundary
  between Rust kernel work and Python coordinator work. The decision here
  is about *when* to build it, not *whether* to build it.
- See also the coordinator/verifier split ADR for the other Phase 4 item;
  the two questions interact, and the split is the cheaper way to get
  isolation benefits in the interim.
