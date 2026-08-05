# Tourist Design Studio Delivery Schedule

Date: 2026-08-05  
Status: Working delivery plan for the product-pivot discovery and pilot track  
Companion: [`tourist_design_studio_pilot_design.md`](tourist_design_studio_pilot_design.md)

## 1. Decision And Planning Boundary

This plan operationalizes the proposed Tourist Design Studio pilot. It does
**not** change the active SeedCore Restricted Custody Transfer (RCT) roadmap,
and it does not put the SeedCore PDP, `ExecutionToken`, custody graph, or
replay runtime on the visitor creation or checkout path.

The team is making one bounded commercial bet:

```text
At one venue, can visitors create and buy a private, destination-specific
T-shirt in five minutes or less, and can the venue fulfill it reliably?
```

The plan is therefore a 12-week discovery-to-closed-pilot sequence, not a
commitment to a multi-venue commerce platform. A failed exit gate stops or
re-scopes the track; it must not be solved by adding products, VR, social
features, or platform complexity.

## 2. Working Assumptions

Calendar dates assume kickoff on **Monday, 2026-08-10**. If the partner or
fulfillment contract is delayed, shift the calendar; do not compress the exit
criteria.

| Decision | Planning default | Owner to confirm by Phase 0 exit |
| --- | --- | --- |
| Pilot venue | One museum, zoo, or resort gift shop with visitor dwell time | Commercial lead + venue partner |
| Product | One adult/youth T-shirt blank; limited colors and sizes | Product + fulfillment lead |
| Fulfillment promise | One route only: venue pickup when reliable, otherwise shipping | Fulfillment lead |
| Audience | Family co-creation; children approximately 6–12 are co-creators, never default purchasers | Product + privacy lead |
| Design input | Approved kit selections, short text, and playful structured controls | Design lead |
| Commercial model | Per-item margin or revenue share | Commercial lead + venue partner |
| Pilot volume | 50 completed designs; evaluate paid conversion only after operational readiness | Product lead |

The pilot begins only after the venue rights, support responsibilities,
fulfillment promise, and local legal/privacy review are written down. The
application does not collect a child account, photo, voice, precise location,
or full name in the pilot.

## 3. Product And Technical Scope

### 3.1 Pilot vertical slice

```text
Venue landing -> destination kit -> starter layout -> structured personalization
-> up to 3 safe variants -> remix -> print-valid product preview
-> purchaser phone handoff -> adult approval -> payment
-> one fulfillment path -> purchaser status + venue exception queue
```

Included implementation surfaces:

| Surface | Minimum capability |
| --- | --- |
| Shared kiosk / phone | Start or resume a private session, select a kit, create and revise artwork, show a product preview |
| Purchaser phone | Expiring QR handoff, design approval, checkout, pickup/shipping selection, receipt and status link |
| Application API | Session/version lifecycle, kit selection, constrained generation, print validation, payment/fulfillment orchestration |
| Venue console | Today’s paid/production/ready/exception queue; lookup by short order code; daily funnel summary |
| Partner adapters | One payment provider and one fulfillment path, each isolated behind an adapter |

Explicit exclusions: multi-venue tenancy UI, generic creator accounts, public
sharing, social features, raw prompt chat, multiple vendors, custom toys,
inventory planning, native VR, headset features, and an integration with the
SeedCore RCT authority runtime.

### 3.2 Application boundary

Create a standalone TypeScript application boundary, proposed as
`apps/tourist_design_studio/`, rather than modifying the legacy hotel simulator
or extending RCT services. The implementation begins only after Phase 0 exit.

| Layer | Pilot responsibility | Must not do |
| --- | --- | --- |
| Web app | Kiosk, phone handoff, purchaser, and operator user interfaces | Hold payment credentials or decide safety/print eligibility |
| API | Authoritative workflow and private session state | Expose model credentials to browsers |
| PostgreSQL | Sessions, versions, approvals, orders, fulfillment states, limited analytics | Store raw card data or unnecessary child inputs |
| Object storage | Private artwork, mockups, production exports | Publicly expose abandoned drafts |
| Worker/queue | Generation, export checks, fulfillment retry, webhook processing | Alter a purchaser-approved design |
| Generation/safety adapter | Kit-bound creation and friendly safe alternatives | Claim rights clearance, exclusivity, or approve orders |
| Print-readiness service | Production export, bounds/DPI/color/margin checks, checksum | Capture payment or silently substitute artwork |

Use a modular monolith for the pilot: one deployable API, one database, one
worker, and narrow adapters. Split services only when pilot evidence shows a
specific scale or reliability need.

### 3.3 Reuse disposition

The existing hotel-simulator work is reference material, not a production
dependency.

| Candidate | Disposition |
| --- | --- |
| Separate print-artwork and garment-mockup idea | Reuse as a product pattern; regenerate and validate exports server-side |
| Wearable UI styling and controlled-choice interactions | Selectively port after accessibility and kiosk-session review |
| Local IndexedDB generated-asset cache | Do not use as an authoritative store; only an optional non-sensitive UI cache |
| Browser-side generation calls and API keys | Do not port |
| Hotel/VR/NPC/digital-twin layers | Do not port |
| SeedCore policy snapshots, custody, and PKG request path | Do not port to visitor commerce hot path |

## 4. Delivery Cadence And Roles

### Weekly cadence

| Ceremony | Cadence | Output |
| --- | --- | --- |
| Pilot stand-up | 15 minutes daily | Blockers, venue readiness, production incidents |
| Product/operations review | Twice weekly | Scope decisions and owner-confirmed exceptions |
| Build review | Weekly | Demonstrable end-to-end slice, not slides |
| Risk review | Weekly from Phase 1 | Safety, privacy, print, payment, and support risks with owners |
| Pilot review | Daily during Phase 3 | Funnel, abandonment, failed generation, fulfillment exceptions, next-day change decision |

### Accountable roles

The same person may hold more than one role in a small team, but accountability
must remain explicit.

| Role | Accountable for |
| --- | --- |
| Product lead | Scope, outcome metrics, exit decisions, acceptance of user flow |
| Technical lead | Architecture, security boundaries, delivery sequencing, release decision |
| Design lead | Kit contract, starter layouts, kiosk/phone usability, accessibility, copy |
| Generation/safety owner | Generation configuration, moderation, blocked-request behavior, model evaluation |
| Fulfillment lead | Blank/profile data, export test, vendor contract, reprint/refund workflow |
| Privacy/legal reviewer | Child/family data posture, notices, consent, retention, consumer/purchase terms |
| Venue operator | Placement, staff readiness, pickup/customer support, daily review participation |
| QA/release owner | Test fixtures, negative-path checks, pilot sign-off evidence |

## 5. Twelve-Week Schedule

### Phase 0 — Partner, product, and contract discovery

**Dates:** 2026-08-10 to 2026-08-23  
**Objective:** prove the pilot is legally, operationally, and commercially
specific enough to build.

| Week | Work | Deliverables | Exit evidence |
| --- | --- | --- | --- |
| 1: Aug 10–16 | Confirm one venue, product blank, fulfillment candidate, venue placement, commercial model, and support boundaries. Prototype the five-minute flow and test it with 5–10 representative visitors/families. | Signed pilot-scope draft; venue/fulfillment responsibility matrix; prototype findings; first kit inventory. | Named decision-makers agree who owns pickup, refunds, reprints, and uncollected inventory. |
| 2: Aug 17–23 | Freeze v0 kit and product-profile contracts. Complete jurisdiction-specific privacy, payment, tax, returns, and consumer-disclosure review. Define pricing hypothesis and telemetry schema. | Approved kit v0; product profile v0; data map/retention schedule; reviewed copy; measurement plan; runbook outline. | One approved kit, one fulfillment route, one supported geography, and reviewed terms/notices. |

**Phase 0 hard gate — build only when all are true**

- One venue partner has granted written rights to its name, assets, and brand
  motifs for the stated dates and products.
- A named party accepts every support state: payment failure, vendor rejection,
  damaged/wrong item, reprint, refund, uncollected pickup.
- The team chooses exactly one fulfillment promise.
- The pilot can avoid child accounts, photos, voice, public sharing, and
  behavioral advertising.
- The venue has accepted the pilot pricing hypothesis and the 50-design
  measurement goal.

If the gate fails, continue discovery or stop. Do not write production code in
an attempt to substitute for a missing partner decision.

### Phase 1 — Private creation and print-valid preview

**Dates:** 2026-08-24 to 2026-09-13  
**Objective:** a visitor reaches a private, print-valid T-shirt preview in five
minutes without payment or live fulfillment.

| Week | Work | Deliverables | Exit evidence |
| --- | --- | --- | --- |
| 3: Aug 24–30 | Establish the application skeleton, data model, private session credential, kiosk reset behavior, kit/product read model, and structured-event schema. | Deployed non-production environment; migrations; API contract draft; session-expiry fixtures; venue kit loader. | A new kiosk session cannot read a prior abandoned session. |
| 4: Aug 31–Sep 6 | Build kit selection, starter layouts, structured personalization, version history, undo, and constrained generation request. Implement safe fallback states. | Kiosk/phone creation flow; generation adapter; moderation/alternative response contract; design-version records. | A blocked input returns a safe alternative without showing raw blocked text to the next visitor. |
| 5: Sep 7–13 | Build product mockup, server-side print-readiness checks, production-candidate export, visual preview-to-export comparison, and internal test harness. | Exact product preview; validation results; checksum-linked export; accessibility and responsive pass. | An invalid design cannot reach `ready_for_preview`; a valid test design reaches a print-valid preview in <=5 minutes. |

**Phase 1 acceptance tests**

1. Each session uses an opaque, expiring credential; QR or browser history
   cannot reveal another visitor’s draft.
2. A kit version, product profile, and structured design options are recorded
   for every generated version.
3. Generation runs only from the selected kit and product profile; unbounded
   chat is not available.
4. The export passes bounds, effective resolution, background treatment,
   color/profile warning, text margin/readability, and checksum checks.
5. The preview identifies the same final version and production candidate that
   will later be approved; the client cannot supply its own print asset.
6. The shared device clears or expires a session before a new visitor can use
   it.

### Phase 2 — Purchaser approval, payment, and fulfillment

**Dates:** 2026-09-14 to 2026-10-04  
**Objective:** an approved print-valid version becomes one accurately fulfilled
test product with a recoverable operational exception path.

| Week | Work | Deliverables | Exit evidence |
| --- | --- | --- | --- |
| 6: Sep 14–20 | Add QR purchaser handoff, adult approval record, order draft, selected fulfillment route, and hosted checkout integration. | Expiring handoff link; purchaser flow; approval timestamp/version binding; checkout test mode. | A child/shared kiosk session cannot pay, export, or share without a purchaser session. |
| 7: Sep 21–27 | Implement fulfillment adapter, webhook verification/idempotency, operator queue, order-code lookup, status page, and exception state transitions. | Fulfillment job contract; queue; status mapping; reprint/refund support runbook. | Duplicate or out-of-order vendor webhooks do not create a duplicate print or corrupt the order state. |
| 8: Sep 28–Oct 4 | Run end-to-end synthetic and real test orders; rehearse support workflows; conduct security/privacy/release review; instrument the funnel. | Test-print evidence; daily report; incident runbook; release checklist; staff training pack. | Exact approved export checksum is received by the print provider and correct status reaches both purchaser and operator views. |

**Phase 2 release gate**

- Payment status is confirmed through provider webhook handling, not only
  browser return URLs.
- Every fulfillment submission has payment confirmation, purchaser approval,
  product eligibility, print validation, matching export checksum, and the
  selected delivery details.
- Venue staff can resolve reprint/refund scenarios with only the necessary
  order information; they cannot browse unused drafts or raw child text.
- Monitoring identifies failed generation, failed validation, payment failure,
  rejected vendor job, uncollected pickup, and webhook error separately.
- At least three physical test orders are produced through the intended
  fulfillment route, including one deliberate exception rehearsal.

### Phase 3 — Closed venue pilot and decision

**Dates:** 2026-10-05 to 2026-11-01  
**Objective:** collect enough reliable commercial and operational evidence to
continue, revise, or stop.

| Week | Work | Deliverables | Exit evidence |
| --- | --- | --- | --- |
| 9: Oct 5–11 | Install/verify kiosk or QR entry, brief staff, run soft launch with staff/friends, and correct only launch-blocking issues. | Venue launch checklist; staff quick guide; soft-launch report. | Staff complete lookup, pickup, and exception rehearsal without engineering help. |
| 10: Oct 12–18 | Operate a closed pilot; review funnel and incidents daily; conduct short purchaser interviews. | Daily funnel/exception report; interview notes; prioritized fixes. | No unresolved P0 privacy, payment, cross-session, or fulfillment incident. |
| 11: Oct 19–25 | Continue pilot with a single controlled improvement to the largest funnel bottleneck. Validate pricing, placement, kit clarity, or handoff—not all at once. | Before/after comparison; updated kit or flow version; cohort note. | The change has a named hypothesis and does not break production or comparability. |
| 12: Oct 26–Nov 1 | Close data collection, reconcile orders, capture partner feedback, and hold continue/revise/stop review. | Pilot decision memo; KPI report; fulfillment reconciliation; next-step backlog or closure plan. | 50 completed designs or an explicitly documented traffic shortfall; partner decision recorded. |

## 6. Workstream Backlog And Completion Criteria

### A. Venue kit and content operations

| Priority | Work item | Complete when |
| --- | --- | --- |
| P0 | `VenueKit` schema/versioning | Kit has venue ID, asset refs/rights, product eligibility, locale, styles, prohibited-terms profile, dates, and print profile reference. |
| P0 | Product profile | Blank/style/color/size, print area, price, tax/display copy, and one fulfillment route are machine-readable. |
| P0 | Starter layouts | Three approved, visually distinct compositions work without prompting. |
| P0 | Asset-rights register | Every supplied/derived asset has a source, allowed use, expiry, and owner. |
| P1 | Seasonal kit replacement | A new version can activate without changing historical orders or designs. |

### B. Private session and family experience

| Priority | Work item | Complete when |
| --- | --- | --- |
| P0 | Design session lifecycle | Drafts expire automatically; kiosk reset is tested; no account is required. |
| P0 | QR handoff | One-time/short-lived link resumes only the intended private session and records expiration/revocation. |
| P0 | Purchaser approval | Approval binds an adult/purchaser action to one design version and production candidate. |
| P0 | Data minimization | Contact data is collected only at checkout and only for the selected route. |
| P1 | Purchaser save/download choice | Introduce only after retention, rights, and support policy are reviewed. |

### C. Generation, safety, and print readiness

| Priority | Work item | Complete when |
| --- | --- | --- |
| P0 | Structured generation request | API receives kit/product/options, never an arbitrary client-built system prompt. |
| P0 | Moderation and fallback | Disallowed content does not enter print queue; the visitor sees a positive alternative. |
| P0 | Version ledger | Each design version records kit/version, options, moderation result, asset refs, and creation time. |
| P0 | Print validation | Server validates print area, resolution, alpha/background, color, text, margin, and output checksum. |
| P0 | Preview/export binding | The final approved thumbnail and submitted production export are cryptographically or content-hash linked. |
| P1 | Human quality sampling | Daily pilot review samples outputs for false negative/false positive safety and print issues. |

### D. Commerce and fulfillment

| Priority | Work item | Complete when |
| --- | --- | --- |
| P0 | Hosted payment | Card data never reaches the kiosk/API; server handles provider callbacks and order state. |
| P0 | Fulfillment adapter | Normalizes provider status without allowing the provider response to alter artwork or product selection. |
| P0 | Idempotent webhooks | Provider event ID and order reference prevent duplicate order transitions. |
| P0 | Operator queue | Shows only permitted fields required to action today’s orders and exceptions. |
| P0 | Support runbooks | Operator can perform approved reprint/refund paths with audit notes. |
| P1 | Shipping carrier tracking | Add only if shipping is the chosen pilot route and the provider has a stable integration. |

### E. Measurement and release operations

| Priority | Work item | Complete when |
| --- | --- | --- |
| P0 | Event taxonomy | Events cover start, first draft, print-valid preview, checkout start, paid, fulfillment terminal state, and reason-coded failures. |
| P0 | Privacy-aware analytics | No raw child text, artwork, payment data, or unnecessary identifiers appear in funnel reporting. |
| P0 | Daily report | Report runs without manual spreadsheet reconstruction. |
| P0 | Alerting | Staff receive a usable notification for payment/fulfillment/webhook failures. |
| P1 | Venue comparison | Add only after the first site proves operationally viable. |

## 7. State Model And Test Matrix

The production state model remains intentionally small:

```text
draft -> ready_for_preview -> awaiting_purchaser -> checkout_started -> paid
  -> in_production -> ready_for_pickup | shipped

needs_revision, refunded, and reprint_required are controlled exception states.
```

| Risk | Required automated test before pilot | Required operational rehearsal |
| --- | --- | --- |
| Cross-visitor access | Expired, guessed, and replayed session/QR credentials are denied | Abandoned kiosk is reset before next visitor |
| Child purchase/sharing | Shared session cannot invoke checkout, export, or sharing | Parent completes handoff on phone |
| Unsafe request | Blocked content gets a friendly alternate response and no raw prompt is rendered | Safety owner reviews a sampled event |
| Non-printable output | Validation failure blocks preview approval and checkout | Staff understand revision explanation |
| Preview mismatch | Submitted export checksum equals approved candidate checksum | Physical print compared with approval image |
| Payment failure | No fulfillment job is created | Purchaser retry/abandon behavior is clear |
| Webhook duplication/order | Duplicate/out-of-order event leaves one correct order state | Vendor status outage and recovery are rehearsed |
| Print rejection | Order becomes `reprint_required` and no automatic substitution occurs | Operator follows a named resolution path |
| Excess staff access | Queue/API omit unused drafts, raw prompts, and nonessential contact data | Staff sign in under least-privilege role |

## 8. Metrics, Thresholds, And Decision Rules

### Pilot dashboard

| Metric | Target | Trigger if missed |
| --- | --- | --- |
| Start -> first draft | >= 70% | Simplify first screen, starter choices, or kiosk instruction |
| First draft -> print-valid preview | >= 60% | Improve kit, generation constraints, or validation feedback |
| Preview -> checkout start | >= 30% | Investigate desirability, price, mockup clarity, or handoff friction |
| Checkout start -> paid | >= 70% | Investigate payment/device handoff and price disclosure |
| Start -> paid | 15–25% | Assess commercial viability only after sufficient traffic |
| Median time to print-valid preview | <= 5 minutes | Remove choices/latency; do not add features |
| Fulfillment exception rate | < 5% | Pause expansion and fix production/support path |
| Parent/purchaser trust rating | >= 4/5 | Review consent, privacy copy, approval, and fulfillment clarity |

### Continue / revise / stop rule

| Outcome | Decision |
| --- | --- |
| Targets broadly met, no severe privacy/security incident, venue wants continuation | Continue to a second controlled cohort or limited duration extension; keep one product/vendor while fixing the largest bottleneck. |
| Visitors enjoy creation but conversion/fulfillment misses one threshold | Revise one variable at a time—kit, price, placement, handoff, or fulfillment promise—and run a bounded follow-up cohort. |
| Repeated fulfillment failure, missing partner ownership, material privacy/safety failure, or persistent low intent | Stop the pilot, close/retain data according to policy, reconcile orders, and document the learning. Do not mask failure through feature expansion. |

## 9. Risk Register

| Risk | Leading signal | Mitigation | Stop/escation owner |
| --- | --- | --- | --- |
| Venue rights unclear | Asset list lacks source/expiry | Freeze kit, obtain written rights, replace assets | Commercial lead |
| Design feels generic | Low preview or checkout rate; interview feedback | Improve venue-specific starter compositions, not prompt freedom | Product/design lead |
| Generation latency | Preview >5 minutes | Fewer variants, precomputed assets, async job status, retries | Technical lead |
| Unsafe/age-inappropriate result | Moderation event or staff report | Block, offer approved alternative, sample outputs, fix rules | Safety owner |
| Print mismatch | Validation/export/physical-print comparison fails | Block order, improve export pipeline, reprint from approved candidate only | Fulfillment lead |
| Payment/handoff abandonment | Checkout-start to paid <70% | Clarify QR transition and price; test purchaser phone flow | Product lead |
| Staff support burden | Queue exceptions or staff questions rise | Simplify statuses/runbook; retrain before adding functionality | Venue operator |
| Data over-collection | New field lacks fulfillment purpose | Remove field; update data map/review | Privacy lead |
| Scope dilution | Requests for VR, toys, marketplace, or multi-venue portal | Record as post-pilot backlog; do not pull into sprint | Product lead |

## 10. Decision Log Required Before Build

Record each answer in the pilot repository or partner operating agreement by
the Phase 0 exit. An unanswered item is a build blocker, not a TODO.

1. Named venue and physical kiosk/QR placement.
2. Pilot geography and applicable privacy, consumer, tax, return, and payment
   review owner.
3. T-shirt blank, print method, print area, product price, and size/color set.
4. Venue pickup **or** shipment, including lead time and uncollected-item
   policy.
5. Asset/license terms, kit owner, and seasonal expiry dates.
6. Generation provider, moderation policy, sample-output review cadence, and
   data-use terms.
7. Payment provider and merchant-of-record model.
8. Fulfillment provider and webhook/status contract.
9. Support/refund/reprint owner, contact path, and service hours.
10. Retention/deletion periods for abandoned drafts, approved artwork, order
    data, production files, and aggregated safety events.
11. Pilot price hypothesis, revenue share/margin, and the decision-maker for
    continuation.

## 11. Handoff Artifacts

Each phase produces durable artifacts so the pilot can be operated by the venue
and evaluated without reconstructing history manually.

| Phase | Required artifact |
| --- | --- |
| 0 | Signed scope, responsibility matrix, kit/product contracts, data map, reviewed disclosures, research notes |
| 1 | API/UI contract, state diagram, threat/negative-test matrix, print validation fixtures, accessibility review |
| 2 | Payment/fulfillment test evidence, webhook fixture set, staff runbook, release checklist, dashboard definition |
| 3 | Daily funnel and exception reports, reconciliation report, purchaser research summary, partner decision memo |

## 12. Post-Pilot Expansion Rules

Do not add a category, venue, vendor, social/sharing surface, account system,
or spatial experience merely because the pilot ships. Consider a next step only
when the pilot decision memo names a specific bottleneck or opportunity and
shows the required evidence. For the shared portfolio boundary with governed
rare-shoe trade, use
[`immersive_commerce_and_governed_trade_architecture.md`](immersive_commerce_and_governed_trade_architecture.md).

The expansion order remains:

```text
Reliable T-shirt conversion and fulfillment
  -> second kit or controlled second cohort
  -> second product or second venue (one variable at a time)
  -> mobile AR / simple 3D preview only if it improves conversion
  -> venue immersive installation only if it has a measured commercial role
```

SeedCore’s transferable lessons for this track are limited to explicit approval,
versioned configurations, clear exception states, tested negative paths, and
operator legibility. The Tourist Design Studio should remain an independent
consumer-commerce application until there is a separately justified,
high-consequence execution boundary that warrants SeedCore integration.
