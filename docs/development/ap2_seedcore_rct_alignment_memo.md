# AP2 And SeedCore RCT Alignment Memo

Date: 2026-05-20
Status: Boundary and status memo; not an implementation contract

## Current Judgment

SeedCore should not compete with the Agent Payments Protocol (AP2) as an
agent-payment protocol.

SeedCore should be positioned as an AP2-compatible custody, evidence, and
replay-verification layer for high-value physical transfers.

Short version:

```text
AP2 proves the agent was authorized to pay.
SeedCore proves the paid-for physical transition was authorized, evidenced,
and replay-valid.
```

This memo records the current product and architecture judgment so future
commerce work does not blur payment authorization, custody authorization,
settlement references, physical proof, and legal ownership.

## Why This Memo Exists

The current SeedCore commerce wedge overlaps with AP2 in vocabulary:

- delegated agent intent
- bounded authority
- policy constraints
- cryptographic references
- replay and dispute evidence
- human-present and human-not-present execution modes

That overlap is useful, but it can also create confusion. AP2 is primarily a
financial authorization and payment-governance protocol for agent commerce.
SeedCore's current product wedge is Agent-Governed Restricted Custody Transfer
(RCT): the governed handshake between a digital transaction and a physical
custody transition.

The clean distinction:

- AP2 governs the commercial payment chain.
- SeedCore governs the physical custody and evidence chain.
- A commerce workflow may need both.

## AP2 Owns

AP2 should be treated as the upstream protocol for agent-native payment
authorization.

In an AP2-compatible workflow, AP2 owns or can own:

- user payment intent and spend bounds
- merchant cart commitment
- payment authorization and payment-rail handoff
- human-present versus human-not-present payment authorization posture
- payment-method token references and role segregation
- payment dispute evidence around cart/payment authorization

AP2 mandate vocabulary maps roughly as:

| AP2 artifact | Responsibility |
| --- | --- |
| Intent Mandate | User's bounded commercial delegation before discovery or purchase |
| Cart Mandate | Merchant-signed cart, line items, price, taxes, shipping, and fulfillment commitment |
| Payment Mandate | Minimal payment authorization slice submitted to payment rails |

SeedCore should not reimplement these as its core product.

## SeedCore Owns

SeedCore owns the downstream trust boundary for high-consequence physical
execution.

For RCT, SeedCore owns:

- source registration and authentication state
- delegated custody authority
- policy snapshot and PDP evaluation
- approval envelope and step-up handling
- bounded `ExecutionToken` issuance
- physical scope, zone, custodian, and asset binding
- signed edge telemetry and hardware signer evidence
- evidence bundle construction
- RESULT_VERIFIER quarantine and lockout behavior
- replayable proof surfaces
- custody settlement status in the SeedCore twin/runtime sense

SeedCore settlement in this context means governed state transition settlement,
not payment-rail settlement and not legal title transfer.

## Integration Shape

Recommended integration sequence:

```text
AP2 Intent Mandate
-> AP2 Cart Mandate
-> AP2 Payment Mandate / payment authorization
-> SeedCore Agent Action Gateway
-> SeedCore PDP allow / deny / quarantine / escalate
-> ExecutionToken
-> signed physical telemetry
-> EvidenceBundle / replay bundle
-> verifier outcome / custody settlement
```

SeedCore should preserve AP2 artifacts as references and hashes, not absorb
them as the runtime source of custody truth.

Candidate additive fields for future gateway, evidence, or forensic-block
integration:

- `ap2_intent_mandate_hash`
- `ap2_cart_mandate_hash`
- `ap2_payment_mandate_hash`
- `ap2_mandate_chain_ref`
- `merchant_signature_ref`
- `payment_authorization_ref`
- `payment_rail_ref`

These should be optional bridge fields until an AP2 schema mapping is selected
and contract-tested.

## Rare-Shoe RCT Implication

The collectible rare-shoe demo should keep the current separation:

- marketplace or AP2-like commerce layer supplies listing, quote, order, cart,
  and payment references
- SeedCore registers and authenticates the physical pair before transfer
  authority exists
- buyer-agent intent remains advisory until policy admits it
- SeedCore mints bounded custody authority only after delegation, approval,
  authentication, value, and scope gates pass
- signed NFC, scan, video, weight, or custody telemetry proves the physical
  handoff
- replay verifies that the delivered pair matches the authenticated pair and
  the authorized commerce context

For public positioning:

```text
AP2 can authorize the purchase.
SeedCore verifies that the authenticated physical item moved through the
authorized custody path.
```

## Overlap Map

| AP2 concept | SeedCore nearby concept | Alignment | Distinction |
| --- | --- | --- | --- |
| Intent Mandate | Gateway request, `ActionIntent`, owner delegation, approval envelope | Bounded delegated intent | SeedCore intent is custody/action authority, not payment authorization |
| Cart Mandate | `product_ref`, `quote_ref`, `order_ref`, `declared_value_usd`, `economic_hash` | Commerce state is hash-bound into the workflow | SeedCore does not own merchant cart signing in v0 |
| Payment Mandate | settlement refs, payment refs, closure handoff metadata | Payment state can be referenced for replay | SeedCore does not submit to payment rails in v0 |
| Mandate chaining | canonical request hash, `workflow_join_key`, policy/state/replay hashes | Deterministic audit chain | SeedCore chain currently centers on custody authority and evidence |
| Human-present / not-present | `allow`, `deny`, `quarantine`, `escalate`, step-up review | Same fail-closed autonomy posture | SeedCore step-up is custody/policy review, not payment SCA by itself |
| Secure signing | hardware fingerprint, TPM/KMS posture, signed telemetry | Non-LLM deterministic proof | SeedCore's unique proof is physical closure evidence |

## Non-Goals

This memo does not propose:

- making SeedCore a payment processor
- storing raw cardholder data
- replacing AP2 mandates with SeedCore-native payment mandates
- treating payment success as proof of custody
- treating custody proof as legal title transfer
- making JSON-LD the authoritative runtime contract for policy evaluation
- widening the current RCT wedge into a generic marketplace platform

## Product Language

Preferred language:

- AP2-compatible custody verification
- post-payment physical proof layer
- restricted custody transfer runtime for autonomous commerce
- replay-verifiable physical settlement for high-value goods
- governed bridge between agent commerce and physical custody

Avoid:

- SeedCore is an agent payment protocol
- SeedCore replaces AP2
- SeedCore completes legal ownership transfer
- payment settled, therefore custody is proven
- digital proof page equals physical possession

## Near-Term Documentation Actions

1. Keep `agent_action_gateway_contract.md` as the current SeedCore external
   contract authority.
2. Keep `rare_shoes_collecting_transfer_demo_spec.md` explicit that commercial
   settlement is represented by refs and not executed by SeedCore v0.
3. Add AP2 mandate-reference fields only as optional bridge fields after the
   rare-shoe fixture path is stable.
4. If AP2 integration becomes active, write a separate contract memo mapping
   AP2 mandate hashes into `workflow_join_key`, forensic blocks, evidence
   bundles, and replay materialization.

## Decision

SeedCore should base future autonomous-commerce integrations on AP2 where AP2
is available, but the SeedCore product distinction remains downstream:

```text
payment authorization is not custody authority;
custody authority is not physical proof;
physical proof is only accepted when replay verification holds.
```

