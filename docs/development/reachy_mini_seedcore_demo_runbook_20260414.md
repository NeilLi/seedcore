# Reachy Mini -> SeedCore Digital Twin Demo Runbook (2026-04-14)

Primary schedule source:
- `/Users/ningli/project/seedcore/docs/development/design_partner_demo_schedule.md`

Scope note:
- `local_practice_schedule.md` intentionally skipped (removed).

## 1) Live Reachy Mini pull (executed)

Source used:
- https://huggingface.co/spaces?filter=reachy_mini

Snapshot highlights (captured on 2026-04-14):
- Reachy Mini Conversation App (`pollen-robotics/reachy_mini_conversation_app`) - Running
- Red Light Green Light (`pollen-robotics/red_light_green_light`) - Running
- Reachy Mini Greetings App (`pollen-robotics/reachy_mini_greetings`) - Running
- Reachy Mini Clock (`pollen-robotics/reachy_mini_clock`) - Running
- ClawBody (`tomrikert/clawbody`) - Running
- Marionette (`RemiFabre/marionette`) - Running
- Reachy Mirror (`Domotick/reachy_mirror`) - Running
- 3D Web Visualizer (`8bitkick/reachy_mini_3d_web_viz`) - Running
- Reachy Phone Home (`itsMarco-G/reachy_phone_home`) - Running
- Reachy Mini App Example (`starlit-cat/reachy_mini_app_demo`) - Running

## 2) Selected demo pair for SeedCore trust-boundary story

Happy-path candidate (recommended):
- `pollen-robotics/reachy_mini_conversation_app`
- Why: official app-store grade UX, high engagement, easy to narrate as bounded AI intent crossing SeedCore trust boundary.

Toxic-path candidate (recommended):
- Use the *same* happy-path workflow but inject a controlled mismatch in SeedCore evidence chain:
  - stale telemetry OR
  - wrong serialized item
- Why: aligns exactly with your schedule's fail-closed objective (`quarantined`/`rejected`) and avoids random app instability as the toxic proof.

Supporting visual twin candidate:
- `8bitkick/reachy_mini_3d_web_viz`
- Role: optional side panel for digital twin visualization, not the primary trust claim.

## 3) Narrative mapping to SeedCore surfaces

Map each Reachy action to this fixed sequence:
1. request (`ActionIntent`)
2. approval lineage (`TransferApprovalEnvelope`)
3. governed decision (`PolicyDecision`) -> allow/deny
4. execution authorization (`ExecutionToken` + `PolicyReceipt`)
5. proof chain (`TransitionReceipt` + `EvidenceBundle`)
6. verification projection (`VerificationSurfaceProjection`)
7. replay + offline verifier evidence

Business line to keep:
- SeedCore is the trust boundary between AI intent and physical consequence.

## 4) Command runbook aligned to schedule

### T-7 (baseline lock)
```bash
mkdir -p artifacts/demo/$(date +%Y%m%d)_baseline
python scripts/tools/verify_phase0_contract_freeze.py | tee artifacts/demo/$(date +%Y%m%d)_baseline/01_phase0_contract_freeze.log
bash scripts/host/verify_q2_verification_contracts.sh | tee artifacts/demo/$(date +%Y%m%d)_baseline/02_q2_verification_contracts.log
python scripts/tools/verify_rct_signoff_bundle.py | tee artifacts/demo/$(date +%Y%m%d)_baseline/03_rct_signoff_bundle.log
```
Gate:
- all exit codes `0`
- environment locked (local host-mode default)

### T-3 (fresh evidence)
```bash
mkdir -p artifacts/demo/$(date +%Y%m%d)_evidence
python scripts/host/verify_rct_hot_path_shadow.py | tee artifacts/demo/$(date +%Y%m%d)_evidence/01_hot_path_shadow.log
bash scripts/host/verify_productized_surface.sh | tee artifacts/demo/$(date +%Y%m%d)_evidence/02_productized_surface.log
```
Then lock:
- one happy-path `audit_id`
- one toxic-path `audit_id`
- confirm both in replay, verification API, proof surface, operator console

### T-1 (dry run lock)
```bash
# optional verifier drill
cd rust
cargo run -q -p seedcore-verify -- verify-transfer --dir fixtures/transfers/allow_case
```
Gate:
- two full dry runs (10-12 min)
- cheat sheet frozen

### Day-of (stage bring-up)
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

## 5) Required IDs / artifacts checklist (freeze sheet)

Fill and freeze before demo:
- happy `audit_id`:
- toxic `audit_id`:
- `TransferApprovalEnvelope` id:
- `ExecutionToken` id:
- `PolicyReceipt` id:
- `TransitionReceipt` id(s):
- replay/detail URL:
- proof surface URL:
- verification API URL:
- offline verifier output path:
- fallback artifact bundle path:

## 6) Fallback ladder (no live debugging)

1. verification API issue -> use proof surface + replay for same `audit_id`
2. proof surface issue -> use verification API + offline verifier artifact
3. operator console issue -> continue with runtime API + replay + verifier artifact
4. runtime restart needed -> switch to pre-captured evidence bundle and continue narrative

## 7) Reachy pull update command (repeatable)

Use this quick check when refreshing app candidates:
```bash
open "https://huggingface.co/spaces?filter=reachy_mini"
```
Then re-select:
- 1 official `pollen-robotics` happy-path app
- 1 optional visualization app
- toxic path stays a SeedCore mismatch scenario (not random platform outage)
