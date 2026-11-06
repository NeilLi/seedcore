# CW-L03: authoring and simulation alpha review

Date: 2026-11-06
Decision: **DEFER release decision**; local software candidate available

The candidate includes the CW-L01 local curated gallery/fork and a guided
synthetic rehearsal/export lesson. Its source baseline is commit `4ae171c` plus
the current uncommitted candidate diff; exact input/output hashes and the browser
exercise are recorded in `artifacts/robotics/cw-l01/verification.json`.
The candidate is restricted to local offline authoring and the existing synthetic
simulation profile. The tabletop starter is not simulation or hardware qualified.

The source-built local gate passes 309 workspace tests and seven Chrome groups.
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
