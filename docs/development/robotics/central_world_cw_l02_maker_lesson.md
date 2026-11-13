# CW-L02: guided maker lesson and observation sheet

Date: 2026-11-12
Status: Local guide and automated exercise available; independent maker trial pending

## Prepare and observe this candidate

Use the [local trial commands](../../../deploy/local/README.md#prepare-an-independent-maker-trial)
to build and verify the Studio, check startup dependencies and create a new
source-bound packet. The source baseline is `b86fd3bb`; the 12 November task-flow
fix is an explicit local diff. The packet hashes the current build and records
the uncommitted implementation changes.
The packet is a set of local references and instructions, not a standalone app.

The observer starts a stopwatch when the participant begins, records assistance
without coaching in advance, and writes the actual browser/device and outcomes
into the packet's blank `observation.json`. Keep setup time separate from lesson
time. Record failures or interventions as they happen. Do not include names or
private account information. If a task cannot be completed, record that outcome
instead of substituting an automated test or estimate.

Before starting, verify the packet against the checkout; repeat after filling
the observation. `verify` checks source bindings and completeness, not the truth
of manually supplied statements. All generated packets retain a deferred release
decision and grant no execution authority.

## Participant task

The Studio opens the full Microduck visual explorer on every page load, including
when a lab project is saved. **Continue saved project** explicitly reopens that
project; choosing **Meet Microduck** returns to the complete robot.
The head sliders change only the displayed pose. They do not run a Microduck
physics simulation, validate balance, or create an editable assembly.

No external model account is needed. Browser draft data is saved locally;
downloaded files remain with the operator. The separate signed-evidence inspector
requires a configured local governed service; the lesson recording is unsigned.

1. Follow **Make Microduck look around**: choose **Look left**, then **Center
   head**. Try **Look right**, both head sliders, and **Reset pose & view**.
   Use **Save head pose (.json)** and inspect the two saved head angles and
   model identity. This is a visual pose file, not a physics recording or
   executable robot command. Explain what the controls do and whether the task
   is understandable. A successful visual task is separate from simulation.
2. Open **Advanced lab** for the assembly/simulation portion of the trial.
   In **Practice platform robot**, choose **Open robot & start task**.
   It opens your own synthetic draft and brings the robot workspace into view.
   The left panel identifies its fixed base, two motor joints and top platform;
   colored rings mark its turning joints. This is a simplified simulation model,
   separate from the full Microduck visual explorer.
3. Read the task guide beside the robot: **Tilt the platform, then return**.
   Explain what you expect to happen and why you would use this task. Choose
   **Prepare tilt & return**. It applies the tested settings, creates the tiny
   target curves and checks them; it does not run the simulation.
4. Inspect **Preview: the planned tilt and return**. Blue and orange dashed
   lines show the two joint targets. Describe the expected joint behavior.
   Choose **Run checked simulation** when you are ready.
5. Choose **Review target vs. result**. Compare the dashed planned targets with
   solid measured positions. The 0.24-second run uses targets at most 0.001 rad;
   the chart shows their actual values in milliradians so the 3D view need not
   exaggerate the motion. Completing a simulation does not establish that its
   joints followed their targets. **Stop simulation** is available in the task
   guide during startup/run. If it finishes before you can exercise Stop, record
   “not exercised”; do not infer successful stopping from a completed run.
6. Drag the recording slider to inspect individual samples. Use the task guide's
   **Save recording (.json)** and **Save project file** buttons. In **My build**,
   change **Project name**, then choose **Save name**. This is an edit: prior
   simulation results clear and the guide asks you to prepare a fresh task.
7. In **Check & parts**, choose **Check again**, then **Save design pack (.zip)**.
   Inspect `assembly.sc-assembly.json` → `metadata.notes` for source/license
   lineage and `manifest.json` for draft scope. Unknown wiring/cost/physical
   findings remain visible; exporting a draft does not approve a physical build.
8. Choose **Meet Microduck**, then **Continue saved project** and confirm that
   the renamed project returns. Refresh once: Microduck should be the default,
   and **Continue saved project** should recover the same draft. Do not clear
   browser storage as a recovery step.

Changing size or editing a project clears older validation and recordings.
Use **Prepare tilt & return** again before another run. Individual movement
controls remain in **Tilt & return**; the advanced JSON, exact positions and
service tools remain under **Show technical details** and expandable sections.

The source-built Chrome exercise performs this sequence and independently
inspects the downloaded ZIP. This automated run does not substitute for a person
using the lesson without coaching.

## Independent adult-maker observation

Ask an adult who has not built the feature to follow the on-screen guide on a
named browser and device. Record only the details needed for the task; do not
record names, credentials, camera images or private account data in this repo.
Observe before offering help. Record each intervention and its reason.

| Observation | Result to record |
| --- | --- |
| Source revision and exact build/source pins | Pending |
| Browser/version, OS and date | Pending |
| Time to start the local service and reach the gallery | Pending |
| Microduck pose/reset, practice copy, rename, run, replay, export and resume outcomes | Pending |
| Keyboard-only path, visible focus, text/readability and mobile layout | Pending |
| Stop/recovery or failure encountered and what the participant understood | Pending |
| Assistance, unexpected behavior and participant feedback | Pending |
| Downloaded ZIP/manifest and lineage inspected | Pending |
| Privacy/egress observations and unexpected prompts | Pending |
| Reviewer decision and follow-up issues | Pending |

A successful automated test, a guessed completion time, or an agent pretending
to be an independent maker does not fill this sheet. Record actual observed
results and rerun the affected gate if the lesson or supported profile changes.
