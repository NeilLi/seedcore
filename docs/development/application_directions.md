# Application Directions

Date: 2026-08-20
Status: Canonical application portfolio and sequencing map

SeedCore is a trust runtime, not a collection of unrelated vertical products.
The current application work is organized as one authority-bearing product
wedge and two bounded expansion tracks that reuse the same trust boundary.

```text
public discovery and presentation
  -> ordinary coordination and commercial intent
  -> accountable ActionIntent
  -> PDP decision
  -> scoped ExecutionToken
  -> physical attempt
  -> evidence, replay, and verifier closure
```

Only the last five stages are authority-bearing SeedCore execution. Search,
recommendation, storytelling, model output, availability, and payment intent
remain context or presentation until an accountable action is separately
admitted.

## Portfolio Decision

| Direction | Portfolio role | Current state | Next promotion gate |
| --- | --- | --- | --- |
| Rare-shoe Restricted Custody Transfer (RCT) | Must-win authority-bearing application | Runtime, proof, NFC simulation, replay, operator baseline, visual schemas, canonical hashes, and 15-case offline fixture matrix implemented | Benchmark same-model/different-pair behavior, then integrate the frozen refs into canonical replay before shadow use |
| Local producer discovery and proof | Bounded adjacent application | Provenance, read-only projection, accessible intake, and public-proof contracts defined; no new production vertical activated | Implement the strict read-only projection and confirmed-draft slice against reviewed fixtures |
| Grounded producer storytelling | Presentation sidecar to producer proof | Text plus existing consented still/audio experiment defined; generated media deferred | Ship only after claim-state projection, consent, citation, staleness, and withdrawal behavior are enforced |
| Sovereign city bootstrap | Active foundation and discovery track | Closed-world fixture, typed models, three-table persistence, isolated PostgreSQL schema-restore/reseed parity, redaction, runtime-profile gate, Haversine discovery, and three REST reads verified under `bootstrap_sim` | Review persistence promotion, then add producer/service flows before any governed city action |

This is a sequencing decision, not a claim that all four rows are independent
products. Rare-shoe RCT remains the commercial proof of governed execution.
Producer and city work expand the discovery, provenance, and operating context
around that proof without becoming authority sources themselves.

## Direction 1: Rare-Shoe RCT

The collectible rare-shoe handoff remains the clearest proof that SeedCore can
bind digital transaction identity to physical scope and replayable custody
evidence.

The active application extension is a static visual-evidence sidecar. It may
produce typed observations such as `MATCH`, `MISMATCH`,
`INSUFFICIENT_COVERAGE`, or `ANOMALY_FLAGGED`, but it cannot mint an
`ExecutionToken`, mutate custody, release quarantine, or close a verifier job.
Raw capture must survive every derivation, and generated pixels are excluded
from forensic evidence.

Read:

- [`rare_shoes_collecting_transfer_demo_spec.md`](rare_shoes_collecting_transfer_demo_spec.md)
- [`rare_shoe_rct_visual_evidence_adapter_v0.md`](rare_shoe_rct_visual_evidence_adapter_v0.md)
- [`virtual_nfc_simulation_plan.md`](virtual_nfc_simulation_plan.md)
- [`hardware_anchored_telemetry_mvp_contract.md`](hardware_anchored_telemetry_mvp_contract.md)

## Direction 2: Local Producer Discovery And Public Proof

The local-producer track tests whether the same provenance and custody
contracts can support agricultural micro-lots, singular artisan goods, and
regional workshop handoffs. It starts with read-only discovery rather than a
marketplace.

The strict first slice is deliberately small:

1. three read-only projection endpoints: query, projection lookup, and anchor
   explanation;
2. three vendor-neutral MCP wrappers over those endpoints;
3. one-image-plus-one-audio draft extraction with explicit producer or operator
   correction and confirmation;
4. one safely escaped, low-bandwidth public proof page; and
5. individually reviewed fixtures, with no automatic activation of a new
   production vertical.

Booking, purchase, release, workshop approval, custody transfer, and
quarantine mutation remain separate governed actions. A QR code is a copyable
identifier, not proof of physical presence.

Read:

- [`local_producer_provenance_and_rct_scenario_expansion.md`](local_producer_provenance_and_rct_scenario_expansion.md)
- [`source_registration_architecture.md`](source_registration_architecture.md)
- [`owner_creator_external_sdk_and_plugin_surface.md`](owner_creator_external_sdk_and_plugin_surface.md)

## Direction 3: Grounded Creative Sidecar

Producer storytelling can make public proof useful and memorable without
blurring claim state. The first experiment is limited to producer-approved,
source-cited story text plus an existing consented still or audio excerpt.

The proof surface must render three distinct regions:

- `Verified Origins` for verifier-backed claims;
- `Producer-Declared Details` for confirmed but unverified statements; and
- `Artisan Story & Lore` for presentation content.

Translation, dramatization, and synthetic media must be disclosed. Source
staleness, revocation, or consent withdrawal must remove dependent story
projections. Generated reels, image-to-video, cloned voice, live personas, AR,
and 3D remain later presentation research and never enter PDP context,
fingerprints, custody evidence, or verifier closure.

The detailed contract lives inside
[`local_producer_provenance_and_rct_scenario_expansion.md`](local_producer_provenance_and_rct_scenario_expansion.md).

## Direction 4: Sovereign Agent-Native City Bootstrap

The city direction supplies a founder-operable foundation for local discovery,
producer and service profiles, ordinary coordination, provider simulation, and
eventual governed physical action. It is a modular bootstrap around SeedCore's
trust slice, not an expansion of the PDP into a city platform.

The implemented bounded slice includes:

- a packaged five-parcel, three-building reference district;
- typed feature, geometry, relationship, and state-axis models;
- public/protected projection and redaction rules;
- `bootstrap_sim` runtime-profile and fixture-identity gates; and
- read-only query, projection, and anchor discovery with pure-Python Haversine
  filtering.

Persistence, MCP distribution, producer/service lifecycle, ordinary
reservations, and governed city actions remain pending. PostGIS, H3, OGC,
IFC/BIM, maps, 3D, payments, logistics, and live provider integrations are
adopted only after a measured need and a reviewed promotion gate.

Read:

- [`agent_native_digital_city_platform.md`](agent_native_digital_city_platform.md)
- [`sovereign_digital_city_bootstrap_plan.md`](sovereign_digital_city_bootstrap_plan.md)
- [`sovereign_city_foundations_and_infrastructure.md`](sovereign_city_foundations_and_infrastructure.md)

## How The Tracks Converge

The producer and city tracks can share public-safe projections, source
registration, service profiles, and discovery adapters. They do not share
ambient execution authority.

```text
city foundation fixture/live adapter
  -> public-safe place and service projection
  -> producer source registration and confirmed profile
  -> read-only agent/web discovery
  -> optional grounded story presentation
  -> ordinary reservation or commercial intent
  -> named high-consequence action only
  -> Agent Action Gateway / PDP / ExecutionToken
  -> actuator evidence / RESULT_VERIFIER / replay
```

The state boundaries stay explicit:

```text
relevant != available != commercially accepted != policy-admitted
policy-admitted != physically attempted != verifier-closed
```

## Promotion Rules

An application direction advances only when all applicable conditions are met:

1. its contracts and negative fixtures are versioned;
2. advisory or generated content is separated from admitted facts and evidence;
3. public, protected, and restricted projections are explicit;
4. any governed mutation enters through `ActionIntent` and PDP evaluation;
5. execution requires a scoped, fresh, non-revoked `ExecutionToken`;
6. the actuator emits evidence bound to the admitted action;
7. replay and verifier behavior fail closed; and
8. production, secrets, custody closure, quarantine clearance, and policy
   promotion remain human-reviewed or explicitly policy-admitted.

The active implementation order is maintained in
[`current_next_steps.md`](current_next_steps.md). The underlying gate ownership
is canonical in [`policy_gate_matrix.md`](policy_gate_matrix.md).
