# Supervised lesson: permission, interruption and evidence

Date: 2026-10-15
Status: Simulation rehearsal; no connected robot or classroom release

Allow 30 minutes with one adult facilitator and an existing laptop/browser.
No account, camera, learner identity or external AI service is needed. The
facilitator prepares the localhost service and Rust verifier using the
[acceptance guide](../development/robotics/simulation_first_acceptance.md).
Confirm the page says **Simulation only** and the service binds localhost.

The learning goal is to distinguish a proposal, permission, a simulated attempt
and verified evidence. The visual arm and recorded controller are independent
models. Their displays do not establish physical motion or physical safety.

| Time | Learner action | Facilitator check |
| --- | --- | --- |
| 0–5 min | Predict what a small move, an out-of-bounds proposal and revocation should do | Explain that a model proposal does not grant permission |
| 5–10 min | Select one simulated servo and propose an allowed move | Show the admitted one-second session, changing observations and fenced end; refresh does not extend permission |
| 10–15 min | Try out-of-bounds, forged, expired and wrong-endpoint cases | Each denies before a simulated controller opens; no dispatch count is recorded as motion |
| 15–20 min | Admit again, then select Revoke; repeat using Local stop | The attempt fences, pending motion is discarded and another fresh admission is needed |
| 20–25 min | Admit and hide the tab for at least one second; return and inspect | Browser refresh ceases; the host watchdog fences independently; the attempt does not resume |
| 25–30 min | Repeat one allowed/revoked case with three simulated servos and download evidence | Python/Rust report simulation scope and no physical acceptance; discuss what missing or changed evidence would mean |

Ask learners to explain why a heartbeat cannot extend permission, why knowing a
token ID does not authenticate a command, and why a signature cannot prove a
real servo moved. The visible cases use fixed local admission fixtures; no live
VLM/PDP is required or claimed.

Record only anonymous facilitator observations: cases reproduced, whether the
learner distinguished proposal/permission/evidence, setup time and confusing
steps. Keep downloaded samples local. Any later collection or sharing requires
separate consent/retention review; participation does not require telemetry.

If the service or verifier fails, stop the exercise and inspect the report.
Do not relabel a failed or missing verification as success. The static planar
lessons can still be used independently. Physical classroom use requires the
selected body's authority, electrical/mechanical, stop, signer, recovery and
support acceptance; this simulation lesson does not grant that acceptance.
