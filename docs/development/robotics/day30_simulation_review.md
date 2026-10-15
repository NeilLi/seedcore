# Day-30 review sheet: simulation-first checkpoint

Prepared: 2026-10-15
Scheduled decision: 11–12 November 2026
Current recommendation: continue offline integration; defer physical release

This is an early evidence inventory, not a completed day-30 or hardware review.
Use the [execution plan](../strategy/seedcore_physical_ai_execution_plan_2026_2028.md)
for gate definitions and the [acceptance guide](simulation_first_acceptance.md)
for reproducible commands and artifact provenance.

| Review item | Current evidence | Required before dependent acceptance |
| --- | --- | --- |
| Source/policy contract | Candidate runtime/RL/body/policy pins and explicit 61/14/15 mapping | Reconcile unavailable earlier runtime pin and runtime/body/policy compatibility |
| Observation/export checks | 16 upstream Rust observation and independent ONNX evaluator vectors; CPU runtime replay | Exact training checkpoint, normalization/export state and independent training outputs |
| Read-only startup | Native MuJoCo adapter rejects motion; hardware profile cannot fall back | Native live integration and full profile review |
| Bounded sessions | Durable single-use claim, scope/sequence/deadline checks, independent host watchdog, revocation fixtures | Actual gateway/PDP/native boundary and device ingress enforcement |
| Evidence | Action-bound host-signed simulation receipts, Python/Rust verification and corruption/gap rejection | Enrolled hardware signer, capture calibration and production RESULT_VERIFIER closure |
| Browser rehearsal | Forged denial, admitted revocation and Rust-verified download reproduced in local headless Chrome | Managed Chromebook/browser matrix and independent facilitator repeat |
| Firmware | Local build-review packet preparer; no source/image qualified | Reviewed ESP-IDF build, source/binary provenance, enrollment and flash/recovery tests |
| Physical stop | Not measured; no connected fixture | Revocation propagation, response initiation, stopping time/distance, bus/tick load and fault traces |
| BOM and support | $12 recurring controller target; quote and support measurements unset | Volume/parts/power/assembly/test/yield/logistics/support quotation and owner |

Regression status at this checkpoint: simulator, model/workbench, telemetry,
session/codec and cross-language checks pass. Q2 checks pass, with Postgres
integration skipped by their configured default. The authorization script's
79 focused tests pass; its live stage is unavailable because the API on local
port 8002 is offline. This is not a complete deployed-stack qualification.

For each subsequent bench run attach the exact profile/source/image digests,
admission outcome, command trace, capture completeness and verifier disposition.
Measure allow, deny, interruption, host/browser loss, revocation, restart,
capture overflow and rollback separately. Keep all hardware timing fields unset
until observed; configured 5 ms host polling is not a physical latency result.

At the scheduled review record one decision and its evidence:

| Decision | Criteria |
| --- | --- |
| Go to next offline/native integration slice | Reproducible source and authority/evidence checks, named owners and bounded scope |
| Go to supervised one-servo bench, then three | Selected physical profile passes the relevant G0/G1 controls and the operator's bench acceptance; physical demonstration also requires G2 |
| Rescope | Reference/firmware/support evidence remains incomplete; retain a simulation deliverable and move dependent dates |
| Defer release | Missing identity/enforcement, stopping/capture/recovery evidence, unresolved deterministic gate failures or unsupported economics |

Decision owner, reviewed artifact set, hardware quote, physical measurements and
next approved kit/site tranche remain unset. No outreach or procurement follows
automatically from this sheet.
