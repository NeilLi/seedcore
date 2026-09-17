# Edge-Hub Trust Loop Architecture for AI-Era Automated Trade

**Date:** 2026-07-03
**Status:** Sidecar architecture sketch / future feature reference
**Scope:** A strategic topology for combining edge-trust devices, SeedCore PDP
gating, scoped `ExecutionToken` semantics, signed telemetry, replay, and
operator-facing trust projections for high-consequence trade workflows.

This document is not an implementation commitment and does not change the
current SeedCore authority path. It is a reference sketch for future physical /
digital trade surfaces that must still be promoted through contract-first
models, fixtures, tests, policy gates, verifier closure, and replay evidence.

## 1. North-Star Constraint

AI intent must not become execution authority.

In AI-era trade, agents may propose high-value actions such as custody transfer,
physical release, settlement preparation, repair dispatch, data licensing, or
asset registration. Those proposals remain advisory until an accountable Agent
turns them into a typed `ActionIntent`, the PDP admits the request, a scoped
`ExecutionToken` is issued, an executor consumes that token, and evidence closes
through replay / `RESULT_VERIFIER`.

The durable split is:

1. **Intent generation, planning, and negotiation:** advisory only.
2. **Policy and capability gating:** authoritative only after PDP evaluation
   over typed contracts and sufficient context.
3. **Actuation and telemetry:** executor-bound behavior plus signed evidence.
4. **Replay and verification:** closure, quarantine, or failure projection.

Edge hardware can strengthen evidence and local execution binding. It does not
replace the PDP, widen an `ExecutionToken`, clear quarantine, or prove legal
title by itself.

## 2. Sidecar Topology

```text
  +----------------------------------------------------------+
  |                    HUB / CONTROL PLANE                   |
  |                                                          |
  |  typed ActionIntent                                      |
  |        |                                                 |
  |        v                                                 |
  |  Stateless PDP + active authz graph + context checks     |
  |        |                                                 |
  |        v                                                 |
  |  allow / deny / quarantine / scoped ExecutionToken        |
  +--------+-------------------------------------------------+
           |
           | short-lived, attenuated token
           v
  +----------------------------------------------------------+
  |                    USER / OPERATOR EDGE NODE             |
  |                                                          |
  |  enrolled device identity + signer ref                   |
  |        |                                                 |
  |        v                                                 |
  |  local executor / actuator checks token binding          |
  |        |                                                 |
  |        v                                                 |
  |  signed telemetry refs + evidence bundle material        |
  +--------+-------------------------------------------------+
           |
           | replayable evidence
           v
  +----------------------------------------------------------+
  |                    VERIFICATION / REPLAY PLANE           |
  |                                                          |
  |  replay chain + RESULT_VERIFIER + TrustPage projection   |
  |  signed TrustCertificate where current replay contracts  |
  |  support it                                             |
  +----------------------------------------------------------+
```

The hub may be deployed centrally, regionally, or as a future distributed
control plane, but the authority semantics remain the same: the active policy
snapshot and PDP decision are the admission point. Distributed deployment must
not mean distributed permission to mint authority outside the promoted PDP /
token path.

## 3. Current Repo Anchors

This sketch should be read against these existing SeedCore surfaces:

- `ActionIntent` and `ExecutionToken` contracts in
  `src/seedcore/models/action_intent.py`.
- Agent Action Gateway / PDP preflight and no-execute behavior in the API
  router and RCT drill tests.
- Fixture-backed edge trust enrollment in
  `src/seedcore/models/edge_trust.py` and
  `src/seedcore/ops/evidence/edge_trust_adapter.py`.
- Signed edge telemetry references in
  `src/seedcore/models/edge_telemetry.py`.
- Evidence bundle closure and signed telemetry references in the RCT
  verification fixtures and tests.
- `RESULT_VERIFIER` and replay / TrustPage / `TrustCertificate` projections in
  `src/seedcore/services/replay_service.py` and the replay router.

These anchors make the sketch plausible, but they do not mean the full Edge-Hub
trade loop is implemented end to end.

## 4. Architectural Pillars

### 4.1 Hardware-Anchored Edge Evidence

Future edge nodes can hold enrolled signer references backed by TPM, HSM, TEE,
Secure Enclave, or a production KMS profile. In the current codebase, this lane
is fixture-backed and includes `software_dev_key`, `tpm`, `kms`, and `tee`
profile vocabulary.

The edge node's job is evidence strengthening:

- bind telemetry to an enrolled `edge_node_ref`;
- produce digest-bound signed telemetry references;
- capture asset, zone, and physical-presence observations;
- preserve counter, nonce, timestamp, and signer metadata for replay.

Edge telemetry is admissible only after it is represented in typed contracts and
accepted by verifier-facing evidence paths. Raw sensor output, AI summaries, or
device-local confidence scores are not authority sources.

### 4.2 PDP And Token Gating Hub

The hub evaluates typed `ActionIntent` envelopes against the active policy /
authorization graph and sufficient context. Its authoritative output is a deny,
quarantine, escalation/manual-review path, or a narrowly scoped
`ExecutionToken`.

For future trade workflows, token scope may include already-used SeedCore
binding concepts such as:

- `valid_until` or TTL;
- expected coordinate / zone binding;
- asset and workflow scope;
- economic hash or transaction fingerprint;
- executor / device binding;
- replay and receipt references.

These fields must be contract-backed before they are treated as enforceable.
The sketch should not be read as adding new request-time token fields merely by
naming them here.

### 4.3 Local Execution With Fail-Closed Posture

An edge executor may consume an `ExecutionToken` locally to operate a lockbox,
robotic handoff, scanner gate, settlement adapter, or database mutation. The
executor must verify token validity, expiry, scope, revocation posture, and
executor/device binding before acting.

Offline behavior should be conservative:

- if token validity or revocation posture cannot be checked, fail closed;
- if telemetry is missing, stale, unsigned, or outside scope, fail closed or
  quarantine;
- buffering signed telemetry for later submission is acceptable, but buffered
  evidence does not retroactively authorize an action that lacked a valid token
  at execution time.

### 4.4 Replay, RESULT_VERIFIER, And Trust Projections

Trade closure belongs to replay and verifier surfaces, not to the model or edge
node. The verifier reads governed receipts, evidence bundles, signed telemetry
references, replay records, and policy decision material to produce a closure
status.

Use repo-native terms carefully:

- `EvidenceBundle` is the trade / execution evidence closure surface.
- `RAGTrace` and `RAGReceipt` belong to governed-RAG evidence acquisition and
  should not be reused as generic trade receipts.
- `TrustCertificate` and `TrustPageProjection` are replay-service projections
  over replay records. They can present verifiable claims, trust gaps, and
  authority consistency, but they do not by themselves transfer title, settle
  funds, clear quarantine, or override failed verification.

## 5. Example Lifecycle

1. **Advisory proposal:** An AI buyer agent proposes a luxury-goods trade,
   including asset, price, route, and risk notes. This is not executable.
2. **Typed intent:** The accountable Agent or operator workflow derives an
   `ActionIntent` with principal, workflow, asset, authority scope, telemetry
   requirements, and security-contract references.
3. **PDP preflight:** The hub evaluates policy, authorization graph state,
   context sufficiency, owner/delegation posture, approval state, and
   freshness. The response is allow, deny, quarantine, or escalation.
4. **Scoped token:** On allow, the authority path issues a short-lived
   `ExecutionToken` constrained to the approved asset, workflow, executor,
   coordinate / zone expectation, economic fingerprint, and expiry.
5. **Local actuation:** The enrolled edge executor consumes the token and acts
   only if local checks still match the token and policy posture.
6. **Evidence assembly:** The edge node submits signed telemetry references and
   evidence material, such as NFC counter observation, weight delta, coordinate
   binding, or device signer metadata.
7. **Verifier closure:** Replay / `RESULT_VERIFIER` validates the chain and
   marks the workflow passed, failed, incomplete, quarantined, or blocked.
8. **Trust projection:** A TrustPage or `TrustCertificate` may present a
   redacted, audience-appropriate projection of verifier-backed claims and
   trust gaps.

## 6. Non-Goals And Guardrails

- Do not make edge devices independent authority sources.
- Do not allow an AI agent, prompt profile, retrieval result, or local model to
  mint or widen `ExecutionToken` scope.
- Do not use `RAGTrace` / `RAGReceipt` as generic transaction closure artifacts.
- Do not claim legal settlement, title transfer, or public finality from a
  TrustPage unless a separate promoted settlement/title contract exists.
- Do not let offline buffering become offline authorization.
- Do not treat distributed hub deployment as permission to bypass the active
  PDP, signed policy snapshot, revocation posture, or evidence closure.
- Do not promote fixture-backed edge trust profiles to production hardware
  assurance without key registry, attestation validation, revocation, and
  negative-path tests.

## 7. Promotion Path

The safest path from this sidecar sketch into implementation is:

1. Define a narrow trade-loop contract slice using existing
   `ActionIntent`, `ExecutionToken`, `EvidenceBundle`, signed telemetry refs,
   replay records, and TrustPage / `TrustCertificate` projections.
2. Add fixtures for one domain, such as RCT luxury handoff, with happy path and
   toxic paths for stale telemetry, wrong coordinate, revoked signer, expired
   token, replayed nonce/counter, and mismatched economic hash.
3. Verify that all negative paths deny, quarantine, or fail closed without
   minting authority.
4. Only then consider production edge attestation, distributed hub deployment,
   live hardware roots, or settlement/title integrations.

For now, keep this document as a sidecar strategy reference. The current main
development path remains the SeedCore authority spine:

`ActionIntent -> PDP -> ExecutionToken -> executor / HAL -> evidence closure -> replay / RESULT_VERIFIER`.
