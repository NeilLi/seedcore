# CW-L02: guided maker lesson and observation sheet

Date: 2026-11-06
Status: Local guide and automated exercise available; independent maker trial pending

## Prepare and observe this candidate

Use the [local trial commands](../../../deploy/local/README.md#prepare-an-independent-maker-trial)
to build and verify the Studio, check startup dependencies and create a new
source-bound packet. The current committed candidate is `f99479a2`; the packet
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

The Studio's **Guided lesson** uses the synthetic reference and requires the
local Studio service and its pinned dependencies. No external model account is
needed. Browser draft data is saved locally; downloaded files remain with the
operator. A configured local governed service is needed only for the separate
signed-evidence inspector; the lesson's replay is an unsigned simulation capture.

1. Open the local gallery and choose **Create synthetic draft fork**.
2. In Inspect, change the name and save the draft revision.
3. In Simulation, wait for the model and apply the rehearsal preset.
4. In Moments, create the tilt/return example, validate its curves and rehearse
   it. The Stop control is available during an attempt.
5. Inspect the captured outcome and move the sample slider.
6. In DRC & BOM, recheck DRC after the settings change and download the draft
   design ZIP. Inspect the assembly's `metadata.notes` for declared source and
   license lineage and the manifest for draft scope.

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
| Inspect, fork, rename, rehearse, inspect result and export outcomes | Pending |
| Keyboard-only path, visible focus, text/readability and mobile layout | Pending |
| Stop/recovery or failure encountered and what the participant understood | Pending |
| Assistance, unexpected behavior and participant feedback | Pending |
| Downloaded ZIP/manifest and lineage inspected | Pending |
| Privacy/egress observations and unexpected prompts | Pending |
| Reviewer decision and follow-up issues | Pending |

A successful automated test, a guessed completion time, or an agent pretending
to be an independent maker does not fill this sheet. Record actual observed
results and rerun the affected gate if the lesson or supported profile changes.
