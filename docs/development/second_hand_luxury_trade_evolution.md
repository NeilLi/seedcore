# Second-Hand Luxury Trade Evolution Reference

- **Date:** 2026-07-01
- **Status:** Sidecar reference memo, not an authority-path commitment
- **Scope:** Mapping the Restricted Custody Transfer (RCT) runtime to high-value
  second-hand luxury goods such as watches, bags, and jewelry without changing
  the current convergence path.

---

## Convergence Guardrails

This memo is a vertical reference. It may inform future product packaging,
simulation, fixture design, and partner vocabulary, but it does not add a new
authority path, relax current RCT convergence rules, or promote luxury-specific
telemetry into execution authority.

The live authority spine remains:

```text
AI or operator proposal
  -> accountable Agent
  -> typed ActionIntent
  -> PDP allow/deny/quarantine under pinned policy and fresh context
  -> scoped ExecutionToken only on admitted allow
  -> actuator attempt
  -> signed telemetry, replay, and RESULT_VERIFIER closure
```

Luxury-specific fields such as appraisals, service history, optical
fingerprints, GPS traces, or product-passport identifiers are evidence or
constraints only after they are represented in typed contracts, evaluated by
policy, frozen into token or receipt state where relevant, and closed through
replay/verifier evidence.

Non-goals for this phase:

- no direct model, marketplace, appraisal, RAG, or observability output may mint
  or widen execution authority
- no legal title, payment-release, insurance, or settlement semantics are
  authority-bearing until a separate policy-admitted contract exists
- no luxury vertical work should displace the rare-shoe RCT wedge or Slice 1
  runtime hardening sequence
- no GPS, DPP, service-history, or optical-fingerprint claim should be treated
  as implemented baseline without matching schema, policy, replay, and verifier
  tests

## 1. Commercial Context And Trust Gaps

Second-hand luxury trading (e.g., watches, designer handbags, fine jewelry) represents a high-stakes commercial environment with significant trust vulnerabilities. Unlike standard e-commerce, the transaction lifecycle relies on verifying physical authenticity, custody integrity, and state preservation.

| Luxury Trust Gaps | Sneaker RCT Baseline | Luxury Trade Evolution |
| :--- | :--- | :--- |
| Swapped parts / fraud | Swapped fake shoes, stale grading | Swapped watch movements, hybrid fake-real bags, altered stones |
| High-value transit risk | Low-to-moderate value density | Higher value density and higher custody-loss blast radius |
| Contextual authentication | NFC and visual verification fixtures | Candidate multimodal scans, service history, and manufacturer or repair-shop evidence |

---

## 2. Structural Mapping to SeedCore Invariants

Second-hand luxury trading can reuse the current RCT architecture only by
staying inside the deterministic runtime path:

```text
trade or transit proposal
  -> ActionIntent with existing resource, principal, policy, and context fields
  -> PDP evaluation against policy, delegation, active authz graph, and freshness
  -> ExecutionToken only when policy admits the exact attempt
  -> actuator or operator attempt under frozen scope
  -> signed telemetry, replay bundle, and verifier outcome
```

Key invariants:

1. **AI intent remains advisory.** AI buyer, appraisal, and fraud-review agents
   may propose actions, summarize evidence, or draft candidate `ActionIntent`
   inputs. They never hold execution authority. Authority exists only after PDP
   admission and a scoped `ExecutionToken`.
2. **Custody is distinct from title.** SeedCore can govern physical custody
   movement and evidence integrity. It does not handle legal ownership,
   property-title registration, payment settlement, or insurance adjudication in
   the current RCT baseline.
3. **The PDP stays deterministic.** The PDP evaluates pinned policy snapshots
   and supplied context. RAG, telemetry processing, and appraisal systems may
   assemble or annotate evidence, but they do not become policy databases or
   final authority sources.
4. **Verifier closure decides outcome.** An `ExecutionToken` authorizes an
   attempt. Settlement, quarantine, rejection, or review posture must be derived
   from signed evidence, replay, and the `RESULT_VERIFIER` outcome.

---

## 3. Candidate Luxury Extensions

The following extensions are candidates for future work. They should be adopted
only as contract-first slices, after the rare-shoe RCT baseline and current
hardening sequence have the required proof surface.

### Candidate A: Dual-Authorization Custody Handoff

High-value custody handoff may eventually require release and receipt
signatures, for example consignor release plus authenticator or vault
ready-to-receive confirmation.

Adoption rule:

- model this first as an approval-envelope or signed-context requirement around
  the existing `ActionIntent`, not as a parallel intent type
- add policy tests proving missing, stale, replayed, or mismatched signatures
  deny or quarantine and do not mint `ExecutionToken`
- record the signer chain in governed receipts and replay artifacts before any
  operator-facing claim says the feature is supported

### Candidate B: Multi-Hop Transit Constraints

Luxury courier transport may eventually need token constraints for route, time,
handoff zone, lockbox, or custody node. Current `ExecutionToken.constraints` can
carry structured constraint data, but luxury route semantics are not an
implemented typed contract yet.

Adoption rule:

- start with typed fields for zone, handoff location reference, TTL, route
  policy reference, and telemetry evidence refs
- treat Biscuit or Macaroon-style caveat systems as optional hardening beside
  the current `ExecutionToken`, not as a replacement for it
- prove fail-closed behavior for stale telemetry, route mismatch, expired token,
  revoked token, and replay mismatch before invoking payment, settlement, or
  custody closure language

### Candidate C: Product-Passport-Compatible Provenance

Luxury goods may need manufacturer serial hashes, optical fingerprints, repair
shop attestations, appraisal reports, and service-history evidence. The current
SeedCore baseline already has `TrackingEvent`, `SourceRegistration`,
`SourceRegistrationArtifact`, and `SourceRegistrationMeasurement` projections.
Those are the right first integration surface.

Adoption rule:

- map DPP-like evidence into tracking events, artifacts, measurements, and
  registration decisions before considering a new schema
- preserve append-only ingress and replayable provenance
- keep external DPP or GS1 Digital Link compatibility as an export/profile
  concern until a contract and migration plan exists
- require verifier tests for fingerprint mismatch, partial evidence, stale
  service history, wrong asset, and cross-asset replay

---

## 4. Replay And Observability Posture

Luxury trade evidence should eventually be visible through the same replay and
operator surfaces as RCT. That visibility is read-only. It must not become an
authority surface.

Candidate replay views:

- custody timeline across seller, courier, authenticator, vault, and buyer
- source-registration and tracking-event evidence with public-safe redaction
- token constraints, signer provenance, revocation state, and verifier verdict
- operator remediation hints for missing evidence, route mismatch, stale scan,
  owner/delegation mismatch, or quarantine

The Execution Replay Studio remains an advanced forensic viewer over existing
authority-bearing contracts. A luxury-specific view should be treated as future
presentation work until the underlying contracts and verification cases exist.

## 5. Recommended Adoption Sequence

1. Keep the current rare-shoe RCT wedge and Slice 1 runtime hardening as the
   convergence path.
2. Use this memo only to design fixtures and vocabulary for high-value physical
   custody scenarios.
3. If the luxury lane becomes active, implement the smallest contract-first
   slice: dual release/receive evidence on an existing custody handoff.
4. Add policy, replay, and verifier tests before linking any luxury field to
   token minting, custody closure, settlement, or quarantine clearance.
