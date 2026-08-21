# AI-Era Journey Digital City: Tourist Demand, Local Business, And Governed Action

Date: 2026-08-21
Status: Active product-experience direction; the Pattaya reference journey is a bounded target, not a production-city claim
Current product center: Agent-Governed Restricted Custody Transfer (RCT), with the journey city as a surrounding discovery and experience layer
Related tracks: [`agent_native_digital_city_platform.md`](agent_native_digital_city_platform.md), [`sovereign_digital_city_bootstrap_plan.md`](sovereign_digital_city_bootstrap_plan.md), [`sovereign_city_foundations_and_infrastructure.md`](sovereign_city_foundations_and_infrastructure.md), and [`local_producer_provenance_and_rct_scenario_expansion.md`](local_producer_provenance_and_rct_scenario_expansion.md)

## 1. Decision And Product Goal

SeedCore should build an **AI-era journey digital city** that helps a visitor
state what they need in natural language and quickly receive a small, feasible,
current, and explainable journey through an unfamiliar city.

Pattaya is the first concrete reference setting. A visitor should be able to
say, for example:

> We have four hours, two adults and one child, a modest budget, one dietary
> restriction, and an interest in local food and handmade souvenirs. We need to
> return to our hotel by 17:00 and prefer little walking.

The system should translate that demand into explicit constraints, ask one
focused question only when a material requirement is missing, and return a
short journey whose places, timing, availability, cost posture, accessibility,
claim state, and uncertainty are visible.

The city grows through two accountable contribution paths:

1. **SeedCore developer/operator growth:** build and improve the shared city
   foundation, public-safe projections, journey engine, visual experience,
   adapters, and governed-action handoff.
2. **Independent-business growth:** local producers and business owners create,
   correct, confirm, operate, suspend, and withdraw their own service profiles
   and bounded service-agent capabilities.

Tourist demand and observed outcomes may identify missing services or product
improvements. They are advisory signals. Analytics, AI suggestions, memory, or
flywheel learning never activate a business, change a verified claim, widen an
agent's delegation, alter ranking policy, or authorize execution by themselves.

The product is not a municipal operating system, generic marketplace, or
tourism chatbot. Its promise is:

> Tell the city what you need. Receive a source-aware journey that fits your
> constraints. Let local businesses participate on their own terms. Route only
> consequential physical actions through SeedCore's governed execution and
> proof runtime.

## 2. Desired Human Outcomes

### 2.1 Tourist outcome

The tourist gets:

- natural-language interaction in a preferred language;
- fast conversion of needs into hard and soft constraints;
- a small number of relevant choices instead of an undifferentiated directory;
- a connected itinerary with time, route, availability, cost, accessibility,
  dietary, family, and transport considerations;
- an explanation of why each stop was selected and which requirements it
  satisfies;
- visible source, freshness, declaration, verification, and uncertainty state;
  and
- safe handoffs for booking, payment, directions, customer-property intake, or
  governed custody where applicable.

"Exact" does not mean that an AI response makes reality true. It means every
material requirement is explicit, every proposed match is traceable to current
source-linked data, conflicts are shown, and unmet constraints are never hidden.

### 2.2 Independent-business outcome

The local producer or business owner gets:

- a low-friction way to become discoverable without learning schemas or agent
  infrastructure;
- ownership of the public profile, service description, hours, availability,
  media consent, and enabled interaction modes;
- direct customer discovery based on actual demand rather than only popularity;
- the ability to correct, pause, revoke, export, or withdraw the profile;
- a clear separation between declared details and verifier-backed claims; and
- access to ordinary coordination and, when justified, SeedCore-governed
  physical handoffs.

The product must not require a business to surrender its customer relationship,
accept opaque ranking, or purchase a trust verdict.

### 2.3 SeedCore outcome

The journey layer makes SeedCore's trust runtime useful and understandable at
the moment a digital recommendation becomes a consequential real-world action.
The city experience distributes the trust slice; it does not expand the PDP
into search, recommendation, storytelling, or ordinary commerce.

## 3. Co-Created City Growth Loop

```text
SeedCore developer/operator
  -> adds reusable city capabilities, curated reference areas, and adapters
  -> publishes public-safe experience and journey surfaces

Independent business owner
  -> submits source-linked media and declared service information
  -> corrects and confirms an expiring draft
  -> enables bounded profile and service-agent capabilities
  -> maintains freshness, consent, availability, and withdrawal

Tourist
  -> expresses current demand and constraints
  -> receives an explainable journey from eligible current projections
  -> visits, coordinates, creates, buys, or requests a governed handoff

Outcomes and corrections
  -> produce advisory product-quality signals
  -> suggest developer or owner improvements
  -> require normal review and confirmation before changing durable state
```

This is a compounding participation loop, not autonomous self-government.

- Developer changes follow normal review, verification, and promotion gates.
- Owner changes remain bound to authenticated ownership, field-level source,
  visibility, consent, and lifecycle rules.
- Tourist behavior may improve retrieval and product design but does not become
  policy, verification truth, or execution authority.
- Paid placement, if ever introduced, must be visibly labelled and cannot
  affect claim state, verifier disposition, or trust ranking.

## 4. Tourist Requirement And Journey Contract

### 4.1 Requirement capture

The journey assistant should convert conversation into a versioned private
request such as:

```json
{
  "query_version": "seedcore.journey_request.v0",
  "city_ref": "reference:th-pattaya",
  "party": {
    "adults": 2,
    "children": 1
  },
  "time_window": {
    "duration_minutes": 240,
    "return_by_local": "17:00"
  },
  "hard_constraints": {
    "dietary": ["shellfish_free"],
    "max_total_budget_thb": 2500,
    "max_walking_distance_meters": 1200
  },
  "preferences": {
    "themes": ["local_food", "handmade_souvenir"],
    "transport": ["walk", "allowlisted_partner_handoff"]
  }
}
```

This request is private journey context, not a public tourist profile and not
PDP authority context.

### 4.2 Precision rules

Every journey result must:

1. distinguish hard constraints from preferences;
2. use only eligible public-safe business and place projections;
3. carry `as_of`, freshness, source, and claim state for material facts;
4. explain which requirement caused each stop to be selected;
5. disclose unresolved conflicts, estimates, and unavailable information;
6. avoid presenting accessibility, dietary suitability, safety, price, hours,
   or availability as guaranteed when they are only declared or inferred;
7. offer a fallback when a stop becomes stale or unavailable; and
8. keep commercial ranking separate from verified claim state.

The first useful answer should require as little interaction as practical, but
the assistant must ask a focused clarification rather than silently inventing a
material constraint.

### 4.3 Four-stage journey arc

```text
1. Demand & anticipation
   -> capture needs, clarify constraints, compare a few journey options

2. Wayfinding & live coordination
   -> follow a curated route, receive freshness-aware updates and fallbacks

3. Participation & making
   -> meet a producer, join a workshop, co-create, reserve, or request service

4. Keepsake & verified closure
   -> receive a souvenir or recap and, when applicable, inspect replayable proof
```

The journey is successful only when the visitor's requirements remain legible
through all four stages. A visually attractive route that violates a hard
constraint is a failed journey.

## 5. Layered Product Architecture

```text
[ Tourist Web / Mobile / QR / Supported Agent Clients ]
                         |
[ Visual Journey Experience And Private Session Assistant ]
                         |
[ Requirement Matching, Route Composition, And Fallbacks ]
                         |
[ Public-Safe Place, Producer, Service, Availability, And Claim Projections ]
                         |
[ City Foundation: Stable Identity, Space, Time, Source, Visibility, History ]
                         |
              ordinary coordination providers
                         |
       named high-consequence action only
                         v
[ SeedCore: ActionIntent -> PDP -> ExecutionToken -> Attempt -> Evidence -> Verifier ]
```

| Layer | Responsibility | Authority posture |
| --- | --- | --- |
| Experience | Illustrated district, cards, chat, itinerary, proof explanation | `PRESENTATION_ONLY` plus cited public projections |
| Journey intelligence | Requirement parsing, matching, route proposals, alternatives | Advisory; cannot mutate business or authority state |
| Business services | Owner-confirmed profiles, declared hours, availability, ordinary coordination | Profile and provider state; not PDP authority |
| City foundation | Stable feature refs, geometry, source, time, visibility, topology, history | Canonical city representation; representation is not authority |
| Trust runtime | Identity, delegation, policy evaluation, scoped execution, evidence, replay | Deterministic, fail-closed authority boundary |

The detailed city-foundation contract remains in
[`sovereign_city_foundations_and_infrastructure.md`](sovereign_city_foundations_and_infrastructure.md).
This document owns the experience above it, not the foundation below it.

## 6. Business-Owned Service Profiles And DIY Agents

### 6.1 Assisted onboarding

The five-minute onboarding goal is a usability target for creating and
confirming a useful public draft. It is not a promise that media can establish
identity, certification, origin, current price, inventory, accessibility, or
execution authority.

```text
one image + one local-language audio clip, with optional additional media
  -> expiring extraction draft
  -> sources, confidence, missing fields, and conflicts
  -> owner correction and explicit confirmation
  -> ACTIVE_READ profile
  -> separately enabled service capabilities and provider connections
```

Candidate draft fields include:

- public display name, story, service category, and languages;
- declared hours, seasonal availability, approximate price posture, and
  workshop capacity;
- public/coarse location plus separately protected exact site refs;
- accessibility, dietary, family, cancellation, and support information;
- media consent and withdrawal state;
- **declared claim candidates** for later source registration; and
- preferred conversational style.

Extraction never creates a verified claim. The claim path remains:

```text
declared candidate
  -> owner correction and confirmation
  -> source-linked registration
  -> deterministic registration decision
  -> current public-safe claim projection
```

### 6.2 Profile and capability lifecycle

```text
DRAFT -> CONFIRMED -> ACTIVE_READ -> ACTIVE_SERVICE
   |          |             |              |
   +--------> ARCHIVED      SUSPENDED <----+
                                  |
                               REVOKED
```

- `ACTIVE_READ` means the confirmed public projection is discoverable.
- `ACTIVE_SERVICE` means configured service integrations may accept ordinary
  requests or prepare proposals.
- Neither state grants execution authority.
- Governed actions still require current owner delegation, an accountable
  principal, PDP admission, a scoped `ExecutionToken`, actuator evidence, and
  verifier closure.

The initial deployment should use one hosted, versioned REST/MCP service with a
business or profile reference. It should not expose an independently operated
public MCP server for every business before authentication, lifecycle,
revocation, observability, and support are proven.

### 6.3 Bounded capabilities

| Capability | Agent behavior | Boundary |
| --- | --- | --- |
| Concierge | Answer source-grounded questions and translate | Read-only; show source and freshness |
| Journey participant | Explain why the business fits a request | Advisory; cannot alter ranking or requirements |
| Workshop coordinator | Check availability and request a bounded hold | Ordinary provider state; expiry and owner terms apply |
| Design assistant | Help compose a souvenir or service request | Generated artifact remains presentation content |
| Quote preparer | Prepare an itemized draft | Cannot settle payment or change owner-approved rules |
| Proof explainer | Explain current claim and verifier state | Cannot issue, upgrade, or clear a trust verdict |
| Custody proposer | Create a named `ActionIntent` proposal | Cannot mint a token, actuate, or close evidence |

## 7. Visual And Interaction Direction

The experience should feel warm, local, and legible rather than like a generic
GIS console.

The Pattaya pilot begins with:

- responsive HTML and SVG proof and journey cards;
- an illustrated 2D district or neighborhood view;
- a small number of clearly connected stops;
- visible time, budget, distance, freshness, and requirement-fit indicators;
- grounded producer stories and consented media; and
- an obvious transition from advisory discovery to external or governed action.

Progressive visual fidelity is allowed only after the basic journey works:

```text
Level 0: low-bandwidth proof and itinerary
Level 1: illustrated 2D district and interactive business cards
Level 2: optional tactile 3D product or workshop preview
Level 3: optional supervised spatial or XR scene
```

Generated images, 3D models, stories, reels, and spatial scenes are labelled
`PRESENTATION_ONLY`. They do not fill evidence gaps, prove origin, establish
accessibility, or participate in visual fingerprints, PDP context, custody
evidence, or verifier closure.

## 8. API, MCP, And Agent Distribution

The first MCP surface should reuse the same read service as REST and the web
experience:

```text
seedcore.discovery.search
seedcore.discovery.get_projection
seedcore.discovery.explain_claim_state
```

Later journey-specific candidates may include:

```text
seedcore.city.plan_journey
seedcore.city.get_journey_update
seedcore.city.chat_concierge
```

These remain thin, vendor-neutral adapters. They do not accept free-form SQL,
expose protected exact location without purpose-bound access, silently change
from read to write, or provide a generic `city.execute` tool.

## 9. Risk Tiers And Consequential Handoff

| Class | Example | Runtime posture |
| --- | --- | --- |
| `READ_PUBLIC` | Search, inspect a profile, explain a claim | Read-scoped REST/MCP; no `ExecutionToken` |
| `DRAFT_PRIVATE` | Capture journey needs, extract a business draft, compose a quote | Private expiring state; explicit confirmation before durable writes |
| `ORDINARY_EXTERNAL` | Request a workshop hold, open directions, ordinary checkout | Responsible provider auth and terms; not SeedCore custody proof |
| `GOVERNED_DIGITAL` | Change an authority-bearing registration or delegation | `ActionIntent` through the existing PDP/token/receipt path |
| `GOVERNED_PHYSICAL` | Release a controlled batch, transfer a valuable artifact, accept or return customer property | Named RCT profile with evidence and replay closure |
| `REMEDIATION` | Revoke compromised authority or clear quarantine | Human-reviewed or separately policy-admitted |

A price threshold alone does not determine the class. Asset, custody, owner
delegation, regulation, reversibility, required evidence, and policy profile
must determine whether an action enters RCT.

Visual comparison may support a separately benchmarked evidence contract for a
specific task. A visual `MATCH` never proves general craft authenticity, origin,
legal ownership, or custody and never authorizes or closes a transition alone.

## 10. Privacy, Family, And Fairness Boundaries

- Journey requests are private, purpose-bound, and retained only as long as the
  user permits or the service needs to complete the session.
- Do not build persistent child profiles, publish child activity, or use child
  media or journey history for training without separate explicit consent.
- Adult approval for production or payment must occur through an independent,
  attributable confirmation rather than a child's chat session.
- Precise homes, workshops, storage sites, vulnerable facilities, and current
  tourist location remain protected unless a purpose-bound projection permits
  disclosure.
- Accessibility, dietary, opening-hours, price, safety, and availability data
  carry source and freshness; declarations are not guarantees.
- Businesses can inspect, correct, pause, export, and withdraw their profiles
  and consented media.
- Recommendation reasons and sponsored placement are legible. Payment cannot
  purchase a verified claim or conceal a better constraint match.

## 11. First Pattaya Reference Journey

The first bounded pilot is one curated Pattaya-area journey, using fixture or
explicitly consented data until live-provider promotion is reviewed.

### V0 scope

- one illustrated reference area rather than a citywide map;
- three to five representative independent businesses or fixture profiles;
- one demand scenario combining local food, a maker experience, and a keepsake;
- one owner-confirmed onboarding and correction flow;
- one shared web/REST/MCP discovery and concierge surface;
- one deterministic ordinary reservation or workshop-hold provider;
- one customer-property or high-value artisan handoff mapped to the existing
  RCT runtime; and
- one low-bandwidth itinerary/proof experience with fallback behavior.

No live Pattaya merchant, address, schedule, price, accessibility attribute, or
origin claim is presented as current until it has an admitted source, consent,
visibility, `as_of`, expiry, and correction path.

### Pilot measurements

Establish a baseline before freezing thresholds for:

- time to first usable journey;
- hard-constraint satisfaction and visible violation rate;
- proportion of recommendations with current source-linked material facts;
- owner onboarding completion time and correction rate;
- journey fallback success when a stop becomes stale or unavailable;
- discovery-to-contact, visit, or reservation conversion for participating
  businesses, with privacy-preserving measurement; and
- replay and verifier closure for the single governed handoff.

These are product-quality signals, not authority inputs.

## 12. Delivery Order And Current Status

### Foundation baseline: partially implemented, promotion pending

- Implemented: five-parcel, three-building reference fixture; typed feature,
  geometry, relationship, and state-axis models; public/protected projections;
  `bootstrap_sim` isolation; read-only REST discovery.
- Implemented but awaiting review: PostgreSQL persistence and operational
  promotion described in [`current_next_steps.md`](current_next_steps.md).
- Pending: MCP parity, producer/service profiles, journey matching, merchant
  studio, visual Pattaya experience, ordinary providers, and governed city
  handoff.

### Delivery sequence

```text
C1b persistence review
  -> C2 public-safe producer/service profiles and read-only MCP parity
  -> Pattaya demand-to-journey reference experience
  -> owner-controlled service capabilities and ordinary provider simulation
  -> one named RCT handoff with replay closure
  -> measured visual, merchant, area, and provider expansion
```

Do not make city-scale GIS, PostGIS, H3, a tile farm, per-business infrastructure,
payments, logistics, 3D, or XR prerequisites for validating the first journey.

## 13. Document Ownership

- This document owns tourist outcomes, co-created growth, requirement matching,
  journey experience, business participation, Pattaya pilot scope, and product
  measurements.
- [`sovereign_city_foundations_and_infrastructure.md`](sovereign_city_foundations_and_infrastructure.md)
  owns spatial, temporal, topology, storage, infrastructure, and twin contracts.
- [`sovereign_digital_city_bootstrap_plan.md`](sovereign_digital_city_bootstrap_plan.md)
  owns the founder-operable topology, modules, simulators, delivery slices, and
  acceptance gates.
- [`agent_native_digital_city_platform.md`](agent_native_digital_city_platform.md)
  owns the long-range ecosystem planes, authority taxonomy, federation, and
  promotion gates.
- [`current_next_steps.md`](current_next_steps.md) owns the active execution
  queue.

## 14. Final Invariant

```text
The tourist's demand shapes the journey.
The business owner controls the service profile.
The developer grows the shared city capability.
Sources and freshness bound what the experience may claim.
AI proposes and explains; it does not create authority.
The PDP admits only named consequential actions.
Evidence and verification close the physical loop.
```
