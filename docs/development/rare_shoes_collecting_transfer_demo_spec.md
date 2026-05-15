# Collectible Rare-Shoe Restricted Custody Transfer Demo Spec

Date: 2026-05-15  
Status: Working development spec for a commercial-grade RCT vertical scene

## Purpose

This document translates the collectible rare-shoe trading research into a
SeedCore-native implementation plan.

The goal is not to build a generic sneaker marketplace, a digital collectible
exchange, or a digital-twin app. The goal is to show that SeedCore can govern
a high-value physical collectible transfer where:

- provenance and authentication are registered before trading authority exists
- AI collector intent remains advisory until policy admits it
- custody movement is explicitly delegated, scoped, time-bounded, and
  replay-verifiable
- physical evidence proves that the delivered pair is the authenticated pair

This is a specialized **Restricted Custody Transfer** scene. It reuses the
current SeedCore trust runtime rather than creating a parallel product stack.

This demo is not about sneakers. It is a compact commercial scene for proving
that SeedCore can govern high-value physical asset movement when AI intent,
authentication, delegated authority, and physical telemetry must agree before
custody changes.

Rare shoes are useful because the trust failures are obvious: counterfeits,
stale authentication, swapped items, condition drift, replay attacks, and
opaque custody. If SeedCore can govern this flow, the same pattern extends to
luxury collectibles, robotics handoff, insured logistics, industrial parts, lab
samples, and regulated physical assets.

The public proof strategy should avoid ownership-claim language that could be
confused with AI-era digital abstractions or speculative claims. For this demo,
the preferred public artifact is a **published forensic video proof**: a
hash-bound video or clip package showing registration, scan, handoff, or
delivery evidence, linked to the replay bundle and governed receipts.

The video proof is evidence, not authority. SeedCore authorizes custody through
policy, delegated authority, scoped execution authority, and signed telemetry. The
published forensic video helps humans inspect the proof chain without treating
any digital artifact as proof of physical possession by itself.

## Commercial Thesis

High-value collectible shoes have three trust gaps that normal commerce systems
do not close:

1. The listed item and the physical item can diverge.
2. Authentication can be opaque, stale, or detached from custody.
3. A buyer-side or seller-side agent can express intent faster than the
   physical evidence chain can prove admissibility.

SeedCore's role is to sit between AI-visible intent and physical execution. It
does not decide taste, price, or market demand. It decides whether a proposed
trade and custody movement is admissible under policy, delegated authority, and
evidence.

Commercial one-liner:

```text
SeedCore governs high-value collectible transfers by binding authentication,
custody, and settlement intent into one replayable proof chain.
```

Demo frame:

```text
AI intent is not execution authority.
Authentication is not custody.
Custody is not settlement.
Settlement intent is not proof.
SeedCore binds them into one governed chain.
```

For investors and partners, rare shoes should be described as the first
commercial-grade vertical scene, not the whole company:

```text
SeedCore governs high-value physical transfers where AI intent must be bound to
authentication, delegated authority, physical custody, and replayable evidence.
```

## Actors

The demo uses explicit commercial roles so authority boundaries stay readable.

| Actor | Responsibility |
| --- | --- |
| Seller / consignor | submits the rare pair for registration and sale |
| Authenticator | provides authentication packet, condition grade, and evidence refs |
| Marketplace / listing partner | provides `product_ref`, `quote_ref`, `order_ref`, and listing context |
| Buyer | authorizes spend constraints and receives final proof |
| Buyer agent | expresses purchase intent but cannot authorize custody alone |
| Vault / origin custodian | holds the authenticated item before transfer |
| Courier / edge operator | performs scoped physical movement under bounded authority |
| SeedCore operator | monitors PDP outcomes, verification, evidence chain, and proof surfaces |
| Verifier | performs replay and forensic validation, including quarantine outcomes |

## Custody, Settlement, And Ownership

The v0 demo must avoid legal ambiguity by keeping three concepts separate.

| Concept | v0 meaning |
| --- | --- |
| Custody transfer | SeedCore governs physical possession movement under scoped authority |
| Commercial settlement | represented by `quote_ref`, `order_ref`, `declared_value_usd`, and `economic_hash`; not executed by SeedCore v0 |
| Legal ownership | out of scope for v0; represented only as an external reference or future integration |

SeedCore v0 does not assert legal title transfer. It proves that the
authenticated physical asset moved through an authorized custody path under a
specific commercial intent envelope.

## Implementation Stance

The research introduces useful commercial concepts, but the implementation
must be staged against the repo's current runtime.

### Build now

- `TrackingEvent`-first source registration for the shoe pair
- `SourceRegistration` projection for authentication and provenance state
- Agent Action Gateway v1 request for the trade/custody move
- commerce-shaped fields: `product_ref`, `quote_ref`, `order_ref`,
  `declared_value_usd`, `economic_hash`
- signed edge telemetry refs for NFC / scan / weight / custody evidence
- RESULT_VERIFIER fail-closed quarantine and replay verification
- operator and public proof surfaces over the existing verification contracts
- published forensic video proof refs for human-legible public evidence

### Treat as extension interfaces

- microscopic optical authentication providers
- NFC / RFID challenge-response hardware
- Digital Product Passport compatible JSON-LD projection
- GS1 Digital Link style external identifiers
- object storage for high-resolution image and video evidence
- Kafka transport for intent, telemetry, and policy outcome observability

### Treat as future hardening

- SEV-SNP or other TEE confinement for gateway-critical signing
- NGSI-LD context broker synchronization
- consortium-chain publication
- delay-tolerant networking as an edge transport feature
- regulatory-grade external verifier packages

These are valuable, but they should not block the first repo-grade demo.

## Architecture Stack

Rare-shoe RCT is a vertical specialization of the Restricted Custody Transfer
runtime. It binds five normally separate trust domains:

1. Authentication: is this the claimed pair?
2. Provenance: why is this pair valuable and what history is admissible?
3. Commercial intent: which listing, quote, order, and value envelope is this
   transfer tied to?
4. Custody movement: who or what is authorized to move the physical asset,
   through which zones, and during what time window?
5. Replayable proof: can an independent verifier reconstruct the chain from
   registration to delivery without trusting the live request?

The implementation stack should be described as five layers.

| Layer | SeedCore baseline | Rare-shoe specialization |
| --- | --- | --- |
| Source registration | `TrackingEvent` -> `SourceRegistration` projection | shoe identity, seller declaration, authentication evidence, NFC binding, condition state |
| Policy and authority | PKG / PDP hot path / approval envelope | buyer spend limits, seller allowlist, high-value step-up, authentication freshness, stolen/quarantine checks |
| Agent boundary | `seedcore.agent_action_gateway.v1` | collector-agent purchase intent and scoped physical custody transfer |
| Physical evidence | signed edge telemetry refs and closure | NFC challenge response, vault scan, weight/case seal, courier handoff, final buyer scan |
| Proof surface | verification API, replay, forensics, public proof | collectible passport, forensic video proof, authentication verdict, custody chain, settlement status, quarantine runbook |

Kafka, Ray, object storage, TEEs, and context brokers are support planes. They
must not become policy truth.

## Domain Model

### Canonical Identifiers

`workflow_join_key` is the deterministic correlation key for one rare-shoe
custody-transfer workflow. It binds registration, commerce intent, gateway
evaluation, bounded authority, telemetry closure, and verifier replay.

Canonical construction:

```text
workflow_join_key =
  sha256(asset_id + product_ref + quote_ref + order_ref
         + policy_snapshot_ref + authority_window)
```

`authority_window` should normalize `valid_from` and `valid_until` to UTC
before hashing. Implementations may include a version prefix, but the same
inputs must produce the same key across gateway, verifier, and proof surfaces.

### CollectibleShoeRegistration

Use this as the app-facing rare-shoe aggregate. It can be implemented as a
specialized projection over the existing source-registration model first.

Required fields:

| Field | Type | Volatility | Notes |
| --- | --- | --- | --- |
| `asset_id` | string | immutable | SeedCore custody-controlled asset id, e.g. `asset:shoe:player-exclusive-001` |
| `asset_did` | string | immutable | optional DID-style external pointer for passport/proof use |
| `product_ref` | string | immutable | commerce-facing product/listing reference |
| `seller_ref` | string | mutable | current seller or consignor identity |
| `brand_identifier` | string | immutable | brand/manufacturer identifier; GS1-compatible if available |
| `style_code` | string | immutable | public style or model code |
| `sku_serial_hash` | string | immutable | SHA-256 of SKU + serial data; raw serial stays restricted |
| `nfc_uid_hash` | string | immutable | public hash of NFC/RFID UID; raw UID stays authority-tier |
| `hardware_anchor_profile` | object | mutable | dynamic NFC/RFID, tamper-evident, or PUF-backed anchor summary |
| `physical_fingerprint_refs` | array | append-only | refs to optical, material, video, or scan fingerprint evidence |
| `provenance_class` | enum | immutable | `PLAYER_EXCLUSIVE`, `PROTOTYPE_SAMPLE`, `LIMITED_RETAIL_RUN`, `SIGNED_PAIR`, `GENERAL_COLLECTIBLE` |
| `athlete_provenance_refs` | array | append-only | signed references to photos, game/date claims, team/authenticator statements |
| `condition_grade` | object | mutable | numeric grade, grader ref, graded_at, restoration flags |
| `authentication_status` | enum | mutable | `pending`, `approved`, `rejected`, `expired`, `quarantined` |
| `authentication_payload_ref` | string | mutable | pointer to current evidence packet |
| `custody_state` | enum | mutable | current governed custody state |
| `risk_state` | enum | mutable | current risk/security state |
| `policy_snapshot_ref` | string | mutable | snapshot used for latest admissibility decision |
| `registration_decision_ref` | string | mutable | source-registration decision id |
| `workflow_join_key` | string | mutable | correlation key for an active trade/custody workflow |

### ShoeAuthenticationPayload

The authentication result must not collapse into a boolean. Preserve the
evidence packet as an admissibility input.

Required fields:

- `authenticator_ref`
- `authenticator_signature_ref`
- `model_or_method_version`
- `captured_at`
- `confidence_score`
- `threshold`
- `evidence_artifact_refs`
- `microscopic_image_hashes`
- `spatial_fingerprint_hash`
- `condition_observations`
- `nfc_binding`
- `fingerprint_modalities`
- `verdict`
- `explainability_refs`

`verdict` values:

- `authentic`
- `suspect`
- `counterfeit`
- `inconclusive`
- `tamper_detected`

For v0, `evidence_artifact_refs` may point to fixture JSON and image hashes.
The runtime should not require a real external authentication provider to prove
the flow.

### Physical Fingerprinting Stack

Rare-shoe RCT should move from simple identifiers toward unclonable
physical-to-digital bindings. The first implementation can model these as
fixture evidence, then replace fixture producers with real hardware or service
integrations later.

| Modality | Spec field | Use |
| --- | --- | --- |
| Optical microscopic fingerprinting | `microscopic_image_hashes`, `spatial_fingerprint_hash` | captures stitching, glue morphology, leather grain, and localized surface topology |
| Dynamic NFC challenge-response | `nfc_uid_hash`, `challenge_nonce`, `challenge_response_hash`, `cmac_ref` | proves fresh physical presence and prevents replay of a static scan |
| Tamper-evident hardware anchor | `hardware_anchor_profile.tamper_state` | detects tag removal, damaged antenna, or anchor swap |
| PUF-backed hardware anchor | `hardware_anchor_profile.puf_attestation_ref` | binds the scan to unclonable chip-level manufacturing variation |
| Material science marker | `physical_fingerprint_refs` | optional high-value marker such as diamond-dust or molecular tracer evidence |
| Hash-bound forensic video | `forensic_video_proof_ref` | human-legible evidence tied to the same workflow and device signature chain |

For Slice 3, use a dynamic NFC architecture as the default fixture shape. A
commercial implementation can map this to products such as AES-backed dynamic
NFC tags that emit one-time scan messages. Vendor-specific details should stay
behind the fixture or adapter boundary.

Required dynamic NFC fields in edge telemetry:

- `nfc_uid_hash`
- `scan_counter`
- `challenge_nonce`
- `challenge_response_hash`
- `cmac_ref`
- `tamper_state`
- `anchor_profile_ref`

Policy rules:

- static UID equality is never sufficient for custody closure
- challenge-response freshness must be verified for every handoff scan
- scan counters must be monotonic within the fixture evidence stream
- `tamper_state != clear` forces quarantine or isolation
- optical or material fingerprints may strengthen registration, but they do
  not replace scoped custody authority

Hash-bound forensic video requirements:

- video hash is generated at capture time or fixture-ingestion time
- video metadata includes `asset_id`, `workflow_join_key`, `authorized_device_ref`,
  `observed_at`, and `zone_ref`
- clip or derived proof hashes must be linked to the source video hash
- video is accepted as evidence only when its metadata and hashes bind to the
  same workflow as the gateway evaluation and closure telemetry

### Shoe State Model

Keep operational custody state separate from risk/security state. This avoids
overloading one field with both business progress and failure posture.

`custody_state`:

| State | Meaning |
| --- | --- |
| `REGISTRATION_PENDING` | seller declaration exists but source registration is incomplete |
| `AUTHENTICATED_REGISTERED` | provenance and authentication passed registration |
| `VAULTED_SECURE` | shoe is physically held in an approved origin custody zone |
| `PENDING_TRADE_AUTHORITY` | buyer intent exists; authority has not been minted |
| `IN_TRANSIT_BONDED` | scoped courier transfer is active |
| `DELIVERED_OPERATOR_CUSTODY` | delivered to approved buyer or operator-controlled vault |

`risk_state`:

| State | Meaning |
| --- | --- |
| `CLEAR` | no known active trust gap |
| `PENDING_TELEMETRY` | physical scan occurred but signed telemetry has not reached closure |
| `QUARANTINED_ANOMALY` | verifier or policy found a trust gap or contradiction |
| `ISOLATED_SECURITY_EVENT` | hardware anchor or signer-chain attack suspected |
| `LEGAL_LOCK` | external legal or compliance hold blocks transfer |
| `DISPUTED` | seller, buyer, authenticator, or operator dispute blocks transfer |

### Return And Reversal Policy

Returns, buyer rejection, failed delivery acceptance, or post-delivery disputes
must not mutate the original custody workflow backward.

For v0, a return is modeled as a **new Restricted Custody Transfer workflow**
with reversed commercial actors and a new `workflow_join_key`. The original
workflow remains replayable as completed, quarantined, or disputed. Any return
workflow must carry:

- reference to the original `workflow_join_key`
- current condition grade and risk state
- fresh authority window
- fresh approval envelope
- new origin and destination scope
- new edge telemetry closure evidence

This avoids rollback semantics that would weaken forensic replay. Historical
truth stays append-only; remediation and returns are forward-only workflows.

### Digital Product Passport Projection

Expose a DPP-compatible JSON-LD projection as a read/export surface. Do not
make JSON-LD the authoritative runtime contract for policy evaluation.

The runtime source of truth remains:

- source-registration rows and tracking events
- approval envelopes
- Agent Action Gateway request/response records
- governed receipts
- signed telemetry refs
- verifier outcomes

JSON-LD should be used to make the proof portable and interoperable with
collectors, authenticators, marketplaces, insurers, and auditors.

## Access Tiers

The proof surface should expose different detail by role.

| Tier | Access | Contents |
| --- | --- | --- |
| Public proof | unauthenticated or public link | product identity, provenance class, high-level authentication verdict, current business state, narrow proof hash |
| Authenticated business | signed user or partner credential | custody chain, condition grade, listing/quote refs, signed authentication packet summary |
| Authority and verifier | SeedCore operator / verifier / regulated partner | raw telemetry refs, raw NFC UID, challenge-response details, signer provenance, full replay bundle |

This mirrors the existing public proof vs operator forensic split. Sensitive
fields must not leak into the public proof projection.

### Public Proof Redaction Gate

`PUBLIC_PROOF_REDACTION_REQUIRED` is detected before a public proof view is
published. The first implementation should use a static allowlist validator for
the public JSON-LD / proof projection.

Allowed public keys should include only:

- product identity
- provenance class
- high-level authentication verdict
- condition grade summary
- current custody state
- current risk state
- public proof hash
- forensic video proof ref and video hash
- replay reference or verification URL

Forbidden public keys include:

- raw telemetry refs
- raw NFC UID or challenge-response payload
- unredacted microscopic image hashes
- signer key refs
- approval envelope internals
- device attestation details
- operator-only reason traces

If the static projection validator detects a forbidden key, the proof
publication path must return `review_required` with
`PUBLIC_PROOF_REDACTION_REQUIRED`. A later implementation may add an active
verifier step, but v0 should start with deterministic schema/key validation.

## Demo UI Surfaces

The vertical demo should be visually inspectable through three surfaces.

### Collector Proof View

- forensic video proof player or link
- product identity
- provenance class
- authentication verdict
- condition grade summary
- current custody state
- current risk state
- proof hash

### Operator Forensic View

- full custody chain
- policy decisions and reason codes
- approval envelope and signer provenance
- telemetry refs
- authentication payload summary
- quarantine or lockout status

### Replay View

- evaluated gateway request
- bounded custody authority
- origin scan
- delivery scan
- verifier result
- public proof projection
- operator forensic projection

## Happy Path

### Phase 1: Shoe registration

1. Seller submits declaration, listing reference, condition details, and
   provenance references.
2. Ingestion writes governed `TrackingEvent` records first.
3. Authentication evidence is attached as source-registration artifacts.
4. Optional NFC/RFID binding evidence is attached as a measurement/artifact.
5. Policy-backed registration decision marks the shoe
   `AUTHENTICATED_REGISTERED`.
6. Custody state initializes to `VAULTED_SECURE` only after location and
   custodian evidence are present.

### Phase 2: Collector intent

1. Buyer or buyer-side agent submits a purchase / transfer proposal.
2. The proposal is normalized into an Agent Action Gateway v1 request.
3. Owner-context preflight checks buyer delegation, spend limits, marketplace
   scope, and required evidence modalities.
4. Memory may supply advisory context, such as prior seller risk or price
   comparables, but memory cannot authorize the transfer.

### Phase 3: Policy preflight and authority minting

The PDP evaluates:

- active delegation and approval envelope
- authentication status and freshness
- absence of quarantine or legal lock
- product / quote / order binding
- declared value and step-up approvals
- current custody state and expected physical scope
- signed telemetry freshness
- edge device or courier authority

Only after these pass may SeedCore mint bounded custody authority for the exact
asset, zones, courier/device, and validity window.

### Phase 4: Physical handoff

1. Courier or vault edge node presents the scoped authority.
2. Edge scan reads the NFC/RFID anchor or equivalent fixture identifier.
3. Scan telemetry is signed by the authorized device.
4. Weight, seal, box, image, or video refs are attached as supporting evidence.
5. Closure request binds telemetry refs to the original evaluated `asset_id`.
6. Custody state moves to `IN_TRANSIT_BONDED`.

### Phase 5: Delivery and replayable proof

1. Buyer-side receiving scan produces final signed telemetry.
2. Closure aggregates authentication evidence, authority, handoff telemetry,
   and delivery telemetry.
3. RESULT_VERIFIER validates the chain.
4. Public and operator proof surfaces render the final state.
5. Custody resolves to `DELIVERED_OPERATOR_CUSTODY` or quarantines fail-closed.

## Policy Gates

Minimum gates for the first commercial-grade demo:

- `registration_decision_ref` exists and is approved
- `authentication_status == approved`
- authentication evidence is within configured freshness window
- `nfc_uid_hash` or fixture hardware anchor matches the asset
- dynamic NFC challenge-response proof is fresh and bound to the workflow
- tamper-evident anchor state is clear
- asset is not quarantined, stolen, disputed, or locked
- buyer agent has active delegated authority
- approval envelope is present and valid
- high-value threshold triggers step-up or dual approval
- `product_ref`, `quote_ref`, and `order_ref` bind to the same `asset_id`
- telemetry is fresh or explicitly marked delayed with valid signed timestamp
- delayed telemetry is submitted before the maximum delayed-telemetry
  submission window expires
- physical scope matches expected zone / coordinate / custodian
- closure evidence carries the same asset binding as the evaluate request

Delayed telemetry policy:

- `observed_at` must fall inside the bounded authority window
- `submitted_at` must be no more than `24h` after `observed_at` for v0
- payload signature must cover both `observed_at` and `submitted_at`
- payload must preserve the same `asset_id`, `workflow_join_key`,
  `authorized_device_ref`, and edge event nonce
- if `submitted_at - observed_at > 24h`, deny closure with
  `TELEMETRY_SUBMISSION_WINDOW_EXPIRED`

## Bounded Custody Authority

The bounded custody authority is the narrow, replayable permission artifact
for physical movement. It is not legal title and not a settlement instrument.

Minimum fixture shape:

```json
{
  "authority_id": "authority:rare-shoe-rct-001",
  "asset_id": "asset:shoe:player-exclusive-001",
  "workflow_join_key": "sha256:...",
  "product_ref": "marketplace:listing:shoe-001",
  "quote_ref": "quote:shoe-001:2026-05-15",
  "order_ref": "order:shoe-001:buyer-001",
  "authorized_actor_ref": "principal:courier-001",
  "authorized_device_ref": "device:vault-scan-001",
  "origin_zone": "vault_a",
  "destination_zone": "buyer_secure_receiving",
  "valid_from": "2026-05-15T10:00:00Z",
  "valid_until": "2026-05-15T10:30:00Z",
  "allowed_operations": ["SCAN_ORIGIN", "TRANSFER_CUSTODY", "SCAN_DELIVERY"],
  "evidence_requirements": [
    "nfc_challenge_response",
    "signed_origin_scan",
    "signed_delivery_scan"
  ],
  "policy_snapshot_ref": "snapshot:pkg-rare-shoe-rct-v1",
  "approval_envelope_ref": "approval:rare-shoe-transfer-001",
  "signature_ref": "sig:bounded-authority-001"
}
```

## Reason Codes

Use stable reason codes from the first fixture pass so tests, logs, replay, and
operator UI speak one language.

| Reason code | Default outcome | Meaning |
| --- | --- | --- |
| `REGISTRATION_NOT_APPROVED` | `deny` | source registration has not produced an approved decision |
| `AUTHENTICATION_STALE` | `quarantine` | authentication evidence is older than the policy window |
| `AUTHENTICATION_VERDICT_INVALID` | `deny` | authentication verdict is not admissible |
| `ASSET_QUARANTINED` | `deny` | asset has active quarantine or verifier lockout |
| `BUYER_DELEGATION_MISSING` | `deny` | buyer agent lacks active delegated authority |
| `APPROVAL_ENVELOPE_INVALID` | `deny` | approval envelope is missing, inactive, stale, or mismatched |
| `VALUE_STEP_UP_REQUIRED` | `escalate` | declared value requires additional approval |
| `COMMERCE_BINDING_MISMATCH` | `deny` | product, quote, order, or value envelope does not bind to the same asset |
| `HARDWARE_ANCHOR_MISMATCH` | `deny` | NFC/RFID or fixture hardware anchor does not match expected asset |
| `HARDWARE_ANCHOR_TAMPERED` | `quarantine` | tamper-evident anchor reports removal, damage, or irreversible tamper |
| `DYNAMIC_NFC_PROOF_INVALID` | `deny` | dynamic NFC challenge-response, CMAC, or scan counter is invalid |
| `SPATIAL_FINGERPRINT_MISMATCH` | `quarantine` | optical or material fingerprint contradicts the registered baseline |
| `FORENSIC_VIDEO_BINDING_INVALID` | `review_required` | forensic video hash or metadata does not bind to the workflow |
| `TELEMETRY_STALE` | `quarantine` | telemetry is too old for physical-scope validation |
| `TELEMETRY_SUBMISSION_WINDOW_EXPIRED` | `deny` | delayed telemetry arrived after the maximum submission window |
| `TELEMETRY_SIGNATURE_INVALID` | `deny` | telemetry signer or signature validation failed |
| `AUTHORITY_WINDOW_EXPIRED` | `deny` | scan or transfer occurred outside the authority validity window |
| `CROSS_ASSET_REPLAY` | `deny` | valid-looking artifacts were replayed against the wrong asset |
| `CONDITION_DRIFT_DETECTED` | `quarantine` | observed condition materially contradicts registered condition grade |
| `PUBLIC_PROOF_REDACTION_REQUIRED` | `review_required` | public projection contains authority-tier data and must be redacted |

## Toxic Paths

| Case | Trigger | Required outcome |
| --- | --- | --- |
| Authentication mismatch | new optical/auth payload contradicts approved baseline or falls below threshold | `deny`; set `QUARANTINED_ANOMALY`; block new authority |
| Hardware anchor tamper | public UID matches but challenge response, CMAC, tamper state, or signer proof fails | revoke authority; set `ISOLATED_SECURITY_EVENT`; deny closure |
| Spatial fingerprint mismatch | optical, surface topology, material marker, or forensic video metadata contradicts the registered baseline | `quarantine`; require verifier review |
| Stale or missing telemetry | scan evidence is absent or older than allowed | `quarantine`; set `PENDING_TELEMETRY` or `QUARANTINED_ANOMALY` |
| Delayed telemetry | signed scan arrives late but scan timestamp was inside authority window | accept only after signature, timestamp, and max-delay validation |
| Signer-chain violation | revoked key, missing delegation, or insufficient approval quorum | `deny`; no custody mutation |
| Cross-asset replay | quote/order/auth evidence for shoe A reused for shoe B | `deny`; reason code must preserve `product_ref`, `order_ref`, `quote_ref`, and `workflow_join_key` |
| Condition drift | received condition evidence contradicts registered grade materially | `quarantine`; require operator review |

## Fixture Set

Add deterministic fixture payloads before runtime expansion:

1. `clean_rare_shoe_registration.json`
   - approved registration, authentication score above threshold, NFC hash,
     condition grade, provenance refs
2. `authorized_rare_shoe_transfer_intent.json`
   - buyer agent delegation, approval envelope, quote/order/value binding,
     destination scope
3. `rare_shoe_bounded_custody_authority.json`
   - fixture scoped-authority projection with asset, courier/device, time, and
     zone constraints
4. `rare_shoe_edge_telemetry_success.json`
   - signed origin scan, dynamic NFC proof, and custody handoff telemetry
5. `rare_shoe_nfc_clone_attack.json`
   - matching public UID hash with invalid dynamic challenge-response proof
6. `rare_shoe_cross_asset_replay.json`
   - valid-looking commerce refs bound to the wrong shoe asset
7. `rare_shoe_delayed_telemetry.json`
   - delayed but correctly signed scan with original observed timestamp
8. `rare_shoe_delayed_submission_expired.json`
   - scan observed inside the authority window but submitted after the v0
     maximum delayed-telemetry submission window
9. `rare_shoe_forensic_video_proof.json`
   - public-safe video proof projection with source video hash, clip hash,
     redaction status, and replay bundle reference
10. `rare_shoe_happy_path_replay_bundle.json`
   - complete registration, approved authentication, buyer intent, gateway
     decision, bounded custody authority, origin telemetry, delivery telemetry,
     verifier outcome, public proof projection, forensic video proof, and
     operator forensic projection

### Simulated Edge Handoff Fixtures

Slice 3 does not require real NFC hardware. Physical handoff should be
simulated with signed edge telemetry fixtures that behave like real scan events
from the gateway's perspective.

Use two logical fixture devices:

- `device:vault-scan-001` for vault-to-courier origin scan
- `device:buyer-receiver-001` for courier-to-buyer delivery scan

Each simulated scan payload should contain:

- `telemetry_id`
- `asset_id`
- `workflow_join_key`
- `authorized_device_ref`
- `edge_node_ref`
- `observed_at`
- `submitted_at`
- `nonce`
- `scan_kind`
- `zone_ref`
- `nfc_uid_hash`
- `scan_counter`
- `challenge_nonce`
- `challenge_response_hash`
- `cmac_ref`
- `tamper_state`
- `anchor_profile_ref`
- `payload_sha256`
- `signer_key_ref`
- `signature_b64`

For the happy path, generate deterministic fixture signatures or signature
placeholders consistent with the existing signed edge telemetry envelope test
style. The runtime test should validate shape, asset binding,
`workflow_join_key`, timestamp windows, and signer refs. Real cryptographic
hardware can be introduced later behind the same envelope contract.

The NFC clone fixture should keep `nfc_uid_hash` syntactically correct but
change `challenge_response_hash`, `cmac_ref`, `scan_counter`, or
`signature_b64`, forcing `DYNAMIC_NFC_PROOF_INVALID`,
`HARDWARE_ANCHOR_MISMATCH`, or `TELEMETRY_SIGNATURE_INVALID`.

## Test Plan

Recommended test progression:

1. Source-registration projection tests for shoe registration artifacts and
   verdicts.
2. Agent Action Gateway fixture tests for happy path, missing approval,
   stale authentication, hardware mismatch, and cross-asset replay.
3. Closure tests that verify signed telemetry refs are asset-bound.
4. RESULT_VERIFIER tests for quarantine and lockout on replay mismatch.
5. Public/operator surface tests that confirm sensitive fields stay out of
   public proof.
6. Optional Kafka ingress test that wraps the same gateway request in
   `seedcore.intent.delegated.v0`.

The first implementation should mirror the existing commerce drill matrix
rather than creating a separate harness.

## Acceptance Criteria

The rare-shoe RCT slice is acceptable when:

- source registration cannot mark the shoe transferable without approved
  authentication evidence
- the gateway denies or quarantines any trade intent with stale, missing, or
  contradictory authentication state
- the gateway response and forensic linkage preserve `asset_id`, `product_ref`,
  `quote_ref`, `order_ref`, and `workflow_join_key`
- a fixture NFC/edge telemetry success path can close custody for the same
  asset evaluated by the gateway
- a fixture NFC clone/tamper path revokes or blocks authority and produces a
  quarantine/verifier outcome
- dynamic NFC proof checks fail closed when challenge response, CMAC,
  monotonic scan counter, or tamper state is invalid
- forensic video proof is accepted only when hash and metadata bind to the same
  `asset_id`, `workflow_join_key`, and `authorized_device_ref`
- delayed telemetry is accepted only when the original signed observation time
  is inside the authority window and the payload is submitted within the
  maximum delayed-telemetry window
- public proof excludes raw telemetry, raw NFC UID, and unredacted microscopic
  evidence while operator forensics includes them
- public proof includes a hash-bound forensic video proof reference without
  presenting a standalone digital claim as physical custody proof
- offline replay can validate the proof chain without trusting a loose request
  payload
- all tests use deterministic fixtures and stable reason codes

Demo success metrics:

1. No trade authority exists before approved source registration.
2. Buyer agent intent cannot move custody without delegated approval.
3. Commerce refs cannot be reused across assets.
4. Dynamic NFC clone and tamper fixtures fail closed.
5. Delayed telemetry is accepted only if signed observation time falls inside
   the authority window and submission occurs within the v0 maximum delay.
6. Public proof reveals legitimacy without leaking raw authority-tier evidence.
7. Published forensic video proof helps humans inspect the handoff without
   confusing digital artifacts with physical custody.
8. Offline replay validates the full proof chain.

## Implementation Slices

### Slice 0: Contract freeze

- land this spec
- define fixture names and expected reason codes
- introduce a named `CollectibleShoeRegistration` read model for the demo UI,
  implemented initially as a projection over the existing `SourceRegistration`
  and `TrackingEvent` substrate

### Slice 1: Registration fixtures

- add rare-shoe source-registration fixture payloads
- add artifact/measurement types for authentication packet, NFC binding,
  condition grade, and provenance refs
- test projection to an approved registration state

### Slice 2: Gateway adapter

- add a rare-shoe commerce adapter or extend the existing RCT reference adapter
  with `collectible_shoe` fixture inputs
- map listing/quote/order/value into gateway asset and forensic fields
- implement the stable reason-code table in fixture expectations
- add happy-path and deny/quarantine tests

### Slice 3: Edge telemetry closure

- add signed dynamic NFC / scan telemetry fixtures using the existing edge
  telemetry envelope shape
- enforce same-asset binding during closure
- simulate vault-to-courier and courier-to-buyer handoffs with deterministic
  signed scan fixtures rather than real NFC hardware
- add dynamic NFC proof invalid, hardware-anchor tamper, spatial-fingerprint
  mismatch, delayed-telemetry, and delayed-submission-window cases

### Slice 4: Replay verifier and proof surfaces

- add `rare_shoe_happy_path_replay_bundle.json`
- verify the replay bundle outside loose request-payload trust
- add proof/forensic projection fields for shoe registration, authentication
  verdict, condition grade, custody evidence, and forensic video proof refs
- keep public proof narrow and operator proof rich
- add runbook lookup entries for authentication mismatch and hardware anchor
  tamper

### Slice 5: Demo narrative and UI polish

- produce one five-minute demo path:

```text
rare pair listed -> authentication registered -> collector agent requests trade
-> SeedCore admits bounded authority -> vault/courier scan -> delivery scan
-> replayable proof
```

## Non-Traditional Goal

This vertical is not framed as a traditional commerce product. It is a compact
proof that SeedCore can govern high-value physical custody when AI intent,
commercial context, authentication evidence, physical telemetry, and replayable
proof must agree before execution.

The demo should therefore avoid presenting any surrounding surface as the
source of custody truth. Marketplace listings, settlement references, public
proof pages, forensic video, JSON-LD projections, external authentication
systems, hardware fixtures, and infrastructure services are all supporting
inputs or views. The governed runtime remains the authority boundary.

For public understanding, the preferred artifact is a published forensic video
proof linked to replayable receipts, not a standalone digital claim.

## Related Docs

- [`README.md`](README.md)
- [`seedcore_2026_execution_plan.md`](seedcore_2026_execution_plan.md)
- [`agent_action_gateway_contract.md`](agent_action_gateway_contract.md)
- [`source_registration_architecture.md`](source_registration_architecture.md)
- [`trading_memory_admissibility_flow.md`](trading_memory_admissibility_flow.md)
- [`q2_2026_audit_trail_ui_spec.md`](q2_2026_audit_trail_ui_spec.md)
- [`productized_verification_surface_protocol.md`](productized_verification_surface_protocol.md)
- [`edge_telemetry_evidence_closure_draft.md`](edge_telemetry_evidence_closure_draft.md)
