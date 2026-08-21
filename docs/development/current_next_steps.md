# Current Next Steps

Date: 2026-08-20
Status: Canonical active execution queue

SeedCore has one must-win authority-bearing application and a bounded
foundation track:

- **Product center:** rare-shoe Restricted Custody Transfer (RCT), including
  replayable physical and visual evidence.
- **Application expansion:** local producer discovery, confirmed provenance,
  public proof, and grounded storytelling.
- **Foundation:** sovereign city fixtures and discovery under
  `bootstrap_sim`, promoted toward governed actions only after explicit gates.

The portfolio and boundaries are defined in
[`application_directions.md`](application_directions.md). This page tracks only
work that is current. Historical status has moved to
[`archive/historical/development_status_log_through_2026-08-17.md`](archive/historical/development_status_log_through_2026-08-17.md).

## Current Baseline

The repository already has:

- Agent Action Gateway v1, stateless PDP evaluation, active authorization graph
  checks, scoped `ExecutionToken`s, revocation, evidence bundles, replay, and
  `RESULT_VERIFIER` integration;
- a host-verified RCT workflow with queue, review, replay, runbook, and asset
  forensics surfaces;
- deterministic dynamic-NFC happy-path and negative fixtures for rare-shoe RCT;
- strict visual-observation/comparison/replay contracts, canonical binding
  hashes, and a deterministic 15-case visual fixture matrix that never grants
  authority;
- an immutable policy-anchor slice that fails closed on unadmitted AI-origin
  authorization graph inputs; and
- a bounded city-discovery slice with a packaged reference district, typed
  models, redaction, `bootstrap_sim` gating, Haversine filtering, and three
  read-only REST surfaces; plus the three-table C1b migration, explicit
  PostgreSQL repository, and fixture/PostgreSQL parity contract.

## Execution Order

### 1. Keep The Trust Spine Green

Before expanding an application surface:

1. run the focused authorization-graph and Q2 verification gates;
2. preserve fail-closed behavior for missing authority, stale context,
   revocation, quarantine, and evidence mismatch;
3. keep model, memory, retrieval, flywheel, discovery, and simulation outputs
   non-authoritative; and
4. stop autonomous iteration and surface verifier evidence when a deterministic
   gate fails repeatedly.

Exit condition: the existing RCT authority and replay contracts remain green
with no bypass or alternate mutation path.

### 2. Benchmark And Integrate The Frozen Visual Contract

V0 schemas and the V1 deterministic fixture matrix are implemented in
`src/seedcore/models/visual_evidence.py`,
`src/seedcore/services/visual_evidence_replay.py`, and
`tests/fixtures/visual_evidence_v0/cases.json`. The next authority-track work is
the static visual adapter described in
[`rare_shoe_rct_visual_evidence_adapter_v0.md`](rare_shoe_rct_visual_evidence_adapter_v0.md).

Work in order:

1. extend the canonical rare-shoe replay bundle with the frozen observation and
   comparison refs;
2. benchmark the same-model/different-pair comparison before choosing thresholds;
3. keep generated or inpainted pixels outside capture, fingerprint, PDP,
   verifier, and replay paths; and
4. route validation through the existing `RESULT_VERIFIER` before shadow use,
   without creating a visual-only verifier or decision path.

Exit condition: the runtime replay bundle reconstructs why a visual observation
was admitted or rejected, the benchmark supports reviewed calibration, and a
visual `MATCH` still cannot authorize custody or close the case.

### 3. Review And Promote City Persistence (C1b)

The three-table migration, PostgreSQL repository, transactional seeding, strict
hydration, timezone normalization, and no-fallback storage selection are
implemented. An isolated PostgreSQL 17 run passed clean migration, scoped-role,
seed/reload, schema-only dump/restore followed by reseed/reload parity, and
unchanged discovery API checks. Review the operational contract from
[`sovereign_city_foundations_and_infrastructure.md`](sovereign_city_foundations_and_infrastructure.md)
before changing any default.

Promotion work:

- review migration 137, role ownership, and the explicit seeding operation;
- decide whether to add the isolated database lifecycle to an opt-in host/CI
  gate;
- document the deployment-specific role membership and backup destination;
- keep `fixture` as the default until promotion is explicitly approved; and
- keep foundation state out of ambient PDP or policy-knowledge-graph caches.

Exit condition: the persistence boundary is human-reviewed, deployment role
membership is explicit, and no fixture or simulated state can be mistaken for
live authority-bearing state.

### 4. Build The Read-Only Producer And Service Slice (C2)

Reuse the city discovery boundary and the local-producer contract rather than
building a separate marketplace stack.

Work in order:

1. freeze versioned producer, service-profile, claim-state, anchor, and public
   projection schemas;
2. implement query, projection lookup, and anchor explanation as read-only
   services;
3. add the three vendor-neutral MCP wrappers over the same service layer;
4. add expiring one-image-plus-one-audio draft extraction with explicit
   correction and confirmation; and
5. render a safely escaped, low-bandwidth public proof page with operator
   exception paths.

Exit condition: agents and web clients can discover and explain public-safe
claims, but cannot book, buy, release, approve, transfer custody, or clear
quarantine through a read endpoint.

### 5. Build The Pattaya Reference Journey And Add Ordinary Coordination

After C2 is green, apply the product contract from
[`journey_driven_digital_city_experience.md`](journey_driven_digital_city_experience.md)
to one bounded Pattaya-area fixture or explicitly consented reference journey.

Work in order:

1. capture a private tourist request with explicit time, budget, mobility,
   accessibility, dietary, family, language, and interest constraints;
2. return a small journey over three to five eligible business profiles with
   source, freshness, requirement-fit reasons, unmet constraints, and a
   deterministic fallback;
3. render the journey as low-bandwidth proof cards plus one illustrated 2D
   reference area before introducing 3D or city-scale map infrastructure;
4. measure time to first usable journey, hard-constraint satisfaction,
   source/freshness coverage, and owner correction without using those metrics
   as authority inputs; and
5. add one ordinary reservation lifecycle and deterministic payment, logistics,
   or facility-provider simulator.

Ordinary coordination must remain separate from policy admission. No live
Pattaya fact is current merely because it appears in a fixture, generated
journey, or owner-unconfirmed draft.

Exit condition: the reference journey visibly satisfies or discloses every hard
constraint, stale or unavailable stops produce a bounded fallback, and
availability and commercial acceptance cannot be confused with
`policy-admitted`, `physically-attempted`, or `verifier-closed` state.

### 6. Pilot Two Governed City Actions (C3)

Only after C1b and C2 pass, map two `bootstrap_sim` actions into the existing
Agent Action Gateway:

- one simulated water or facility isolation; and
- one trade or custody action.

Both require named `ActionIntent` classes, accountable principals, policy
fixtures, scoped and revocable `ExecutionToken`s, transition receipts,
`SIMULATION_ONLY` evidence, negative drills, replay, and verifier closure.

Exit condition: the same trust spine governs both actions, simulated closure is
impossible to present as production closure, and no municipal, utility,
engineering, permit, emergency, or legal authority is implied.

### 7. Add Grounded Story Presentation

This follows the producer claim-state and public-proof slice; it does not block
RCT, C1b, or C2.

The first experiment is producer-approved, source-cited text plus an existing
consented still or audio excerpt. `Verified Origins`, `Producer-Declared
Details`, and `Artisan Story & Lore` remain visibly and structurally distinct.
Stale, revoked, or withdrawn sources remove dependent presentation.

Exit condition: story content is useful and withdrawable while remaining
absent from PDP context, visual fingerprints, custody evidence, and verifier
closure.

## Not In The Current Queue

- a global marketplace, super app, legal cadastre, permit authority, utility
  control center, emergency dispatch system, real escrow rail, or licensed
  transport operation;
- PostGIS, H3, OGC, IFC/BIM, city-scale maps, 3D, AR, or continuous digital-twin
  infrastructure without a measured requirement;
- generated reels, image-to-video, cloned voice, live personas, or generated
  pixels in any forensic path;
- activation of agriculture, artisan, workshop, or other production verticals
  without a separate reviewed decision; and
- policy, authorization graph, deployment, custody closure, or quarantine
  changes admitted solely by AI, retrieval, memory, simulation, or learning.

## Verification

Start with the repository gates named in `AGENTS.md`:

```bash
bash scripts/host/verify_authz_graph_rfc_phases.sh
bash scripts/host/verify_q2_verification_contracts.sh
```

For the current city slice:

```bash
pytest \
  tests/test_city_foundation_persistence.py \
  tests/test_city_foundation_discovery.py \
  tests/test_api_router_registry.py -q
```

After migration 137 is applied to an isolated local/test database:

```bash
SEEDCORE_CITY_RUNTIME_PROFILE=bootstrap_sim \
SEEDCORE_CITY_FOUNDATION_STORAGE=postgres \
python scripts/host/verify_city_foundation_persistence.py --seed
```

For the frozen visual contract and fixture matrix:

```bash
pytest tests/test_visual_evidence_contracts.py -q
```

For flywheel changes:

```bash
pytest tests/test_flywheel_harness.py tests/test_energy.py -q
```

The canonical gate ownership and failure behavior are in
[`policy_gate_matrix.md`](policy_gate_matrix.md).
