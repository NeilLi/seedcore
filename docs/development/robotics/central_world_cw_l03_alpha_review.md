# CW-L03: authoring and simulation alpha review

Date: 2026-11-10
Decision: **DEFER release decision**; local software candidate available

The candidate includes the CW-L01 local curated gallery/fork and a guided
synthetic rehearsal/export lesson. Its committed source baseline is `b71d022d`.
The 10 November trial-refresh changes are an explicit uncommitted diff:
current source/build hashes, revision, dirty state and automated evidence are
recorded in `artifacts/robotics/cw-l01/verification.json` and the generated
`artifacts/robotics/cw-l02-trials/<trial>/candidate.json`. The candidate adds
beginner controls and a complete display-only Microduck explorer. Pose controls
are not full-model physics or a trained walking policy. A packet is prepared
evidence, not a recorded maker session. Support and rollback ownership remain
unassigned. A participant was offered for 9 November, then the operator explicitly
reported **not tested** and asked implementation to continue. No independent
maker observation is recorded; availability alone does not close the trial.
The candidate is restricted to local offline authoring and the existing synthetic
simulation profile. The tabletop starter is not simulation or hardware qualified.

The refreshed 10 November source-built gate passes 309 workspace tests, 57
focused Python checks (including 33 packet/preflight checks), the beginner and
full Microduck browser exercises, and seven gallery/lesson Chrome groups.
The separate startup/restart gate passes five groups, including two owned-server
starts/stops and occupied-port refusal. These results are recorded in the dated
[handoff](cw_l02_daily_plan_2026_11_10.md).
The existing CW-E01 and governance regressions are recorded in the implementation
handoff. These are engineering checks, not a measured independent user trial or a
remote CI/public-hosting result.

Release review remains open until the following are available:

1. An independent adult-maker observation using the [lesson sheet](central_world_cw_l02_maker_lesson.md),
   including actual timing, assistance, accessibility and failure findings.
2. A reviewed exact source/build/artifact set, supported browser/device list and
   resolution or explicit disposition of observed issues.
3. Named support and rollback ownership, a practical rollback path and any
   required hosting/account authorization before publication.
4. A separate human release decision with its scope and exclusions; qualified
   physical execution, printable CAD, firmware and policy execution have their
   own gates.

No deployment, external publication or claim of physical acceptance is made by
this decision. If the maker trial or release prerequisites are unavailable,
retain **DEFER** and continue local preparation; do not convert missing evidence
into a pass based on the calendar.
