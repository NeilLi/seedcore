# Demo Presentation Script

## Opening

Hi, I am Neil Li, founder and architect of SeedCore.

My profile is Ex-Motorola and Alibaba. UESTC.

SeedCore is a governed execution runtime for autonomous systems.

The core thesis is simple: AI intent should not automatically become execution
authority. As agents and robotic systems begin initiating real-world actions,
enterprises need a way to prove those actions were authorized, scoped,
physically evidenced, and replay-verifiable. SeedCore is built to provide that
trust/runtime layer.

## What I Will Show

In this demo, I will show a Restricted Custody Transfer workflow using a
high-value rare collectible shoe as the commercial scene.

This is not a sneaker marketplace. It is a compact proof that SeedCore can
govern high-value physical commerce when authentication, delegated AI intent,
custody movement, and evidence closure must all agree before execution.

## Step 1: Source Registration

First, the rare shoe is registered as a governed source asset.

The registration includes product reference, seller reference, provenance
class, style code, condition grade, authentication payload, and NFC binding.

SeedCore does not treat authentication as a simple boolean. It preserves the
authentication evidence packet as an admissibility input. No transfer authority
exists until the source registration is approved.

## Step 2: Agent Intent

Next, a buyer-side or collector agent submits a purchase and custody-transfer
proposal.

This intent is advisory only. The agent cannot move the asset directly.

The request is normalized through the Agent Action Gateway v1 contract, where
listing, quote, order, declared value, buyer delegation, and destination scope
are bound into one workflow.

## Step 3: Policy Evaluation

SeedCore's Policy Decision Point checks whether the action is admissible.

It verifies that authentication is approved and fresh, the asset is not
quarantined, buyer delegation is active, the approval envelope is valid, the
declared value is within policy, and product, quote, and order references all
bind to the same asset.

If anything fails, the system denies or quarantines the workflow.

## Step 4: Bounded Authority

Only after the policy gates pass does SeedCore mint bounded custody authority.

The authority is scoped to the exact asset, actor or device, origin and
destination zone, allowed operations, evidence requirements, and validity
window.

This is the key distinction: AI intent does not equal execution authority.

## Step 5: Physical Handoff

During physical handoff, the vault or courier edge node presents the scoped
authority.

The edge scan reads the NFC or equivalent hardware anchor. The scan telemetry
is signed by the authorized device.

Supporting evidence such as weight, seal, image, or video references can also
be attached. The closure request must bind this telemetry back to the original
evaluated asset.

## Step 6: Result Verification

At delivery, the receiving scan produces final signed telemetry.

The result verifier validates the full chain: source registration,
authentication evidence, buyer intent, bounded authority, origin telemetry,
delivery telemetry, and final closure.

If the proof chain is consistent, the custody transfer closes. If there is an
NFC clone, cross-asset replay, stale telemetry, missing approval, or condition
drift, the workflow fails closed into quarantine.

## Step 7: Proof Surfaces

Finally, SeedCore renders two proof surfaces.

The public proof view shows a narrow legitimacy surface: product identity,
provenance class, authentication verdict, current state, and proof hash.

The operator forensic view contains the full replay bundle: telemetry
references, signer provenance, policy decisions, verifier outcomes, and
evidence bundle. Sensitive data like raw NFC UID or microscopic authentication
evidence stays out of the public projection.

## Closing

This demo shows the core SeedCore pattern: agent intent -> policy admission ->
bounded authority -> signed physical evidence -> replayable proof.

The rare-shoe scene is only the first vertical. The same runtime pattern can
extend to luxury goods, logistics, robotics handoff, industrial asset custody,
lab samples, and regulated physical workflows.

SeedCore's goal is to become the trust/runtime layer for autonomous systems.
