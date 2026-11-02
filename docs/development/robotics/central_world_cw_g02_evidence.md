# CW-G02: signed local simulation evidence foundation

Date: 2026-11-02
Status: Python foundation implemented; verification results recorded below; full CW-G02 acceptance remains open
Review scope: CW-G02-PYTHON-FOUNDATION (evidence label, not a PDP deny code)

This implements the bounded [2 November plan](cw_g02_daily_plan_2026_11_02.md)
on the [CW-G01 local native adapter](central_world_cw_g01_admission.md). It adds
host-signed simulation exports and independent offline Python verification.
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

The CLI reads only those local files, emits JSON on stdout and exits zero for
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

It requires contiguous ticks, matching time/count coverage, the pinned controls
and LED cues, finite correctly sized state/pose vectors, body inventory, unit
quaternions and observed positions within admitted limits. Completion requires
all 120 steps and a matching completed terminal state. The accepted interrupted
subset is a nonempty intact prefix stopped by `operator_stop` or
`service_shutdown`; other fenced/fault outcomes remain exportable for inspection
but are quarantined by this foundation. An interrupted run cannot be relabeled
as completed. Imports are bounded to 2 MiB and each artifact to 256 KiB, with
strict duplicate-key/nonfinite/depth checks and no external artifact paths.

## Verification and remaining exit gates

Run the source-build and evidence lane:

```bash
node tools/robotics/verify-cw-g02.cjs
```

The lane builds the required CW compiler workspaces and existing Rust token
verifier, runs native/PDP/receipt and API/CLI negative tests, and retains actual
completed/stopped exports plus validly signed gapped and revoked-key refusal
fixtures under `artifacts/robotics/cw-g02/`. The fixture exporter uses temporary
test keys, explicit synthetic registration/delegation and a controlled clock;
real PDP decisions, Rust token checks and native MuJoCo still execute. No private
keys or PolicyCase credentials are exported. CI runs this lane and retains the
public synthetic artifacts, source revision and content hashes.

Local focused evidence comprises **70 CW-G02 tests**, including real-clock
same-origin admission/context capture, API download and independent CLI replay,
plus **139 admission/Fast Spine regression tests** (two browser-only cases
explicitly skipped in this lane). The report is
`artifacts/robotics/cw-g02/verification.json`; it explicitly records that the
Rust **CW receipt** adapter and CW-G02 browser surface are not included. Existing
Rust token verification is exercised and is a distinct capability.

The 36 research/document synchronization tests passed. The authz-graph script
passed 79 focused tests; its separate live phase could not connect to
`127.0.0.1:8002`. This is not recorded as a live-phase pass.

The additive Rust CW receipt adapter and Python/Rust disposition parity,
Studio's verification/import UI and real browser-export evidence are the next
bounded slice. Full [CW-EVID-01/CW-G02 acceptance](central_world_acceptance_matrix.md)
stays open until those pass. Physical signer/profile acceptance, production
context/deployment and real-policy execution retain separate gates.
