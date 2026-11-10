# 10 November: updated Studio maker-trial handoff

Date: 2026-11-10
Timezone: Asia/Bangkok (UTC+07:00)
Source baseline: `b71d022d` — beginner Studio and complete Microduck visual explorer
Package: CW-L02 maker-trial readiness
Implementation owner role: Studio/tooling implementer
Status: Software preparation complete; independent human observation pending

## Selected schedule

The active queue selects CW-L02 before CW-L03. Earlier software preparation
exists, but its reports predate the new landing view, labels, controls and model
assets. Refresh that evidence rather than treating it as current acceptance.

| Order / time box | Work | Completion evidence |
| --- | --- | --- |
| 1 / 30 minutes | Inspect exact candidate and trial contract | Identify changed source/build dependencies and obsolete participant instructions |
| 2 / 60 minutes | Repair packet and refresh participant help | Correct lesson payload; bounded full-model hashing; explicit visual vs. synthetic simulation tasks |
| 3 / 60–90 minutes | Source-built browser and startup verification | Workspace tests; beginner, full-model and gallery flows; source/model/build hashes; occupied-port refusal and two owned-server starts/stops |
| 4 / 30 minutes | Prepare and verify a new local trial packet | Current candidate references and pending observation record, without replacing prior packets |
| Next available participant session | Observe independent adult maker | Actual setup/task timing, assistance, accessibility, recovery, privacy and download findings |
| After observation and issue disposition | CW-L03 review | Exact reviewed artifacts, named support/rollback ownership and a separate release decision |

These are work estimates and dependency order, not claims about elapsed work or
promised release dates. The final two rows depend on people and review evidence.
This allocation does not reopen full-model physics, policy execution, firmware
or hardware qualification.

## Required corrections

- `lesson.md` previously copied the trial verification Python script because it
  used the wrong positional entry in an input list. Use the participant document
  by named path and test the actual payload.
- The existing per-artifact 20 MiB hash limit rejects the complete visual GLB.
  Permit up to 64 MiB for that exact generated file only; retain streaming
  hashing, other size limits and the small reference-only packet.
- Bind the visual exporter, original Microduck model package and all build
  outputs, including the compressed delivery and original license. Older
  gallery-only reports cannot establish the new beginner/full-model flows.
- Refresh startup assertions and lesson labels. A 240 ms synthetic run is too
  short to assume a human exercised Stop; record it as not exercised when missed.
- Preserve the existing server on port 8767. Use separate ports for automated
  startup/restart probes and the new packet; browser storage belongs to an origin.

## Execution record

The source-built gate passed **309 workspace TS tests**, **57 focused Python
checks** (including 33 packet/preflight checks), the beginner and full Microduck
browser exercises, and **seven gallery/lesson Chrome groups**. It pins
184 source inputs and 24 generated build outputs. Its report is
`artifacts/robotics/cw-l01/verification.json`.

The separate actual startup gate passed **five groups**, including two
owned-server start/stop cycles, occupied-port refusal without interrupting the
listener, packet verification while running, and immediate post-stop readiness.
Automated startup measurements were 0.76 s and 0.746 s;
these are machine measurements, not participant setup times. Its report is
`artifacts/robotics/cw-l02/verification.json`. The temporary packet referenced
there is a startup probe; the named handoff below supersedes it after final
documentation changes.

The final local handoff packet is
`artifacts/robotics/cw-l02-trials/2026-11-10-microduck-ready-01/`, configured
for free port **8784** so the existing Studio on **8767** remains undisturbed.
Run its README commands to start the independent trial. Changing port gives
a separate browser-storage origin; use exported project files when needed.
The packet is prepared and checked against the current checkout, with the
`b71d022d` baseline plus the explicit uncommitted tooling/documentation diff.
Later source/build or preparation-document changes require a fresh packet.

No independent participant results, support owner, rollback owner or release
approval have been supplied. CW-L03 remains **DEFER**. Next: observe one adult
maker following `lesson.md`, record actual outcomes in `observation.json`, fix
observed issues and review the exact candidate with named support/rollback owners.
No new authority/shared-runtime contracts changed; broader live authz, Postgres,
hardware and policy lanes were not rerun or claimed as passing in this refresh.

Changes remain local and uncommitted; no publication or hardware operation was
performed. Existing browser drafts and the user's 8767 server were preserved.
