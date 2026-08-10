# Godot AI+VR Tourist Journey Experience Integration Plan

Date: 2026-08-10  
Status: Initial product and technical planning; no implementation or engine commitment yet  
Related tracks: [`tourist_design_studio_pilot_design.md`](tourist_design_studio_pilot_design.md), [`tourist_design_studio_delivery_schedule.md`](tourist_design_studio_delivery_schedule.md), and [`immersive_commerce_and_governed_trade_architecture.md`](immersive_commerce_and_governed_trade_architecture.md)

## 1. Decision In Brief

SeedCore should plan a **Tourist Journey AI+VR experience track** for tourists,
children, and families, with Godot as the preferred engine candidate for the
immersive runtime. The experience is intended to accompany the visitor journey
from anticipation and arrival through playful creation, exploration, and
memory/fulfillment—not merely to serve as a technical XR sidecar.

Godot is a strong candidate because its text-oriented project and scene files,
node composition, lightweight scripting, and command-line workflow make the
development surface unusually legible to Codex and other coding agents. The
engine choice still depends on the target headset, venue operation, and real
device evidence.

This is a product-experience track alongside the Tourist Design Studio, not a
change to SeedCore's RCT trust-runtime boundary:

- The current Tourist Design Studio pilot remains the smallest validated
  commerce entry point. AI+VR is a planned journey extension and must not make
  the first printable-souvenir pilot impossible to launch.
- Each journey experience must be private or explicitly supervised,
  time-bounded, age-appropriate, and justified by a measurable engagement,
  conversion, learning, or return-visit hypothesis.
- Godot scenes, scripts, assets, and test output are application artifacts.
  They do not mint authority, approve a purchase, transfer custody, clear
  quarantine, or replace SeedCore PDP, `ExecutionToken`, evidence, replay, or
  `RESULT_VERIFIER` controls.
- A desktop or headless Godot pass is never evidence that a Quest or other
  target headset is ready. Real-device validation is a required release gate.

The next action is a bounded product-and-technical feasibility slice, not a
full journey platform or headset fleet.

## 2. Tourist Journey Experience Thesis

The experience should make the trip feel more memorable by giving visitors a
safe, playful, AI-assisted world that is connected to the destination and to a
physical souvenir or family memory. AI is the guide, storyteller, activity
composer, and adaptation layer. VR is the immersive entertainment surface.
Neither is a payment, custody, or policy authority.

```text
Before the visit       Arrival / venue          After the visit
discover destination -> enter playful world -> keep approved memory
choose preferences     create and explore      receive souvenir / recap
parent sets limits     complete activities      no persistent child profile
```

The first journey slice should support one coherent loop:

1. A visitor selects a destination theme and an age-appropriate activity.
2. A child or family explores a bounded Godot scene with guided AI narration,
   characters, objects, and safe interaction choices.
3. The system adapts pacing, hints, language, or difficulty from local session
   state and explicit adult settings.
4. The visitor approves a souvenir or memory output through the ordinary
   purchaser flow outside the headset.
5. The experience ends with a clear session reset and a fulfillment or
   follow-up handoff that does not expose private child content.

Possible journey surfaces include a phone/kiosk before or after the immersive
session and a Godot headset or venue installation during the experience. The
runtime need not force every stage into VR; the journey is the product unit,
while each surface should use the smallest appropriate technology.

### AI role in the experience

AI may:

- narrate destination stories using approved content and language settings;
- suggest age-appropriate activities, characters, or creative variations;
- adapt hints, pacing, accessibility options, and difficulty within bounds;
- summarize an approved session for a parent, venue operator, or souvenir flow.

AI may not independently publish unsafe content, identify a child across
visits, collect unnecessary sensitive data, authorize payment, or trigger a
trade/custody action. Generated content must pass the experience's content,
age, and moderation gates before it reaches the child-facing scene.

## 3. Why Godot Fits The Agent-First Development Model

The supplied engine comparison identifies a development-loop distinction that
matters for this track:

```text
Unity-oriented loop:  agent -> C# -> editor and serialized state -> build
Godot-oriented loop: agent -> filesystem (.gd/.tscn/.tres) -> CLI checks -> build
```

For an agent-maintained prototype, the second loop has useful properties:

| Concern | Godot advantage to validate | Planning implication |
| --- | --- | --- |
| Scene reasoning | Node trees are explicit and compositional | Keep scenes small, named, and load-testable |
| Git review | `.gd`, `.tscn`, `.tres`, and project configuration are inspectable text | Require ordinary diffs and prohibit editor-only hidden state |
| Automation | Project checks, tests, and exports can run from the command line | Make every agent task end with deterministic CLI gates |
| Refactoring | Node paths and script contracts can be searched and changed structurally | Define stable interaction interfaces before adding activities |
| Low-context coding | GDScript has relatively little ceremony for small behaviors | Prefer simple scripts with explicit exported configuration |
| Debugging | Logs and headless runs can be captured as artifacts | Treat logs as diagnostics, not authority or safety proof |

These are hypotheses to test, not assumptions that override XR ecosystem or
hardware evidence. Quest/OpenXR support, renderer behavior, hand tracking,
performance, input mapping, and packaging must be verified against the exact
Godot version and target device selected for the spike.

## 4. Scope And Non-Goals

### In scope for the initial spike

- one Godot project skeleton that an agent can inspect and modify;
- a minimal `XROrigin3D` scene with camera and controller/hand placeholders;
- one safe, child-appropriate journey interaction such as selecting or
  touching a virtual object;
- a small activity scene with a clear game-state boundary;
- headless project validation, scene-load checks, and a desktop smoke run;
- an Android/OpenXR export rehearsal if the local toolchain supports it;
- a written device-validation checklist and captured failure artifacts.

### Explicitly out of scope

- forcing native VR into the first Tourist Design Studio pilot before the
  journey hypothesis and operations are validated;
- a persistent social world, avatars, public profiles, or cross-visitor chat;
- biometric, voice, eye-tracking, or persistent child identity collection;
- open-ended child-facing generation without a separate safety and content
  review design;
- checkout, payment, custody, shipment, or RCT execution inside the scene;
- direct browser/headset calls to SeedCore authority endpoints;
- treating an LLM proposal, scene state, physics result, or performance score
  as an authorization decision;
- building custom hardware or committing to a production headset fleet.

## 5. Proposed Agent-Readable Project Shape

The project should be a separate application repository or clearly isolated
subtree. It should not be embedded into SeedCore's Python/Ray runtime or share
its production data stores.

```text
kids-vr/
├── game/
│   ├── worlds/
│   ├── characters/
│   ├── interactions/
│   ├── ui/
│   └── activities/
├── systems/
│   ├── xr/
│   ├── locomotion/
│   ├── safety/
│   ├── audio/
│   └── analytics/
├── assets/
├── tests/
│   ├── unit/
│   ├── scenes/
│   └── xr/
├── tools/
│   ├── validate_project.gd
│   ├── validate_performance.gd
│   └── export_quest.sh
├── AGENTS.md
├── architecture.md
└── project.godot
```

The exact folders may change after the spike. The important properties are
that responsibilities are discoverable, scene composition is separated from
business rules, and every generated or modified artifact has a reviewable
source file and a reproducible check.

### Initial scene contract

```text
KidVRWorld
├── XROrigin3D
│   ├── XRCamera3D
│   ├── LeftHand
│   └── RightHand
├── Environment
├── Characters
├── Activities
└── GameManager
```

`GameManager` may coordinate local activity state. It must not be treated as a
policy decision point, approval authority, payment controller, custody ledger,
or verifier. If a future experience needs to display a verified result, it
may consume a deliberately narrow, read-only projection supplied by an
intermediary application after the existing verification contract has been
defined. The scene remains presentation-only.

## 6. Agent Operating Invariants

The future project should include an `AGENTS.md` with at least these rules:

1. AI-generated plans and code are proposals until a human reviews the diff
   and the deterministic checks pass.
2. Never put product, safety, or activity rules directly into XR controller
   scripts; controller scripts emit local interaction events to explicit
   interfaces.
3. Scenes remain compositional. Shared behavior belongs in versioned scripts
   or resources, not untracked editor state.
4. Every interactive object implements the same versioned interaction
   contract, including disabled, out-of-bounds, and reset behavior.
5. No synchronous filesystem or network operation runs from `_process()` or
   `_physics_process()`.
6. No headset client calls SeedCore PDP, token, custody, or verifier mutation
   endpoints directly.
7. No local scene state, model output, telemetry score, or analytics event can
   become an approval, token, policy update, custody transition, or quarantine
   clearance.
8. Every new scene has an automated load test and at least one negative-path
   test.
9. Quest/target-device budgets are hard constraints: frame time, memory,
   draw calls, asset size, thermal behavior, and interaction latency must be
   measured on hardware.
10. When a deterministic gate fails repeatedly, stop autonomous iteration and
    surface the logs, reproduction steps, and runbook evidence for human
    review.

## 7. Integration Boundary With SeedCore

The default architecture is deliberately disconnected from the RCT authority
path:

```text
Product / venue hypothesis
          |
          v
Codex planner -> Godot project files -> CLI validation -> desktop test
                                      |
                                      v
                               target-device test
                                      |
                                      v
                           human-reviewed release decision
```

If a later product requirement needs a trust-runtime integration, use an
explicit adapter and keep the direction of authority visible:

```text
Godot experience
  -> non-authoritative session/result request
  -> separate application adapter
  -> narrow read-only verified projection or human-operated handoff UI
```

The XR client must never receive an `ExecutionToken` or infer one from a
successful API response. Consequential actions remain in a conventional,
operator-legible surface:

```text
AI proposal -> accountable agent -> PDP -> ExecutionToken -> actuator
           -> receipt -> evidence -> RESULT_VERIFIER / replay closure
```

This keeps the immersive track consistent with the portfolio boundary in
[`immersive_commerce_and_governed_trade_architecture.md`](immersive_commerce_and_governed_trade_architecture.md):
immersive UI may explain or explore, but it cannot authorize or settle.

## 8. Initial Delivery Plan

### Phase 0 — Journey, safety, and feasibility freeze

Deliver:

- selected Godot version, OpenXR profile, target headset, renderer, and
  supported input mode;
- one named journey moment and measurable hypothesis;
- a short architecture note and separate-project data map;
- child-safety, supervision, sanitation, accessibility, and retention owners;
- a Godot CLI availability check on the development machine/CI runner;
- a go/no-go decision for the spike.

Exit only when the target device and operating model are named. “Desktop VR
works” is not sufficient.

### Phase 1 — Agent-readable vertical slice

Build one tiny activity, for example selecting and placing friendly objects in
a bounded room. The slice must include:

- node-based scene composition;
- an interaction interface with reset and disabled states;
- local audio/visual feedback;
- no network or payment dependency;
- unit checks for activity rules;
- scene-load and missing-node checks;
- a deterministic desktop smoke test.

### Phase 2 — Hardware and performance gate

Run the same project on the named headset and capture:

- install/export result;
- controller or hand-tracking behavior;
- frame-time and memory measurements;
- thermal and session-duration observations;
- crash, renderer, tracking, and input logs;
- accessibility and supervised-child usability notes.

Any failure becomes a tracked issue or a scope stop. It must not be hidden by
declaring the desktop run successful.

### Phase 3 — Controlled tourist journey experiment

Only after Phases 0–2 pass, run one measurable journey experiment such as
engagement, product confidence, souvenir conversion, learning, or return
visits. Keep payment and adult approval in the ordinary purchaser flow, and
keep any trade/custody action outside the scene. Compare the experience against
the existing non-XR flow and record stop criteria before expanding to more
activities, venues, or journey stages.

## 9. Required Gates And Artifacts

| Gate | Required evidence | Authority posture |
| --- | --- | --- |
| Source integrity | Git diff, project manifest, asset/license inventory | Agent output remains reviewable proposal |
| Static/CLI validation | Project parse, script checks, scene-load checks, test output | Failure blocks the slice; no automatic promotion |
| Desktop smoke | Reproducible launch and interaction log | Diagnostic only |
| Device validation | Export/install record, performance profile, input/tracking results | Required for headset claims; not a SeedCore authorization result |
| Child/venue safety | Supervision, privacy, accessibility, sanitation, content review | Human-owned release decision |
| Product experiment | Journey hypothesis, cohort, metric, guardrail, stop rule | Does not promote XR into RCT scope |
| Any future trust projection | Versioned read-only projection contract and replay-visible source | Presentation only; never token or custody authority |

Suggested checked-in artifacts:

- `architecture.md` and `AGENTS.md`;
- `tests/fixtures/` for deterministic scene and interaction cases;
- `artifacts/device-validation/<device>/<run-id>/` for logs and summaries;
- `docs/device-validation.md` for the supported hardware matrix;
- a human-reviewed experiment decision memo before any venue deployment.

## 10. Risks And Open Decisions

| Risk or decision | Initial handling |
| --- | --- |
| Godot XR ecosystem or plugin drift | Pin versions; rerun the device gate after engine/plugin changes |
| Desktop success masks headset failure | Make real-device validation a hard exit gate |
| Agent edits create fragile scene paths | Use small scenes, stable contracts, load tests, and structural diffs |
| Child privacy or supervision is underspecified | Assign owners in Phase 0; no persistent identity or biometric collection |
| Visual polish expands scope | Start with one measurable activity and placeholder assets |
| XR becomes an alternate SeedCore client | Keep the adapter separate and read-only by default |
| Tourist pilot becomes blocked by VR work | Keep the printable pilot independently deliverable; do not make AI+VR a hidden dependency of Pilot Phases 0–3 |
| Quest support is insufficient for the product hypothesis | Stop or choose another substrate based on evidence; Godot is not a sunk-cost commitment |

Open decisions before implementation:

1. Which headset and venue operating model, if any, is the first target?
2. Is the first hypothesis child/family engagement, souvenir conversion, or
   read-only evidence comprehension?
3. Who owns age policy, supervision, device sanitation, accessibility, and
   incident response?
4. Which Godot version, XR plugin profile, renderer, and export toolchain are
   supportable for the target device?
5. Is a separate application repository preferred, or is an isolated project
   subtree sufficient for the pilot team?

## 11. Planning Rule

```text
Godot is a candidate runtime for a product-facing tourist journey experience.
It is not a trust authority, a child-data system, or an RCT actuator.
```

The next review should admit the journey feasibility slice. A full spatial
build, headset fleet, direct SeedCore integration, or venue deployment requires
the evidence and owners defined above.
