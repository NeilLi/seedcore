# Immersive Commerce And Governed Agentic Trade Architecture

Date: 2026-08-05  
Status: Product-portfolio architecture and delivery plan  
Related tracks: [`tourist_design_studio_delivery_schedule.md`](tourist_design_studio_delivery_schedule.md), [`rare_shoes_collecting_transfer_demo_spec.md`](rare_shoes_collecting_transfer_demo_spec.md), and [`agent_action_gateway_contract.md`](agent_action_gateway_contract.md)

## 1. Decision

SeedCore should pursue two complementary but independently viable product
tracks:

1. **Immersive Commerce** — a visitor-facing destination-souvenir experience,
   beginning with the Tourist Design Studio and advancing from 2D product
   preview to browser 3D, AR, and only then a venue-hosted spatial experience.
2. **Governed Agentic Trade** — a high-consequence rare-shoe commerce and
   Restricted Custody Transfer (RCT) workflow in which AI may propose actions,
   but only a policy-admitted, scoped, evidence-bound path can execute a
   trade or custody mutation.

They may share brand, visual language, non-sensitive product knowledge, and a
long-term partner narrative. They do **not** share an authorization hot path,
customer data store, checkout system, or deployment boundary by default.

```text
Immersive customer experience             Governed trade execution

Tourist Studio / browser 3D / AR          Trade workspace / operator console
        |                                             |
ordinary consumer commerce                         AI proposes
        |                                             |
payment + print fulfillment                  Agent submits ActionIntent
        |                                             |
consumer support state                       PDP admits or denies
                                                      |
                                              scoped ExecutionToken
                                                      |
                                              custody / edge action
                                                      |
                                              evidence + replay closure
```

The decision protects both products. Tourist creation remains fast, private,
and consumer-legible. Rare-shoe trade retains the narrower, deterministic
authority and forensic posture that differentiates SeedCore.

## 2. Non-Negotiable Authority And Data Boundaries

| Surface | May do | Must not do |
| --- | --- | --- |
| Tourist kiosk, phone, browser 3D, or AR | Let a visitor create, preview, approve, and buy a normal souvenir | Mint authority, transfer custody, trigger trade settlement, or expose another visitor’s data |
| Venue immersive installation | Present a private, time-bounded, supervised exploration of a visitor’s approved design | Be a social world, retain a child’s biometrics, collect payment credentials, or execute a purchase/custody action |
| Trade AI | Prepare listings, compare evidence, recommend prices, draft negotiation or shipping steps, and propose an `ActionIntent` | Approve itself, release a shoe, settle a trade, mutate policy, clear quarantine, or treat a confidence score as authority |
| Trade workspace | Collect human approvals and display bounded action/replay status | Bypass PDP admission, token scope, revocation, evidence, or verifier failure |
| SeedCore RCT runtime | Evaluate the typed trade/custody request and issue a constrained token only when policy admits it | Operate consumer checkout, substitute a customer UI, provide open-ended creative generation, or assert legal ownership transfer in v0 |
| Immersive provenance view | Render a read-only interpretation of existing verified evidence | Become the source of truth or hide a replay/verifier mismatch |

### Data separation

| Data class | System of record | Permitted use |
| --- | --- | --- |
| Tourist drafts, session secrets, purchaser contact, payment/fulfillment state | Tourist Design Studio application | Create and fulfill a souvenir under documented retention rules |
| Aggregate, de-identified studio funnel metrics | Tourist analytics store | Product and venue measurement only |
| Trade intent, approvals, policy result, token reference, custody/telemetry evidence, verifier outcome | SeedCore RCT runtime and its designated stores | Govern, execute, and verify rare-shoe trade/custody operations |
| Approved, replay-derived provenance projection | Read-only trade/proof surface | Customer or operator explanation, never new authority |

Do not copy raw child text, private tourist drafts, payment contact data, or
immersive telemetry into SeedCore merely for analytics. Do not make a virtual
scene, model output, or visually convincing asset evidence for RCT.

## 3. Customer Experiences

### 3.1 Immersive Commerce maturity ladder

| Level | Capability | Commercial purpose | Admission rule |
| --- | --- | --- | --- |
| 0 | 2D exact-product mockup | Prove souvenir desirability and print clarity | Required in the 12-week pilot |
| 1 | Browser 3D turntable of the selected shirt | Improve product confidence | Add only if the pilot shows preview doubt or conversion friction |
| 2 | Mobile AR placement/try-on-style moment | Increase delight or venue engagement | Time-bounded experiment with no extra identity collection |
| 3 | Private venue immersive installation: “walk inside your design” | Test whether immersion lifts paid conversion or return visits | Separate from checkout; parent-supervised where children participate |
| 4 | Read-only rare-shoe provenance journey | Make verified RCT evidence legible to a buyer/operator | Renders evidence already verified by SeedCore; cannot initiate transfer |

Native headset VR, social avatars, persistent worlds, biometric tracking,
voice capture, and cross-visitor interaction are excluded until a specific
venue use case, age policy, retention model, and commercial result justify
them.

The planned next-stage product exploration is broader than a single venue
installation: the **Tourist Journey AI+VR** track may connect anticipation,
arrival, playful destination activities, and post-visit memory or souvenir
fulfillment. Its initial product and Godot runtime plan is
[`godot_agent_operable_xr_runtime_plan.md`](godot_agent_operable_xr_runtime_plan.md).
The track remains staged and evidence-gated; its immersive client is still
separate from checkout and the governed RCT authority path.

### 3.2 Rare-shoe trade workspace

The commercial trade experience begins as a practical operator/buyer workspace,
not a public marketplace. It must show, in plain language:

- shoe identity and asset reference;
- provenance and condition evidence references;
- quote/order context and declared value;
- current custody state and the proposed next action;
- required human approvals and policy result;
- bounded token status when execution is admitted;
- execution receipt, verifier outcome, and a clear exception/remediation path.

AI can assist with preparation and explanation. It cannot make an acceptance,
release, settlement, policy change, or custody conclusion on its own.

## 4. Governed Agentic Trade Flow

The rare-shoe trade lane retains the SeedCore core rule:

```text
AI research/recommendation
  -> accountable trade agent proposes a typed ActionIntent
  -> required human/delegated approvals are resolved
  -> PDP evaluates pinned policy, scope, asset state, and evidence prerequisites
  -> ExecutionToken is minted or withheld
  -> approved fulfillment/custody actuator attempts the bounded mutation
  -> evidence and receipts are recorded
  -> RESULT_VERIFIER / replay closes, rejects, reviews, or quarantines the case
```

### Action classes

| Action | AI role | Authority requirement | Closure evidence |
| --- | --- | --- | --- |
| Draft listing/price recommendation | Advisory | None; a human edits/publishes through a separately governed path | Recommendation provenance only |
| Request quote/order action | Propose typed request | Principal, delegation, quote/order context, policy admission | Policy receipt and request hash |
| Release shoe to courier/next custodian | Propose or route request | Policy-admitted `ExecutionToken`, scoped asset/zone/time, required approvals | Signed edge/NFC/telemetry receipt + custody transition |
| Change custody state | Never self-authorize | Same scoped token and verified preconditions | Replayable evidence bundle + verifier outcome |
| Exception/reprint/quarantine response | Summarize/propose allowed resolution | Explicit operator authority and relevant policy | Operator decision plus exception evidence |
| Policy or graph change | Suggest only | Existing governed mutation/promotion controls; never model authority | Reviewable promotion receipt and tests |

Any deny, expired token, stale evidence, incomplete approval, signature failure,
or verifier mismatch fails closed for the custody action. The UI may explain the
reason, but may not convert it into an implicit override.

## 5. Integration Contracts

The tracks integrate through explicit, versioned contracts—not shared tables or
direct browser calls.

| Contract | Producer | Consumer | Minimum fields | Boundary |
| --- | --- | --- | --- | --- |
| `TouristDesignCompletedV1` | Tourist Studio | Tourist analytics only | venue, kit version, duration bucket, completion outcome | No PII, raw creative text, or artwork asset |
| `TradeProposalV1` | AI-enabled trade workspace | Accountable trade agent | asset/order/quote refs, proposed action, rationale refs, risk flags | Advisory only; not executable |
| `ActionIntentV1` | Accountable agent | SeedCore Agent Action Gateway | principal/delegation, operation, asset scope, TTL, evidence/freshness requirements, request hash | Authority request; PDP input |
| `RCTExecutionReceiptV1` | RCT actuator/edge path | Replay and verification surface | token ref, request hash, asset/custody refs, telemetry/evidence refs, result | Receipt-derived, append-only |
| `VerifiedProvenanceProjectionV1` | Read-only verification surface | Trade/immersive provenance UI | projection ID, verified/rejected/review/quarantine verdict, permitted evidence summary | Presentation only; never source evidence |

`TouristDesignCompletedV1` must not become a trade signal. A tourist’s design
or family activity cannot influence a rare-shoe price, authority decision, or
custody risk score.

## 6. Delivery Plan

### Horizon A — Establish two clear product boundaries (Weeks 1–4)

| Track | Deliverable | Exit condition |
| --- | --- | --- |
| Tourist Studio | Complete Phase 0 partner and product gate in the Tourist Studio schedule | One venue, kit, product, fulfillment route, support and privacy posture are explicit |
| Immersive UX | Create a browser-3D/AR experiment brief; no implementation commitment | A measurable hypothesis names the conversion or trust problem it may solve |
| Rare-shoe RCT | Freeze the operator-facing trade state table and required action classes against the existing gateway/RCT contracts | Each action maps to `ActionIntent`, policy, evidence, and replay requirements |
| Shared architecture | Approve the data/authority boundary in this document | No planned shared database, direct client-to-SeedCore call, or VR authority path |

### Horizon B — Validate the core paths (Weeks 5–12)

| Track | Deliverable | Exit condition |
| --- | --- | --- |
| Tourist Studio | Execute Phases 1–3 of the 12-week pilot plan | Closed-pilot evidence and continue/revise/stop decision |
| Rare-shoe RCT | Run the full quote/order -> policy -> token -> custody -> evidence -> replay flow using fixtures and the existing rare-shoe vertical | Positive and negative cases prove no AI, UI, or stale state bypasses admission/closure |
| Trade UX | Add a read-only proposed-action/replay view to the existing operator surface only when backed by existing verification APIs | Operator can distinguish proposal, pending approval, admitted execution, and terminal verifier outcome |
| Immersive UX | Design-test a non-functional 3D provenance and a non-functional tourist spatial concept | The team has research evidence before building XR runtime features |

### Horizon C — Evidence-gated experience extensions (Weeks 13–20)

| Candidate | Entry requirement | Controlled release | Success / stop rule |
| --- | --- | --- | --- |
| Browser 3D T-shirt preview | Pilot evidence identifies preview confidence as a material funnel issue | A/B or time-bounded cohort; no checkout changes | Retain only if paid conversion/trust improves without harming 5-minute completion |
| Mobile AR | Venue and privacy posture support it; a clear engagement hypothesis exists | Optional phone experience after design approval | Stop if usage is low or adds collection/consent friction |
| Read-only shoe provenance journey | Verified projection contract and replay views are stable | Operator/buyer research cohort | Stop if it obscures exceptions or cannot explain verdicts accurately |
| Agentic trade shadow mode | Trade proposals, policy fixtures, and operational owners are ready | AI proposes; humans execute the same existing governed flow | Promote only if proposal quality and refusal behavior meet review criteria; no direct execution authority |

### Horizon D — Conditional production expansion (after Week 20)

Move only one variable at a time:

1. Tourist Studio: second kit **or** second venue **or** second product.
2. RCT: one named partner integration for rare-shoe trade/custody.
3. Immersive experience: one venue-hosted installation only after it proves a
   commercial role and an operational/age/privacy model.
4. Agentic trade: expand action classes only after shadow/replay evidence,
   policy fixtures, approvals, rollback/exception ownership, and verifier
   coverage exist for the current class.

## 7. Required Acceptance Gates

### Immersive experience gate

- The feature has a single measurable purpose: product confidence, conversion,
  venue engagement, or evidence comprehension.
- It works without biometric, voice, or persistent identity collection.
- It is private by default and supervised/age-bounded when children use it.
- Payment, adult approval, and RCT actions happen in separate conventional UI
  surfaces.
- Abandonment clears local state and does not expose another visitor’s content.

### Agentic trade gate

- The action class has a typed `ActionIntent` schema and a named accountable
  principal.
- Required approvals, asset state, evidence preconditions, TTL, scope, and
  revocation are policy-evaluated before token minting.
- The actuator rejects missing, expired, replayed, or scope-mismatched tokens.
- Receipts and evidence bind to the original request/token/payload hashes.
- Replay/`RESULT_VERIFIER` has fixtures for allow, deny, stale, tamper,
  wrong-asset, missing-approval, and mismatch/quarantine outcomes.
- AI output is logged as an advisory proposal and is never a token, approval,
  policy input, or evidence substitute.

## 8. Product Metrics

| Track | North-star measure | Guardrails |
| --- | --- | --- |
| Tourist Studio | Paid personalized souvenirs per 100 studio starts | <=5 minute preview; <5% fulfillment exceptions; purchaser trust >=4/5 |
| Immersive extension | Incremental lift in the stated conversion/trust objective | No meaningful increase in session duration, abandonment, data collection, or support burden |
| Rare-shoe RCT | Percentage of in-scope custody actions that are policy-admitted and replay-verifiable | Zero bypasses; deny/stale/tamper routes fail closed; exceptions are visible and owned |
| Agentic trade | Useful, review-accepted proposals per reviewed proposal | Zero autonomous trade/custody mutations; no hidden override of policy or verifier verdict |
| Provenance experience | Correct buyer/operator interpretation of verified vs. pending/rejected/quarantined state | Must not overstate provenance, legal ownership, or verifier confidence |

## 9. Decisions Still Required

1. Is the Tourist Studio venue pilot explicitly approved to start Phase 0?
2. Which rare-shoe trade partner or simulated partner owns the first real
   custody/fulfillment integration?
3. Which RCT action class is first for agentic-trade shadow mode: quote
   preparation, courier release request, or exception triage?
4. Is browser 3D for the T-shirt preview a conversion hypothesis, or is it
   merely visual interest? If the latter, do not build it yet.
5. Who owns age policy, attendee supervision, device sanitation, accessibility,
   and content/data retention for a venue spatial installation?
6. Which verified evidence fields may be shown in a buyer-facing provenance
   projection without leaking security-sensitive telemetry or private parties?

## 10. Operating Principle

```text
Make the customer experience magical.
Make consequential trade execution explicit, bounded, and provable.
Never use magic as authority.
```
