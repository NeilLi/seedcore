# Rare-Shoe Restricted Custody Transfer Demo Brief

## Why Rare Shoes

Rare shoes are not the market limit. They are the first vivid proof scene.
They expose trust failures that are easy to understand and expensive to
resolve when systems cannot bind intent, authority, custody, and evidence into
one verifiable chain.

SeedCore is not building a sneaker marketplace. The rare-shoe Restricted
Custody Transfer demo proves a broader runtime pattern for high-value physical
asset transfer: authentication, delegated authority, custody telemetry, and
verifier closure must all agree before execution is accepted.

The demo is not a legal title-transfer system. SeedCore governs physical
custody movement under scoped authority and binds the result to replayable
proof. Legal ownership and settlement remain external references or future
integrations.

Rare shoes make these trust failures legible:

- counterfeits
- stale authentication
- swapped physical items
- condition drift
- custody disputes
- NFC cloning
- cross-asset replay
- opaque provenance

## Demo Flow

1. Rare pair is listed and registered as a governed source asset.
2. Authentication evidence, condition grade, provenance, and NFC binding are
   attached.
3. Buyer-side or collector agent submits purchase / transfer intent.
4. Agent intent enters SeedCore through Agent Action Gateway v1.
5. Policy Decision Point checks authentication status, freshness, delegation,
   quote/order binding, asset state, and required evidence.
6. SeedCore mints bounded custody authority only for the exact asset,
   actor/device, zone, and validity window.
7. Vault/courier scan produces signed telemetry.
8. Buyer-side delivery scan produces final signed telemetry.
9. Result verifier validates that the evaluated request, authority token,
   telemetry, and final closure all match.
10. Public proof and operator forensic views are generated.

Key proof:

```text
No AI or buyer-side agent can move custody unless authentication, policy,
authority, telemetry, and closure evidence all match.
```

## Toxic Path Testing

The demo includes successful and adversarial paths to prove fail-closed
behavior under realistic attack and error conditions:

- NFC clone / hardware tamper violation
- cross-asset replay attempt
- stale or delayed telemetry
- missing approval envelope
- condition drift
- authentication mismatch

Expected behavior:

- invalid or stale authentication denies or quarantines
- missing delegation or approval denies
- cross-asset replay denies and preserves product/order/quote/workflow context
- invalid NFC challenge, tamper state, or signer proof fails closed
- stale telemetry quarantines unless it satisfies the delayed-telemetry policy
- public proof publication halts when authority-tier fields are present

## Public Proof And Operator Forensics

The proof surface uses two different views.

Public proof is intentionally narrow:

- product identity
- provenance class
- high-level authentication verdict
- condition grade summary
- current custody state
- current risk state
- public proof hash
- forensic video proof ref and video hash
- replay reference or verification URL

Operator forensics is rich:

- full custody chain
- policy decisions and reason codes
- approval envelope and signer provenance
- telemetry refs
- authentication payload summary
- raw NFC / challenge-response details where authorized
- quarantine or lockout status
- full replay bundle

Sensitive data such as raw telemetry, raw NFC UID, unredacted microscopic
evidence, signer key refs, approval envelope internals, device attestation
details, and operator-only reason traces must stay out of the public
projection.

## Thirty-Day Verticalization Checklist

Completed or underway:

- final investor application copy
- one-page SeedCore overview
- rare-shoe fixture directory
- `CollectibleShoeRegistration` read model
- rare-shoe gateway adapter
- proof-path tests:
  - happy path closure
  - NFC clone / tamper violation
  - cross-asset replay attempt
  - delayed telemetry policy
- `rare_shoe_happy_path_replay_bundle.json`
- public/operator proof redaction mapping

Remaining packaging work:

- README section for Rare-Shoe RCT demo
- five-minute demo walkthrough recording
- five-slide architecture / investor deck
- first customer discovery list and interview script

## Positioning

Rare-shoe RCT is not a sneaker demo. It is a compact proof that SeedCore can
govern high-value physical asset transfer when authentication, delegated
authority, custody movement, and replayable evidence must all agree before
execution.

The same runtime pattern can extend to luxury goods, logistics, robotics
handoff, industrial asset custody, lab samples, and regulated physical
workflows.
