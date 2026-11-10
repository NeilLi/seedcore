# CW-L02: guided maker lesson and observation sheet

Date: 2026-11-10
Status: Local guide and automated exercise available; independent maker trial pending

## Prepare and observe this candidate

Use the [local trial commands](../../../deploy/local/README.md#prepare-an-independent-maker-trial)
to build and verify the Studio, check startup dependencies and create a new
source-bound packet. The current committed candidate is `b71d022d`; the packet
also hashes the current build and records any uncommitted implementation changes.
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

The Studio opens the full Microduck visual explorer on first use. A returning
user may see a saved project; choose **Meet Microduck** to return to the explorer.
The head sliders change only the displayed pose. They do not run a Microduck
physics simulation, validate balance, or create an editable assembly.

No external model account is needed. Browser draft data is saved locally;
downloaded files remain with the operator. The separate signed-evidence inspector
requires a configured local governed service; the lesson recording is unsigned.

1. In **Meet Microduck**, turn the view, try both head sliders, and use
   **Reset pose & view**. Explain what you think these controls do. A successful
   visual task is separate from the following simulation task.
2. Under **Your first robot project**, choose **1. Choose a practice robot**.
   This opens your own synthetic draft, with source/license lineage. The
   block-shaped practice model is deliberately separate from the full Microduck.
3. In **My build**, change **Project name**, then choose **Save name**.
4. Choose **2. Set up the simulation**. It applies the tested practice settings.
   Wait until **3. Make a movement** is available, then choose it.
5. In **Movement**, select a size, choose **Create tilt & return**, **Check
   movement**, then **Try movement**. The 0.24-second lesson uses tiny targets
   (at most 0.001 rad); inspect the recording values rather than expecting a
   large visible animation. **Stop movement** is available during startup/run.
   If it finishes before a stop can be exercised, record “not exercised”; do
   not infer successful stopping from a completed run.
6. Choose **4. Review and save**. Move the recording slider and compare target
   and measured joint positions. **Save recording (.json)** keeps the unsigned
   capture; **Save project file** keeps the assembly, not the recording.
7. In **Check & parts**, choose **Check again**, then **Save design pack (.zip)**.
   Inspect `assembly.sc-assembly.json` → `metadata.notes` for source/license
   lineage and `manifest.json` for draft scope. Unknown wiring/cost/physical
   findings remain visible; exporting a draft does not approve a physical build.
8. Choose **Meet Microduck**, then **Continue saved project** and confirm that
   the renamed project returns. Do not clear browser storage as a recovery step.

Changing size or editing a project clears older validation and recordings.
Create/check a fresh movement before trying it again. Technical JSON, exact
positions and service tools remain available under **Show technical details**
and their individual expandable sections.

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
