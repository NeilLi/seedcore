# Tourist Design Studio Pilot Design

Date: 2026-08-04  
Status: Proposed product-pivot design; not yet a replacement for the current
Restricted Custody Transfer roadmap

## Purpose

Define the smallest commercial product that lets a tourist create a
destination-specific souvenir, preview it on a real product, pay for it, and
receive it through a venue or fulfillment partner.

The product is intentionally consumer-legible and operationally narrow. It is
not a generic AI design platform, a social network, a marketplace, or a VR
world. Kids and families are important users, but the business is a
**B2B2C tourist-merchandising product**: a venue or destination partner offers
visitors a private co-creation experience that increases engagement and
merchandise conversion.

The first commercial question is:

```text
Will a visitor pay for a personalized destination souvenir that they create in
five minutes or less, and can a venue fulfill it reliably?
```

## Product Thesis

```text
Turn a tourist's memory into a souvenir they helped create.
```

The studio gives visitors a constrained, playful creative loop:

```text
choose a destination kit
  -> choose a product and design starting point
  -> personalize with a memory, name, date, or playful choices
  -> receive safe design variants
  -> remix the preferred variant
  -> preview on the product
  -> parent or purchaser approves and pays
  -> venue pickup or shipping
```

The first product should be a T-shirt. It has familiar sizing, high perceived
value, broad appeal across adults and children, and well-understood
print-on-demand fulfillment. Stickers, tote bags, plush toys, figurines, and
VR/3D experiences are follow-on formats, not pilot requirements.

## Product Decision

### Recommended pilot shape

| Dimension | Pilot decision |
| --- | --- |
| Customer | One tourist venue, attraction, resort, museum, zoo, airport shop, or destination retailer |
| End user | Tourist, family, or child co-creating with a parent/guardian |
| Product | One printable T-shirt style, with a small size/color range |
| Design source | A venue-licensed destination kit plus constrained AI-assisted personalization |
| Sales surface | Venue tablet/kiosk plus QR handoff to the visitor's phone |
| Fulfillment | One print/venue fulfillment partner; local pickup or shipment, not both unless both are already supported |
| Commercial model | Per-item revenue share or software + transaction fee, agreed before the pilot |
| Pilot volume | 50 completed designs; 15–25% design-to-paid-order conversion target |

### Explicit non-goals

Do not build these before the pilot validates demand and operations:

- a global consumer marketplace;
- public profiles, feeds, comments, direct messages, or child-to-stranger
  interaction;
- open-ended image generation without destination or product constraints;
- multiple venues, multiple print vendors, or a generic seller portal;
- custom toy manufacturing, 3D printing, or inventory planning;
- a native VR application or virtual social world;
- enterprise custody, hardware attestation, blockchain, or a generalized trust
  runtime.

## Users And Jobs To Be Done

### Visitor or family purchaser

They want a souvenir that feels personal, is easy to make, and is visibly tied
to their trip.

Primary jobs:

- make a memorable keepsake while the travel moment is fresh;
- create something a child can proudly contribute to;
- see exactly what will be printed before paying;
- receive the item without confusing staff interaction or delayed uncertainty.

### Child co-creator

The child is a creative participant, not an account holder or purchaser by
default.

Primary jobs:

- make choices that visibly change the design;
- feel ownership: “I made this”;
- create safely without needing to understand prompting, copyright, payment,
  or shipping.

### Parent or guardian

They want control over expense, sharing, personal information, and the final
item without turning the activity into an administrative task.

Primary jobs:

- approve the final design and any use of name/photo/voice;
- control shipping/contact details and payment;
- prevent accidental public sharing or purchases;
- understand what data is retained after the visit.

### Venue operator

They want higher merchandise conversion and a differentiating visitor
experience that does not create a support burden.

Primary jobs:

- offer only approved destination branding and motifs;
- see order status and resolve failed prints or pickups;
- obtain a simple conversion and revenue report;
- change a seasonal kit without reengineering the application.

### Fulfillment operator

They need a print-ready order that is accurately scoped to a product blank,
print method, and delivery path.

Primary jobs:

- receive a valid print file and order metadata;
- reject infeasible output before production;
- surface production, pickup, shipment, refund, and reprint states;
- avoid manual interpretation of AI prompts or raw visitor data.

## Pilot Experience

### Entry

The visitor encounters a small sign or kiosk:

```text
Design your own [destination] T-shirt in five minutes.
Make it here. Pick it up later, or send it home.
```

The visitor scans a QR code or starts on the shared venue tablet. The tablet
should be a discovery and creation surface; payment and shipping should move to
the purchaser's phone whenever possible. This reduces kiosk abandonment and
keeps payment credentials off shared hardware.

### Creation flow

1. **Choose a kit.** The visitor selects one of three venue-approved visual
   kits, for example “wildlife explorer,” “local legend,” or “sunset
   adventure.”
2. **Choose a starter.** The visitor sees a small grid of composed starting
   layouts, not a blank canvas or chat prompt.
3. **Personalize.** They choose controlled attributes such as color palette,
   character, activity, trip date, and short text. A child-friendly “make it
   sillier / more magical / more sporty” control is preferred to unrestricted
   text generation.
4. **Generate variants.** The system produces up to three clearly distinct,
   print-safe variants. Each is labeled as a draft, never silently saved as the
   final order artwork.
5. **Remix.** The visitor changes palette, text, graphic placement, or selected
   kit elements. The studio preserves design history so they can undo or return
   to an earlier favorite.
6. **Product preview.** The chosen artwork is composited onto the exact
   T-shirt blank, color, and print area. The UI explains placement and shows
   any print warning before checkout.
7. **Approval and checkout.** The purchaser verifies the final image, product
   options, price, pickup/shipping path, and terms. In family mode, this step
   must be completed by the parent/guardian on the connected phone.
8. **Order and collection.** The visitor receives a concise status card and
   pickup/shipping instructions. The venue staff view only the order reference,
   product, fulfillment status, and permitted contact information.

### Completion states

| State | Meaning | Visitor-facing action |
| --- | --- | --- |
| `draft` | A private design session exists; no product is reserved | Continue or discard |
| `ready_for_preview` | Artwork passed generation and print checks | View product mockup |
| `needs_revision` | The artwork violates a safe-content or print constraint | Use the offered safe revision controls |
| `awaiting_purchaser` | A child/shared-device session needs adult approval | Scan QR and approve on purchaser device |
| `checkout_started` | Product options and payment flow are active | Complete or cancel purchase |
| `paid` | Payment succeeded and an order is created | Follow fulfillment status |
| `in_production` | Fulfillment has accepted the print job | Wait for pickup/shipping update |
| `ready_for_pickup` | Venue can hand over the item | Present order code |
| `shipped` | Carrier handoff is recorded | Track shipment |
| `refunded` / `reprint_required` | An operational exception occurred | Follow venue support instructions |

## Product Surfaces

### 1. Venue landing and kit selection

Required elements:

- venue logo and a single call to action;
- estimated creation time and product starting price;
- three approved destination kits;
- language selector only when a partner can provide reviewed translations;
- QR handoff affordance;
- accessibility controls for text size and contrast.

### 2. Design studio

Required elements:

- starter layout rail;
- approved motif and palette selectors;
- short-text input with length, character, and moderation limits;
- child-friendly creative controls;
- generate/remix control with visible progress and retry limits;
- version thumbnails and undo;
- “start over” that confirms before deleting the session.

The system should frame the assistant as a creative helper, not as a person or
friend. Avoid unbounded conversational framing in the first release.

### 3. Product preview and approval

Required elements:

- front/back product mockups where applicable;
- product color, size, and price;
- print-safe bounding box and warnings;
- final artwork thumbnail and revision link;
- “adult approval required” explanation for family mode;
- a purchaser confirmation screen that clearly separates design approval,
  payment, and sharing/export choices.

### 4. Purchaser phone handoff

Required elements:

- short-lived QR/session link;
- final private preview;
- adult approval, checkout, and fulfillment choice;
- email/phone collection only at this stage and only as necessary for the
  chosen pickup or shipping workflow;
- receipt and order-status link.

### 5. Venue operator console

This is not a full dashboard. It needs only:

- today’s paid/production/ready/exception order queue;
- order lookup by short order code;
- production file/fulfillment reference;
- clear exception reason and allowed resolution steps;
- daily funnel summary: starts, completed designs, checkout starts, paid orders,
  fulfillment exceptions.

It must not expose child session text, unpublished drafts, raw prompts, or more
personal data than staff need to fulfill an order.

## Design System And Creative Constraints

### Destination kit contract

Each venue kit is a versioned, licensed package rather than a bag of arbitrary
AI prompts.

Minimum fields:

```json
{
  "kit_id": "venue:example:summer-2026",
  "venue_id": "venue:example",
  "name": "Sunset Explorer",
  "locale": "en",
  "allowed_products": ["tshirt"],
  "licensed_asset_refs": ["asset:venue:sunbird", "asset:venue:map-outline"],
  "style_rules": {
    "allowed_palettes": ["sunset", "ocean", "forest"],
    "text_max_length": 24,
    "prohibited_terms_profile": "family-safe-v1"
  },
  "print_profile_ref": "print:tshirt:front-a4-v1",
  "active_from": "2026-08-01T00:00:00Z",
  "active_until": "2026-10-31T23:59:59Z"
}
```

The kit contract prevents three common pilot failures:

- unlicensed landmark, mascot, or partner-brand use;
- a generated image that cannot be printed on the selected product;
- inconsistent visual quality across venue installations.

### Generation policy

Generation must be constrained by the selected kit and product profile.

The system may use a model to compose and vary artwork, but it must not:

- generate a recognizable third-party character or logo on request;
- generate sexual, violent, hateful, frightening, or age-inappropriate content;
- use a child's image, voice, or full name without an explicit product decision
  and a reviewed consent path;
- claim that generated art is exclusive, legally cleared, or copyright-free;
- bypass print validation because the image looks attractive in a preview.

When a request cannot be fulfilled, return a positive creative alternative,
for example: “Let’s make an original jungle explorer instead.” Do not show the
rejected text back to nearby kiosk users.

### Print readiness

Before checkout, an artwork export must pass:

- exact product print-area bounds;
- minimum effective resolution and DPI for the print method;
- transparent/background treatment expected by the printer;
- color-profile conversion or printer-supported color warning;
- text readability and margin checks;
- kit/version and artwork checksum linkage;
- final preview-to-export comparison so the produced file matches what was
  approved.

If the export fails, the user returns to `needs_revision`; no order should be
sent to fulfillment.

## Data And Privacy Model

### Principle

Collect the smallest amount of data required to create and fulfill a souvenir.
Design sessions should work without a child account, a public profile, or a
stored travel history.

### Records

| Record | Purpose | Sensitive fields | Retention posture |
| --- | --- | --- | --- |
| `DesignSession` | Temporary creation state and QR handoff | Session secret, selected kit, draft references | Short-lived; automatically expire abandoned sessions |
| `DesignVersion` | Private artwork/version history | Artwork reference, structured options, moderation disposition | Retain only for the order/support window unless purchaser saves it |
| `PurchaserApproval` | Records final creative and order approval | Adult/purchaser identity reference, timestamp | Retain with order record |
| `Order` | Payment and fulfillment orchestration | Contact/delivery reference, product options | Retain per financial and fulfillment obligations |
| `FulfillmentJob` | Print partner handoff/status | Print file reference, order reference | Retain for reprint/support policy |
| `VenueKit` | Licensed creative configuration | Asset rights and expiry metadata | Retain while active plus licensing audit period |
| `SafetyEvent` | Aggregated safety and quality monitoring | Reason code; do not retain raw child text by default | Minimized, access-controlled, time-bounded |

### Family and child posture

- The initial product is private by default.
- A child uses a temporary co-creator session; no child email, direct message,
  public profile, or social graph is required.
- The purchaser/parent controls payment, shipping, downloads, and any sharing.
- Do not use child-generated inputs to train models without an explicit,
  separately reviewed, legally valid consent program.
- Do not add behavioral advertising or third-party tracking to child/family
  creation surfaces.
- Treat photos, voice, precise location, and full names as out of scope for
  the first pilot unless a separate consent, minimization, and deletion design
  has passed legal/privacy review.

This is a product design, not legal advice. A privacy specialist must review
the applicable children's privacy, consumer protection, payment, consumer-data,
and destination-specific rules before an external family pilot launches.

## Technical Architecture

### MVP architecture principle

Use a straightforward application stack. The product needs a fast, resilient
creative workflow and reliable order handoff; it does not need the existing
SeedCore distributed trust runtime in the request path.

```text
Venue tablet or visitor phone
  -> Tourist Design Studio web application
  -> application API
     -> session/design store
     -> destination-kit service
     -> generation and safety adapter
     -> print-readiness service
     -> payment provider
     -> fulfillment-provider adapter
     -> venue operator console
```

### Component responsibilities

| Component | Responsibility | Explicitly does not own |
| --- | --- | --- |
| Web app | Creation UI, previews, QR handoff, purchaser flow | Payment authority, print validation, or safety decision logic |
| Application API | Session lifecycle, design/version orchestration, order state | Model-specific prompts embedded in clients |
| Destination-kit service | Approved assets, style rules, locales, product eligibility | Free-form user artwork ownership claims |
| Generation/safety adapter | Structured generation request, moderation, fallback alternatives | Order creation or fulfillment decisions |
| Print-readiness service | Layout/export validation and production file preparation | Payment capture |
| Payment adapter | Checkout session and payment-status callback | Storing raw payment credentials |
| Fulfillment adapter | Vendor submission, pickup/shipment status normalization | Altering approved artwork |
| Operator console | Minimal order and exception visibility | Access to private, unused drafts or raw child inputs |

### Suggested product entities

```text
Venue
  -> VenueKit (versioned, licensed creative rules)
  -> ProductProfile (blank, price, print area, fulfillment options)

DesignSession
  -> DesignVersion (0..n)
  -> PrintValidationResult (0..n)
  -> PurchaserApproval (0..1)
  -> Order (0..1)
       -> FulfillmentJob (1..n)
```

### Essential APIs

These are product contracts, not an instruction to implement all endpoints
before the pilot UI exists.

- `POST /v1/design-sessions` — start a private session for a venue/kit.
- `GET /v1/design-sessions/{session_id}` — retrieve the current private design
  state with a short-lived session credential.
- `POST /v1/design-sessions/{session_id}/versions` — save structured design
  choices or an approved generated draft.
- `POST /v1/design-sessions/{session_id}/generate` — request a constrained
  variation using the selected kit and product profile.
- `POST /v1/design-versions/{version_id}/validate-print` — run print checks
  and create a production candidate.
- `POST /v1/design-sessions/{session_id}/handoff` — issue a short-lived
  purchaser QR link.
- `POST /v1/purchaser-approvals` — record final design approval before payment.
- `POST /v1/orders/checkout` — begin payment for an approved, print-valid
  version.
- `POST /v1/fulfillment/webhooks` — normalize vendor order status.
- `GET /v1/operator/orders` — limited venue order queue.

## Operational Design

### Venue setup checklist

Before a pilot day, the partner must provide:

- written right to use its name, brand, landmarks, and supplied artwork;
- one approved venue kit with seasonal expiry dates;
- product blank, size chart, price, tax treatment, and pickup promise;
- fulfillment lead time and a named exception owner;
- staff instructions for order lookup, pickup, reprint, and refund escalation;
- a visible customer-support path;
- internet/connectivity fallback: QR continuation on the visitor's own phone.

### Fulfillment contract

The system submits a print job only after all of the following are true:

1. payment is confirmed;
2. a purchaser approved the final version;
3. the selected product profile is eligible for the venue;
4. the production export passed print validation;
5. the submitted file checksum matches the approved production candidate;
6. pickup or shipping details are complete for the chosen path.

### Exception handling

| Exception | System behavior | Owner action |
| --- | --- | --- |
| Generation blocked | Offer safe remixes; preserve no raw blocked text in kiosk UI | None unless persistent false positive |
| Print validation fails | Return to revision before payment | None |
| Payment fails | Keep design for a limited recovery window | Purchaser retries or abandons |
| Print vendor rejects | Set `reprint_required`; do not alter artwork automatically | Operator selects approved resolution path |
| Pickup not collected | Follow venue-defined reminder/retention policy | Venue support |
| Wrong or damaged item | Create support case tied to final approved version and production file | Venue/fulfillment resolution |

## Measurement Plan

### North-star pilot metric

**Paid personalized souvenirs per 100 studio starts.**

This keeps the team accountable to both delight and commercial execution.

### Funnel metrics

| Metric | Pilot target | Why it matters |
| --- | --- | --- |
| Studio start -> first draft | >= 70% | Onboarding and creative clarity |
| First draft -> print-valid preview | >= 60% | Quality of kits and generation controls |
| Preview -> checkout start | >= 30% | Product desirability and pricing |
| Checkout start -> paid order | >= 70% | Checkout/handoff friction |
| Studio start -> paid order | 15–25% | Initial commercial viability |
| Median time to print-valid preview | <= 5 minutes | Tourist attention constraint |
| Fulfillment exception rate | < 5% | Venue operational viability |
| Parent/purchaser trust rating | >= 4/5 | Safety and transparency quality |

### Qualitative research prompts

Ask a small sample of visitors:

- What made this feel like *your* souvenir?
- Where did you hesitate or become confused?
- Would you have bought the standard souvenir instead?
- Did the child feel able to make meaningful choices?
- Did you understand what would be printed and when you would receive it?

Do not treat a high generation count as success. It may mean the controls are
delightful, or it may mean visitors cannot reach a satisfying final design.

## Pilot Acceptance Tests

The pilot is ready only when these flows work end to end:

1. Adult visitor can start, create, validate, pay, and receive a test order.
2. Child/shared-tablet session cannot independently purchase or share a design.
3. QR handoff expires, cannot expose another visitor's design, and resumes the
   correct private session for the purchaser.
4. A blocked request produces a friendly alternative and never reaches the
   print queue.
5. A non-printable design cannot enter checkout until revised.
6. The exact approved version is the exact version submitted to fulfillment.
7. A fulfillment status change appears in the purchaser and operator views.
8. Venue staff can resolve a reprint/refund case without access to unrelated
   visitor drafts or excess personal data.
9. The app remains usable when a shared kiosk is abandoned: the next visitor
   cannot inspect the previous session.
10. The team can produce the daily funnel and exception report without manual
    spreadsheet reconstruction.

## Delivery Sequence

### Phase 0: Partner and product discovery (Weeks 1–2)

- choose one pilot venue and one T-shirt fulfillment route;
- secure asset/brand usage rights and agree on customer-support ownership;
- test the five-minute creation flow with clickable prototypes and 5–10
  representative visitors/families;
- write the kit and product-profile contracts;
- complete privacy, payments, and consumer-disclosure review before collecting
  live visitor data.

Exit: one signed pilot scope, one approved design kit, one product profile, and
one measurable funnel.

### Phase 1: Private creation and preview (Weeks 3–5)

- implement session, kit selection, constrained personalization, design
  versions, generation adapter, and product mockup;
- implement core safety handling and print-validation prototype;
- run internal staff/family tests with synthetic orders;
- verify shared-device session isolation and QR handoff.

Exit: a visitor can reach a private, print-valid T-shirt preview in five
minutes without payment or live fulfillment.

### Phase 2: Approval, payment, and fulfillment (Weeks 6–8)

- add purchaser phone handoff and adult approval;
- integrate one checkout provider and one fulfillment path;
- add operator order queue and status webhook normalization;
- run end-to-end test orders through actual printing or a realistic vendor
  sandbox.

Exit: approved artwork becomes one accurately fulfilled test product, with
operator-visible status and a recoverable exception path.

### Phase 3: Closed venue pilot (Weeks 9–12)

- deploy at one venue for a time-bounded pilot;
- instrument the funnel and collect short purchaser interviews;
- run daily review of conversion, abandonment, safety events, and fulfillment
  exceptions;
- decide whether to iterate on kit quality, pricing, handoff, or venue
  placement before expanding product categories.

Exit: 50 completed designs, enough paid orders to judge conversion, and a
written partner decision to continue, revise, or stop.

## VR And 3D Direction

VR is an experience-extension decision, not the company foundation.

Only consider a spatial feature after the T-shirt pilot proves both visitor
desire and reliable fulfillment. The recommended order is:

1. 2D product preview and simple 3D turntable on the web;
2. mobile AR or browser-based “place your souvenir in the world” experience;
3. venue-hosted, non-social immersive “walk inside your design” installation;
4. only then, evaluate a headset-native experience for a compatible age band
   and venue operating model.

Any immersive experience must remain private by default, parent-supervised for
children, time-bounded, and separate from checkout. It should increase delight
and conversion; it must not become an expensive standalone world before the
core souvenir business works.

## Relationship To Existing SeedCore Work

This design deliberately does **not** place the present SeedCore PDP,
`ExecutionToken`, custody, edge telemetry, or replay stack on the tourist
creation hot path. Those systems solve a different high-consequence problem and
would slow an early consumer-commerce pilot.

The transferable product lessons are modest:

- explicit adult approval before consequential actions such as payment, export,
  or public sharing;
- versioned, attributable design and product configuration;
- clear operator states and exceptions;
- testable negative paths, especially unsafe content, abandoned kiosks, invalid
  print exports, and fulfillment mismatches;
- AI as a constrained creative collaborator, not an opaque authority.

If this pivot is selected after partner discovery, update the development-docs
index and current-plan documents in one intentional documentation migration.
Until then, this file is the single proposed product design and does not claim
to supersede the existing RCT roadmap.

## Decisions Needed Before Implementation

1. Which initial venue category and named design partner are in scope?
2. Is the first fulfillment promise venue pickup, shipping, or both?
3. Which geography is the pilot in, so privacy, tax, returns, and payment
   requirements can be reviewed correctly?
4. What age range is deliberately supported in the first family experience?
5. Which generation provider, moderation approach, and asset license terms are
   acceptable to the venue?
6. Who owns customer support, refunds, reprints, and uncollected inventory?
7. What commercial model is being tested: revenue share, per-item margin, or
   venue software fee?

Do not begin a multi-venue build, toy-manufacturing program, or VR development
until the answers are explicit and the one-location / one-product pilot has
evidence of demand.
