# Governed Robot Skill Packages

Date: 2026-09-21
Status: Proposed developer contract; no package loader, sandbox or studio shipped by this document

## Unit Of Integration

A skill is a versioned behavior proposal with declared dependencies,
parameters, permissions and outcome evidence. A persona is presentation or
planning configuration. Neither is a principal, delegation or execution token.

The current [`RobotProposal`](../../../src/seedcore/robotics/contracts.py) carries
a skill name, arguments, duration and observation sequence. It is an advisory
team contract, not an installable skill package. The package mapping below
needs a separately versioned schema and admission implementation.

The [customer delivery model](robot_solution_delivery.md) describes the function
a person buys or uses. One such solution may compose multiple skills plus an
interaction flow, hardware profile and support instructions. Reusable solution
templates must preserve the customer's outcome criteria and each skill's
independent authority/evidence boundary. Customization does not permit wider
motion or data access without reviewed grants.

## Proposed Manifest Contents

| Field group | Required content | Enforcement owner |
| --- | --- | --- |
| Identity | Package ID/version/digest, publisher identity, provenance | Trusted package admission and artifact store |
| Compatibility | Robot/runtime profiles, policy/model digests, adapter version | Admission and edge compatibility checks |
| Inputs | Typed parameters, units, frames, finite bounds, observation freshness | Gateway validation and edge enforcement |
| Requested capabilities | Motion operations, sensors, audio output, network destinations, storage | PDP intersects requests with owner grants and device profile |
| Execution limits | Maximum duration, workspace reference, supported speed/acceleration limits | Edge session and native controller |
| Data handling | Capture purpose, local/remote processing, retention and export | Sensor/media boundary and isolated process environment |
| Outcomes | Completion, interruption and failure predicates; mandatory telemetry | RESULT_VERIFIER using authenticated evidence |
| Recovery | Local stop behavior, rollback artifact, restart policy | Reviewed controller and deployment profile |
| Validation | Simulator fixtures, denial cases, fault traces and hardware profile evidence | Conformance checks and promotion review |

For a first bounded-move skill, request only reviewed velocity/duration inputs
and the state needed to evaluate the attempt. Camera streaming, microphone
access, arbitrary network access and policy installation are separate
capabilities, absent unless required and explicitly granted. Numeric physical
limits come from the selected robot profile rather than a generic manifest
example copied across devices.

## Grants And Sandboxing

Relationship-based authorization identifies who may delegate which capability
to which Agent for which robot. Parameter validation supplies the physical and
data limits. A manifest is a request, not a grant; a publisher signature proves
package provenance, not permission to execute.

The effective grant must be no broader than the intersection of owner/operator
delegation, deployment policy, enrolled endpoint capability and package request.
Unsupported or unknown requirements fail closed. Child skills cannot expand
the parent's scope, lifetime or data access. Human approval must be bound to
the reviewed version and scope; a generic approval in conversation is not a
reusable execution credential.

Permission declarations require actual isolation: the skill process must lack
raw motor-device/control-socket access, policy-writing credentials and signing
keys; sensor, network and filesystem access must match the grant. Select the
process/container and OS enforcement mechanisms for the target board and test
escape/bypass cases. “ReBAC sandbox” is not an implemented isolation mechanism.

## Package Lifecycle

```text
author -> validate manifest/artifacts -> simulate and fault-test
       -> reviewed enrollment/install -> separately admit a skill attempt
       -> collect evidence -> evaluate candidate revision
       -> separately reviewed promotion or rollback
```

Installation never authorizes motion. Admission binds a specific package and
policy/model digest. A permission expansion requires renewed review; updates
cannot alter active sessions in place. Revoke/drain and reconcile affected
sessions before replacing behavior. A rollback is a deployment action subject
to its own gate and compatibility checks.

Learning produces a new candidate artifact and evaluation report, not broader
authority. Personality tuning cannot alter motion limits, privacy grants,
stop behavior or evidence requirements. Retain the previous admitted artifact
and the corresponding evidence for comparison.

## Delivery Order

After one Microduck session works end to end, turn its accepted and rejected
cases into a package conformance fixture. Prove a second skill can reuse the
same authority/evidence path before building a visual studio. A useful studio
should show requested versus granted permissions, simulation results, local
stop behavior and actual verifier outcomes.

Public distribution, unreviewed third-party installation and a marketplace
remain future decisions. The next implementation milestones remain
[M0–M5](../current_next_steps.md); this proposal does not add a new prerequisite
to the first read-only adapter.
