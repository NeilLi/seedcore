# CW-L02: robot choice and task-flow repair

Date: 2026-11-12
Status: Local implementation candidate; independent retry required
Source baseline: `b86fd3bb` plus explicit local implementation/documentation diff
Scope: Local visual exploration and existing synthetic simulation only

## Later 12 November correction: full robot by default

The participant's next screenshot showed that the task-guide repair still led
with raw component geometry. They asked to load a default tiny robot such as
Microduck or a robot dog. The earlier repair did not close that recognition gap.

Microduck is now the default on every load, including with a saved lab draft.
The original full model stays visible during its first head-pose task: Look
left/right, Center head, adjustable head sliders, and local head-pose export.
The export binds the visual model hash and source revision and carries only
two head angles, visual-only scope and no execution authority. These actions
do not request admission or dispatch. A saved assembly is preserved byte for
byte and reopened explicitly with Continue saved project.

The component fixture and its task guide now live in collapsed **Advanced lab**.
They remain the qualified synthetic simulation path; the full Microduck view
does not inherit its physics, trained policy, actuator limits or evidence.
A robot dog requires its own model and integration; it is not added as a skin
over the two-joint fixture.

The extended Microduck browser exercise checks default selection with a saved
draft, explicit lab entry, head-pose presets and actual JSON download, model
identity, absence of control requests, saved-byte recovery and corrupt-model
refusal. Use the new packet
`artifacts/robotics/cw-l02-trials/2026-11-12-microduck-default-02/`
for the next observation. Earlier packet references below retain their scope.
Independent recognition/usefulness feedback and release review remain open.

The final full-robot candidate passes the source-built gallery gate (309
workspace tests, 57 focused Python checks, revised beginner/Microduck exercises
and seven gallery groups), the complete authoring/simulation browser gate
(including native verification of downloaded models), and the actual startup
gate. Reload regressions now explicitly check full-robot default followed by
saved-draft recovery. Logs are in
`artifacts/robotics/microduck-default-2026-11-12/`.

## Observed blocker

During the prepared maker trial, the participant reached the four-part practice
workspace and could not identify a robot or understand why to choose Movement.
Repeated instructions about button locations did not answer the product-purpose
question. The participant supplied a screenshot and reported that the surface
was confusing from an end developer's perspective.

The partial observation remains against the original
`2026-11-12-review-ready-01` candidate. It is not a completed trial, and the
implementation below does not retroactively resolve the participant's finding.

## Resulting workflow

1. Choose an explicitly scoped robot: the full Microduck visual explorer, or
   the two-joint synthetic practice platform robot with a simulation task.
2. Opening the practice robot brings its workspace into view. Friendly part
   names, functional descriptions and display-only joint rings explain the
   base, two motor joints and platform.
3. A task guide stays beside the robot. **Prepare tilt & return** applies the
   existing tested settings, creates the existing bounded example and checks
   its curves. It does not dispatch a simulation.
4. A dashed target chart previews the planned joint-angle changes. **Run checked
   simulation** is a separate deliberate action using the existing worker path.
5. After capture, solid measured curves appear beside the targets. **Review
   target vs. result**, recording export and project export are available from
   the guide. An interrupted capture is identified separately from completion.

The chart uses actual planned/captured angles in milliradians. It does not
exaggerate the robot's 3D pose or claim that a completed simulation followed the
target. The practice example remains at most 120 steps / 240 ms and 0.001 rad,
with the existing dt=0.002 / position kp=1 profile. Full Microduck walking
simulation, trained policy execution, physical operation and production
admission are outside this change.

The guide delegates to the existing checked controls. Current-revision checks
fence preparation; edits invalidate compiled plans, charts and capture exports.
Robot choices do not silently replace a returning draft. Explicit new-project
selection retains source/license lineage and the existing Undo behavior.
Joint rings are instructional display markers attached to parent parts; they
do not change pinned mesh bytes, assembly state, collision or simulation models.

## Verification and handoff

The extended beginner Chrome exercise reproduces the scrolled workspace from
the participant's report. It checks visible robot choices and next action,
checked preparation, target-only preview, actual recorded curves, export,
edit invalidation, saved-draft recovery, keyboard tabs and mobile containment.
Source-built CW-S04 and gallery/trial gates supply the existing simulation,
native-parity, authoring and packet regressions. Logs and screenshots are under
`artifacts/robotics/task-flow-2026-11-12/` and
`artifacts/robotics/beginner/`.

Final source-built results: **309 workspace tests**, **57 focused Python
checks**, the revised beginner and full Microduck Chrome exercises, and
**seven gallery groups** passed. CW-S04 passed **46 curve/binding/replay tests**,
**seven independent native parity tests**, the full authoring/browser gate
and its **nine gesture browser groups**. The startup gate passed **33 focused
checks and five actual startup/packet groups**, with owned startup probes of
0.766 s / 0.746 s. These are machine results, not participant timing or human
acceptance. Changed Markdown links and `git diff --check` passed.

Use the new packet
`artifacts/robotics/cw-l02-trials/2026-11-12-task-flow-ready-01/`
for the retry, after checking it against the current checkout. The older packet
preserves the initial observation and becomes stale when implementation inputs
change. Refresh the existing Studio tab to load the new build; do not clear its
browser storage. The [participant lesson](central_world_cw_l02_maker_lesson.md)
now follows robot choice → task preparation → preview → simulation → result.

The participant must still assess recognition, purpose, next-action clarity and
usefulness on this candidate. Support/rollback owners and a separate CW-L03
release decision remain required. No commit, push, publication or physical
qualification is implied by this local implementation.
