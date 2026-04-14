# Design Partner Demo Schedule

## Purpose

This document turns the current Restricted Custody Transfer implementation into a partner-convincing demo schedule.

It assumes the core implementation already exists and is credible. The job now is to present the strongest possible trust story with the least on-stage risk.

## Demo thesis

The audience should leave with one clear conclusion:

**SeedCore is the trust boundary that decides whether autonomous intent is allowed to become trusted physical reality.**

That means the demo must prove all four of these:
- authority is bounded before action
- physical evidence is attached after action
- verification is replayable after the fact
- failure becomes governed business state, not silent breakage

## Recommended format

- Total runtime: `10` to `12` minutes
- Primary environment: signed-off local host-mode stack
- Optional upgrade: remote kube topology only if full verification-surface signoff is green before demo day
- Primary surfaces:
  - runtime API result
  - verification surface
  - replay/detail view
  - operator console
  - offline verifier or proof artifact panel

## Why this schedule

The codebase already supports:
- dual-approved transfer authority
- governed authorization output
- replayable proof artifacts
- verification surface projection
- deny, quarantine, and review-required outcomes

So the strongest partner demo is not "look how much we built." It is:

**one happy path, one toxic path, one replayable audit chain, one clear business claim.**

## Show only this story

Use one canonical workflow:
- high-value lot handoff
- dual approval already persisted
- governed authorization at the handoff point
- physical proof and replay chain
- fail-closed toxic-path rejection

Avoid turning the demo into:
- a generic robotics console
- a cloud infrastructure tour
- a broad operator dashboard walkthrough
- a "many workflows" product pitch

## Schedule before demo day

### T-7 days

Lock the runtime path and proof package.

Run:
```bash
python scripts/tools/verify_phase0_contract_freeze.py
bash scripts/host/verify_q2_verification_contracts.sh
python scripts/tools/verify_rct_signoff_bundle.py
```

Goal:
- confirm the repo and captured signoff bundle are still green
- decide whether the live demo will run in local host mode or remote kube
- freeze the exact ports, routes, and UI surfaces used on stage

Step-by-step checklist:
1. Create a timestamped demo folder for this run:
```bash
mkdir -p artifacts/demo/$(date +%Y%m%d)_baseline
```
2. Run all three signoff checks in order and save logs:
```bash
python scripts/tools/verify_phase0_contract_freeze.py | tee artifacts/demo/$(date +%Y%m%d)_baseline/01_phase0_contract_freeze.log
bash scripts/host/verify_q2_verification_contracts.sh | tee artifacts/demo/$(date +%Y%m%d)_baseline/02_q2_verification_contracts.log
python scripts/tools/verify_rct_signoff_bundle.py | tee artifacts/demo/$(date +%Y%m%d)_baseline/03_rct_signoff_bundle.log
```
3. Confirm all three commands return exit code `0`.
4. Decide environment:
   - choose local host mode by default
   - choose remote kube only if all verification-surface checks are still green in that environment
5. Freeze the stage surfaces and ports in your demo notes:
   - runtime API: `127.0.0.1:8002`
   - verification API: `serve:verification-api`
   - proof surface: `serve:proof-surface`
   - operator console: `serve:operator-console`

Exit criteria:
- all baseline checks are green
- demo environment choice is locked
- baseline logs are saved under `artifacts/demo/<date>_baseline/`

### T-3 days

Capture fresh live evidence for the exact demo environment.

Run:
```bash
python scripts/host/verify_rct_hot_path_shadow.py
bash scripts/host/verify_productized_surface.sh
```

Goal:
- produce one fresh happy-path `audit_id`
- confirm the same `audit_id` resolves across replay, verification API, proof surface, and operator console
- choose one toxic-path case to show live

Recommended toxic path:
- wrong serialized item or stale telemetry leading to quarantine or verification failure

Step-by-step checklist:
1. Create an evidence folder:
```bash
mkdir -p artifacts/demo/$(date +%Y%m%d)_evidence
```
2. Run hot-path and productized-surface checks:
```bash
python scripts/host/verify_rct_hot_path_shadow.py | tee artifacts/demo/$(date +%Y%m%d)_evidence/01_hot_path_shadow.log
bash scripts/host/verify_productized_surface.sh | tee artifacts/demo/$(date +%Y%m%d)_evidence/02_productized_surface.log
```
3. Capture one candidate happy-path `audit_id` from logs or API output and store it in your run notes.
4. Verify that same `audit_id` is resolvable in:
   - replay/detail view
   - verification API response
   - proof surface UI
   - operator console
5. Select exactly one toxic path and pre-generate its ID/artifact reference.

Exit criteria:
- one happy-path `audit_id` is confirmed across all surfaces
- one toxic-path case is selected and reproducible
- evidence logs are saved under `artifacts/demo/<date>_evidence/`

### T-1 day

Dry-run the exact talk track with the exact operator clicks.

Lock:
- opening slide
- one happy-path workflow id or `audit_id`
- one toxic-path workflow id or `audit_id`
- one offline verification command
- one fallback artifact bundle

Step-by-step checklist:
1. Timebox and run the full script once at normal speed (`10` to `12` minutes).
2. Run a second pass with a deliberate pause at each handoff:
   - governance freeze
   - allow decision
   - proof surface
   - offline verification
   - toxic fail-closed result
3. Lock final IDs in a single cheat sheet:
   - happy path `audit_id`
   - toxic path `audit_id`
   - approval envelope id
   - receipt ids
4. Validate fallback bundle exists and is readable offline.
5. Freeze narrative wording for opening and close.

Exit criteria:
- two successful dry runs completed
- all IDs and links are frozen in one cheat sheet
- fallback assets are ready if any live surface degrades

### Day of demo

Start only the required services.

Run:
```bash
uvicorn seedcore.main:app --host 127.0.0.1 --port 8002
npm --prefix ts run serve:verification-api
npm --prefix ts run serve:proof-surface
npm --prefix ts run serve:operator-console
```

Preflight:
```bash
curl http://127.0.0.1:8002/health
curl http://127.0.0.1:8002/readyz
bash scripts/host/verify_hot_path_observability.sh
```

Goal:
- confirm all partner-visible surfaces are warm before the audience joins
- avoid any live debugging on stage

Step-by-step checklist:
1. Open four terminals before start:
   - runtime API
   - verification API
   - proof surface
   - operator console
2. Start services in this order:
```bash
uvicorn seedcore.main:app --host 127.0.0.1 --port 8002
npm --prefix ts run serve:verification-api
npm --prefix ts run serve:proof-surface
npm --prefix ts run serve:operator-console
```
3. Run preflight checks:
```bash
curl http://127.0.0.1:8002/health
curl http://127.0.0.1:8002/readyz
bash scripts/host/verify_hot_path_observability.sh
```
4. Open all URLs and keep tabs preloaded to the first scene.
5. Keep fallback artifacts open in a backup tab/window.

Exit criteria:
- all health checks are green
- all demo tabs are preloaded and responsive
- no pending command output indicates startup warnings requiring intervention

## Freeze checklist (single-page)

Use this exact checklist as a gate before the demo starts:

- [ ] baseline signoff scripts green (T-7)
- [ ] happy-path `audit_id` verified across all surfaces (T-3)
- [ ] toxic-path case selected and reproducible (T-3)
- [ ] two successful dry runs completed (T-1)
- [ ] final cheat sheet with IDs and command snippets prepared (T-1)
- [ ] fallback artifact bundle ready and accessible (T-1)
- [ ] runtime + three partner-visible services running (Day 0)
- [ ] `/health` + `/readyz` + observability preflight green (Day 0)
- [ ] all required browser tabs preloaded before audience joins (Day 0)

## Fallback plan (if anything breaks live)

If one surface is degraded, do not debug live. Switch immediately:

1. Verification API down:
   - use proof surface + replay detail view for the same `audit_id`
2. Proof surface down:
   - use verification API + offline verifier output artifact
3. Operator console down:
   - continue with runtime API result + replay + verifier artifacts
4. Runtime restart required:
   - switch to pre-captured evidence bundle and continue narrative

Rule:
- never pause the demo for infrastructure diagnosis
- keep the trust-boundary narrative moving with pre-verified artifacts

## Live demo schedule

### Scene 1 - Category framing (`1 minute`)

Show one architecture slide:
- humans and AI agents above the trust boundary
- commerce and physical execution below it
- SeedCore in the middle as referee

Narration:

> "This is not a robot demo and not a shopping demo. It is a trust-boundary demo."

### Scene 2 - Governance is frozen before action (`1 minute`)

Show:
- policy snapshot summary
- spend/scope/evidence rules
- dual approval lineage

Point to make:
- human governance happens before live action
- the runtime is enforcing policy, not improvising policy

### Scene 3 - Happy path: governed authorization (`2 minutes`)

Show:
- buyer or operator request
- persisted approval envelope
- SeedCore evaluation response
- `allow` disposition
- `ExecutionToken`
- `PolicyReceipt`

Point to make:
- the system did not authorize because an AI sounded confident
- it authorized because bounded authority, approvals, and scope matched

### Scene 4 - Happy path: proof surface (`2 minutes`)

Open the verification surface and replay/detail views.

Show:
- business-readable result = `verified`
- same workflow or `audit_id`
- approval envelope id
- receipt ids
- replay link
- forensic or evidence summary

Point to make:
- this is not only an API response
- it is an inspectable proof chain

### Scene 5 - Third-party verification (`1 minute`)

Run one offline verification step or show the proof artifact panel.

Preferred command:
```bash
cd rust
cargo run -q -p seedcore-verify -- verify-transfer --dir fixtures/transfers/allow_case
```

Point to make:
- a third party can verify the outcome without trusting the live app session

### Scene 6 - Toxic path: fail closed (`2.5 minutes`)

Replay the flow with one concrete mismatch.

Best default:
- stale telemetry or wrong serialized part after approval

Show:
- business-readable state = `quarantined` or `rejected`
- exact mismatch reason in replay/detail
- no surviving downstream release
- lockout or deny behavior

Point to make:
- failure becomes governed business state
- the system stops the transfer instead of silently degrading

### Scene 7 - Partner close (`1 minute`)

Return to the same trust claim:
- bounded authority before action
- physical proof after action
- replayable verification after the fact
- automatic stop on mismatch

Final line:

> "SeedCore is the referee between AI intent and real-world consequences."

## Primary happy-path artifacts

The happy path should visibly reference:
- `ActionIntent`
- `TransferApprovalEnvelope`
- `PolicyDecision`
- `ExecutionToken`
- `PolicyReceipt`
- `TransitionReceipt`
- `EvidenceBundle`
- `VerificationSurfaceProjection`

## Primary toxic-path artifacts

The toxic path should visibly reference:
- business-readable failed state
- mismatch reason
- replay detail
- explicit downstream deny or lockout

Keep internal-only failure mechanics in drill-down detail, not in the first sentence of the demo.

## Recommended proof sequence

For the partner audience, use this order:

1. request
2. approval lineage
3. governed decision
4. proof surface
5. replay
6. fail-closed mismatch
7. offline verification

This sequence lands better than starting with infrastructure or tests.

## Demo operator rules

- Keep one operator driving the keyboard
- Keep one narrator speaking the business meaning
- Pre-open the queue/detail/replay tabs
- Use captured workflow ids or `audit_id`s, not ad hoc searching on stage
- Do not show raw implementation logs unless something goes wrong
- Do not explain `shadow` mode as a weakness; explain it as controlled promotion discipline

## Fallback ladder

If live runtime behavior degrades, keep the trust story intact by falling back in this order:

1. captured live signoff bundle
2. proof surface + replay pages on captured artifact chain
3. offline verifier on frozen fixtures

If physical hardware degrades:

1. keep SeedCore surfaces as primary truth
2. use simulated or scripted telemetry as supporting evidence
3. do not change the business claim mid-demo

## Success criteria

The demo is strong enough for partners if they can repeat this back afterward:

- approvals were real and persisted
- the runtime decision was bounded and explainable
- the proof chain survived outside the live app
- the toxic path was stopped automatically

## Related references

- [killer_demo_execution_spine.md](/Users/ningli/project/seedcore/docs/development/killer_demo_execution_spine.md)
- [next_killer_demo_contract_freeze.md](/Users/ningli/project/seedcore/docs/development/next_killer_demo_contract_freeze.md)
- [restricted_custody_transfer_demo_signoff_report.md](/Users/ningli/project/seedcore/docs/development/restricted_custody_transfer_demo_signoff_report.md)
- [q2_2026_audit_trail_ui_spec.md](/Users/ningli/project/seedcore/docs/development/q2_2026_audit_trail_ui_spec.md)
- [autonomous_repair_transfer_demo_spec.md](/Users/ningli/project/seedcore/docs/development/autonomous_repair_transfer_demo_spec.md)
