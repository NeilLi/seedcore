# CW-G02: signed simulation evidence and Studio inspection

Date: 2026-11-04
Status: Independent Python/Rust verification and known-attempt Studio inspection implemented locally; package promotion and production/physical qualification remain open
Review scope: CW-G02-STUDIO-LOCAL (evidence label, not a PDP deny code)

This implements the bounded [2 November plan](cw_g02_daily_plan_2026_11_02.md)
on the [CW-G01 local native adapter](central_world_cw_g01_admission.md). It adds
host-signed simulation exports and independent offline Python verification.
The [3 November slice](cw_g02_daily_plan_2026_11_03.md) adds the independent Rust
verifier and shared positive/refusal corpus described below.
The [4 November slice](cw_g02_daily_plan_2026_11_04.md) adds the bounded Studio
inspector and actual browser download/import evidence for a known local attempt.
It does not promote the endpoint into production or qualify physical devices.
The supported executor remains the pinned synthetic two-joint reference,
native MuJoCo 3.15.0, `dt=0.002`, position `kp=1`, at most 120 steps / 240 ms.

## Additive contract

[`cw_evidence.py`](../../../src/seedcore/robotics/cw_evidence.py) defines:

| Contract | Meaning |
| --- | --- |
| `seedcore.cw-g02.expected.v1` | Admission context saved through a separately trusted channel; exact request/service-instance/endpoint, revision/epoch, candidate, source, executor, review, token and payload identities plus expected signer references |
| `seedcore.cw-g02.receipt.v1` | Signed terminal manifest containing that context, start/end wall times, every substep's authority-check wall time, terminal state/reason/count and original-artifact byte hashes |
| `seedcore.cw-g02.bundle.v1` | Signed receipt and seven original JSON artifacts encoded as base64 bytes |
| `seedcore.cw-g02.simulation-trust.v1` | Separately supplied public key snapshot, explicit key purposes/endpoint bindings and revoked key references |
| `seedcore.cw-g02.verification.v1` | Read-only completed/interrupted/quarantine disposition, exact input/context/trust hashes and source references |

The seven artifacts are `token`, `candidate`, `source`, `parameters`, `review`,
`executor` and `capture`. The loaded endpoint source retains its exact bytes,
including whitespace. The other original in-memory artifacts are serialized
with RFC 8785 canonical JSON; token claims/signatures remain intact. Each raw
artifact's SHA-256 is signed in the manifest. The manifest uses the existing
`artifact` / `artifact_hash` / `signature` envelope: Ed25519 over the ASCII
hexadecimal RFC 8785 SHA-256 digest. Repeated exports return identical cached bytes.

The original `seedcore.cw-g01.capture.v1` stays `signed: false`. Its surrounding
receipt authenticates the artifact and the host's terminal claim. It does not
turn simulated state into device telemetry, prove physical safety, or establish
native trajectory correctness by signature alone. Host-observed times are signed
claims, not independent physical timing measurements.

The service adds a fresh public instance UUID at startup. It is bound in the
separately saved admission context and receipt; it is not a new ExecutionToken
field. The frozen token claims/constraints and existing Fast Spine schemas are
unchanged. Fast Spine's `spine_sim://` receipt validator is not used to accept a
CW capture under a different schema.

The CW-specific Rust reader in
[`cw_json.rs`](../../../rust/crates/seedcore-verify/src/cw_json.rs) rejects
duplicate keys, excessive depth/nodes, nonfinite numbers, unsafe integral
values and oversized inputs before verification. Its RFC 8785 writer sorts
unescaped property names by UTF-16 code units and formats binary64 numbers with
exactly pinned `ryu-js=0.2.2` (Apache-2.0 OR BSL-1.0). Cargo.lock records the
registry checksum; the build is verified with Rust 1.75. Serde's float-roundtrip
reader is enabled for this dependency path. Existing shared proof canonicalization
code and global token schemas are unchanged. Both implementations run the same
82 fixed canonicalization/refusal vectors, including Unicode ordering, escapes,
safe integers, negative zero, subnormals and seeded binary64 samples.

## Explicit configuration and export

Existing `seedcore.cw-g01.service-config.v1` configurations continue to provide
the original unsigned capture without receipt signing. To enable this slice,
retain the existing explicit source/review/PDP/claim configuration, use
`schemaVersion: "seedcore.cw-g02.service-config.v1"`, and supply:

```json
{
  "receiptSigningKeyPath": "receipt-host.pem",
  "receiptKeyRef": "cw-simulation-receipt-host"
}
```

The private configuration and key files must satisfy the existing private
regular-file checks. The receipt key must be Ed25519 and have a distinct key
reference from the PDP token signer. No normal startup path creates keys or
registration/delegation evidence. The reviewed executor digest now also pins
`cw_evidence.py`; a previously reviewed source/executor pair must be reviewed
again for this installed adapter image, rather than bypassing the digest check.

The same-origin admission response includes `evidenceContext` when signing is
configured. Save it separately at admission through the trusted local service
channel. Save/provision the public trust snapshot independently. Do not derive
either input from an untrusted imported bundle.

After a nonempty admitted attempt terminates, download its bytes with the
read-only route:

```text
GET /api/cw-g02/{request_id}/evidence
```

It responds with `attempt.cw-g02.bundle.json`, `Cache-Control: no-store` and an
attachment header. Active/empty/unadmitted attempts and missing signers cannot
produce a successful export. Sealing failure is an explicit failure response;
it does not relabel, resume or advance the attempt, and does not return an
unsigned substitute. The service caches a successful bundle in its bounded
attempt record. Retain the downloaded file: this slice does not add durable
server-side evidence storage across process restart.

## Independent offline verification

```bash
.venv/bin/python -m seedcore.robotics.cw_evidence \
  --bundle attempt.cw-g02.bundle.json \
  --expected saved-admission-context.json \
  --trust reviewed-simulation-trust.json
```

The independent Rust command takes the same three files:

```bash
cargo build --manifest-path rust/Cargo.toml --locked -p seedcore-verify
rust/target/debug/seedcore-verify verify-cw-evidence \
  --bundle attempt.cw-g02.bundle.json \
  --expected saved-admission-context.json \
  --trust reviewed-simulation-trust.json
```

[`cw_evidence.rs`](../../../rust/crates/seedcore-verify/src/cw_evidence.rs)
implements the structural, signature, binding, time and capture checks in Rust;
it does not invoke Python, MuJoCo or any execution endpoint. It computes CW's
RFC 8785 hashes independently and reuses the existing detached Ed25519 verifier
over those hashes. It does not pass CW artifacts through legacy proof hashing.

Each CLI reads only those local files, emits JSON on stdout and exits zero for
`verified_completed` / `verified_interrupted`, one for `quarantine` or input
failure. It makes no service/network calls or execution requests and does not
change the original artifacts or clear runtime quarantine. Its disposition is
a local report, not a write into RESULT_VERIFIER.

Trust snapshot entries have explicit `key_ref`, `key_algorithm: "ed25519"`,
base64 raw `public_key`, `trust_anchor_type` and `endpoint_id` fields. The token
signer's purpose is `service`; the receipt signer's purpose is `host_simulation`.
The outer snapshot contains only `version`, `trusted_keys` and `revoked_keys`.
A key advertised by an export is not adopted as trust. Every report records the
snapshot digest used; this is not a live revocation lookup.

Verification enforces original-artifact hashes, receipt/token signatures and
key revocation, independently expected action/instance/configuration identities,
the prepared payload hash, review window and every captured step's authorization
window. Historical token expiry at verification time alone does not reject a
run; execution must have occurred within its admitted window.

Both receivers require canonical padded base64, including zero padding bits,
for artifact/key/signature bytes. CW timestamps require explicit RFC 3339 zones
and microsecond-or-coarser precision; offsets and lowercase `t`/`z` are accepted,
while ambiguous ISO spellings, leap seconds and submicrosecond precision are
quarantined. This freezes the service clock's precision rather than letting
Python truncate extra digits differently from Rust. The original exporter
already emits this subset. Captured revision bindings are revalidated as strict
bindings so numeric/boolean coercion cannot alias an authority epoch.
Structured candidate/executor comparisons also distinguish booleans from JSON
numbers; executor clock settings and source frame counters require numeric
values of the declared kind. A trusted signature does not bypass those checks.

It requires contiguous ticks, matching time/count coverage, the pinned controls
and LED cues, finite correctly sized state/pose vectors, body inventory, unit
quaternions and observed positions within admitted limits. Completion requires
all 120 steps and a matching completed terminal state. The accepted interrupted
subset is a nonempty intact prefix stopped by `operator_stop` or
`service_shutdown`; other fenced/fault outcomes remain exportable for inspection
but are quarantined by this foundation. An interrupted run cannot be relabeled
as completed. Imports are bounded to 2 MiB and each artifact to 256 KiB, with
strict duplicate-key/nonfinite/depth checks and no external artifact paths.

## 4 November: Studio Evidence Inspector

Moments now exposes **Verify this attempt**, bounded same-attempt bundle import,
and downloads for the exact inspected bytes, independently retained admission
context, and the original Python/Rust report JSON. The unsigned capture keeps
its separate label. Scope/outcome are visible; request/instance, coverage,
revision/epoch, candidate/model/source/executor and trust-snapshot identities
are available in the expandable binding section. Untrusted text is rendered
with text APIs. Inspection/import never replaces the authoring graph or solver
state and makes no admission/start/stop request.

Enable this operator feature with `seedcore.cw-g02.service-config.v2`, retaining
the v1 receipt/PDP/source/review fields and adding:

```json
{
  "evidenceTrustPath": "reviewed-verification-trust.json",
  "evidenceTrustSha256": "<SHA-256 of the original trust file bytes>"
}
```

The private service config remains mode 0600. The public trust snapshot must be
a bounded regular nonsymlink file without group/other write access, pinned by
its raw-byte SHA-256 and capped at 32 KiB. The displayed trust-snapshot digest
is the existing CW canonical JSON digest, distinct from that raw-file pin.
No browser-provided key/context is adopted. Existing v1 configurations retain
their previous behavior and show verification unavailable with operator guidance.
This adapter is included in the native executor source pin; update review pins
through the existing review process for the new installed image.

`POST /api/cw-g02/{request_id}/verify` accepts only the original bundle bytes
under same-origin JSON requests, capped at 2 MiB while streaming. The service
requires its own known nonempty terminal attempt and retained expected context.
[`cw_evidence_studio.py`](../../../src/seedcore/robotics/cw_evidence_studio.py)
runs the actual Python function and fixed local Rust command outside the native
execution lock. One expensive inspection runs at a time. The Rust child has a
10-second timeout, temporary input/transcript cleanup and a 32 KiB report limit;
an installed binary change makes verification unavailable until service restart.

The response `seedcore.cw-g02.studio-verification.v1` preserves both reports and
their original JSON, trusted expected context, input/retained-bundle hashes,
snapshot digest and retained terminal summary. Only matching verified reports,
correct context/trust and exact retained bytes produce a verified UI outcome.
Disagreement and verifier failure are explicit unverified states. Even harmless
outer JSON reformatting is quarantined by this known-original byte pin while
both standalone CLIs may still verify its signed contents. Refused imported
bytes remain downloadable; no unsigned substitute is labeled verified.

The snapshot is immutable for the service instance. Revocation updates require
explicit operator reprovisioning/restart; the report states the snapshot used,
not live key freshness. An unknown request or another instance cannot acquire
expected context from its uploaded bundle. General historical context lookup
and durable server-side evidence storage remain outside this slice; saved
context plus independently provisioned trust still support the offline CLIs.

UI state is fenced by attempt/instance, candidate/revision/epoch and generation
after each asynchronous read/hash/fetch. Edits, undo/redo, settings, a new attempt
and disposal clear old reports/downloads. A delayed response cannot restore a
verified badge. Both parsed reports are checked against their downloadable JSON
before enabling the report exports.

The local Studio slice passes **14 focused TS checks**, **22 trusted API/config
checks**, and **nine real Chrome groups**. Actual completed/stopped browser
bundles and both downloaded reports match independent CLI executions and native
MuJoCo 3.15.0 replay at `atol=1e-12`, `rtol=0`. Chrome also covers same-attempt
round trips, tampering, wrong attempts, oversized files, safe text, mobile
containment and an edit during delayed verification. The source-built regressions
include 275 workspace TS, 22 authoring API, 46 authoring/replay Chrome checks,
five governed Chrome groups and their existing native checks.

Run the complete local operator lane:

```bash
node tools/robotics/verify-cw-g02.cjs --browser
```

Reports and actual browser exports live under `artifacts/robotics/cw-g02/studio/`:
`browser-verification.json`, `independent-verification.json`, completed/stopped
bundles, admission-context captures, UI/independent verifier reports, native
captures, screenshot and public test trust. The fixture launcher uses explicit
`--evidence` / `--trust-out` flags with temporary test-only keys and context;
normal startup generates neither. This is scoped synthetic acceptance evidence.

## Source verification and remaining exit gates

Run the source-build and API/parity lane without Chrome:

```bash
node tools/robotics/verify-cw-g02.cjs
```

The lane builds the required CW compiler workspaces and independent Rust CW
verifier, runs native/PDP/receipt and API/CLI negative tests, and retains actual
completed/stopped exports plus validly signed gapped and revoked-key refusal
fixtures under `artifacts/robotics/cw-g02/`. The fixture exporter uses temporary
test keys, explicit synthetic registration/delegation and a controlled clock;
real PDP decisions, Rust token checks and native MuJoCo still execute. No private
keys or PolicyCase credentials are exported. CI runs this lane and retains the
public synthetic artifacts, source revision and content hashes.

The 3 November source-built lane passes **111 CW-G02 tests**, including
real-clock same-origin admission/context capture, API download, independent
CLI replay and stricter parser/encoding/clock cases; **139 admission/Fast Spine
regression tests** (two browser-only cases explicitly skipped here); and
**49 Rust verifier/proof/token/type tests**. The 82 fixed canonical vectors run
in both languages. **110 retained cross-language comparisons** agree on
acceptance/disposition/scope, with exact bundle/context/trust/source hashes on
accepted inputs; three additional malformed-file CLI groups reject in both.
Error wording is language-specific and is not an acceptance condition.

The report is `artifacts/robotics/cw-g02/verification.json`. The parity lane requires
`rust_cw_receipt_adapter: true`, `parity_included: true` and records comparison
and canonical-vector counts. `parity/` retains exact input bytes, independently
supplied expected/trust files, both reports and an agreement record per importer
call. `terminal-parity/` and the top-level `*.rust.verification.json` files retain
both verifiers' real completed/stopped/gapped/revoked examples. A disagreement
fails the lane and preserves the reproducer; the runner cannot silently substitute
Python's disposition for Rust's. Normal verification never rewrites input files.

The 36 research/document synchronization tests passed. The authz-graph script
passed 79 focused tests; its separate live phase could not connect to
`127.0.0.1:8002`. This is not recorded as a live-phase pass.

The `--browser` report additionally requires `studio_browser_verified: true`,
nine browser checks and two independently checked download cases. The named
local Studio slice is now available for review against
[CW-EVID-01/CW-G02 acceptance](central_world_acceptance_matrix.md). Full package
promotion remains a review decision; general historical context lookup,
physical signer/profile acceptance, production context/deployment and real-policy
execution retain separate gates.
