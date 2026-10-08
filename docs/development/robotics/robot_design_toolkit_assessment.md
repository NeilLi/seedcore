# Robot design toolkits for SeedCore

Date: 2026-10-08
Status: Accepted research recommendation; CAD adapters and external model imports planned

## Decision and scope

Prioritize **Onshape + Rhoban's onshape-to-robot** for a direct CAD-to-MuJoCo
workflow, then **FreeCAD + RobotCAD** for open-source mechanical authoring and
agent-assisted assembly. The user accepted these recommendations for SeedCore's
general robot-development workbench. This document preserves the assessment;
it does not record an installation, adapter implementation or hardware acceptance.

These are selections for engineering fit, not a demonstrated ranking of the
world's most precise CAD tools. The research found no comparative benchmark
establishing that claim. Export fidelity and agreement with measured hardware
are the useful acceptance targets.

The [MuJoCo workbench](mujoco_development_workbench.md) currently generates
primitive mechanisms and supports bounded experiments through internal agent
tools. External MJCF/URDF packages, CAD integration and a general browser
workspace remain planned. This assessment supports that next step without
changing the [Microduck integration gates](microduck_integration_plan.md).

## Selected toolkits

| Toolkit | Recommended role | Simulation path | Qualification gap |
| --- | --- | --- | --- |
| [Onshape + onshape-to-robot](https://github.com/Rhoban/onshape-to-robot) | First CAD export integration | Direct MuJoCo MJCF; also URDF/SDF | Onshape API access, assembly conventions, exporter configuration and actual model validation |
| [FreeCAD + RobotCAD](https://github.com/drfenixion/freecad.robotcad) | Local mechanical authoring and agent-assisted assembly | URDF/xacro, followed by a qualified MuJoCo import step | Adapter, actuator/sensor mapping and platform qualification; no native MJCF export established by this review |

### Onshape + onshape-to-robot

Rhoban maps assembly mates to robot joints and limits. Named frames become
MuJoCo sites, while supported closed mechanisms use equality constraints.
Its MuJoCo exporter exposes actuator, damping, friction and contact settings.
These are useful foundations for arms, legs and mechanisms beyond SeedCore's
current serial primitive chains.
[Design conventions](https://onshape-to-robot.readthedocs.io/en/latest/design.html),
[MuJoCo exporter](https://onshape-to-robot.readthedocs.io/en/latest/exporter_mujoco.html).

The robot representation includes mass, center of mass and inertia expressed
in the required frame. That data needs validation against the intended physical
assembly, including purchased components and assigned materials.
[Dynamics representation](https://github.com/Rhoban/onshape-to-robot/blob/master/onshape_to_robot/robot.py).

OpenSCAD approximations and CoACD convex decomposition support separate visual
and collision geometry. Export configuration can identify an Onshape document
version rather than a changing workspace. SeedCore should record that version,
the exporter revision and all export settings with each model package.
[Processors](https://onshape-to-robot.readthedocs.io/en/latest/processors.html),
[configuration](https://onshape-to-robot.readthedocs.io/en/latest/config.html).

The exporter is open source; the workflow still depends on Onshape account/API
access. It requires deliberately prepared assemblies, rather than converting
every CAD constraint without interpretation.
[Authentication and setup](https://onshape-to-robot.readthedocs.io/en/latest/getting_started.html).

### FreeCAD + RobotCAD

RobotCAD provides part authoring, links and joints, separate physical/visual/
collision representations, and mass, center-of-mass and inertia calculations
from materials or specified mass. Its documented output centers on URDF/xacro
and ROS 2/Gazebo packages. A MuJoCo adapter must explicitly handle the supported
subset and report unsupported controller or sensor semantics.
[Capabilities and export scope](https://github.com/drfenixion/freecad.robotcad).

Its MCP interface offers a concrete connection point for SeedCore agents:
creating links and joints, positioning components, assigning materials,
calculating inertia and inspecting snapshots. FreeCAD must remain running with
the server enabled; the documented interface is not a standalone headless CAD
service. Integration with SeedCore has not been exercised.
[MCP interface](https://github.com/drfenixion/freecad.robotcad/blob/main/docs/mcp_agent.md).

The documented tested setup emphasizes Ubuntu and Windows/WSL. Qualify the
selected FreeCAD, RobotCAD and Python versions on the intended worker platform;
macOS support for this complete workflow was not established by the review.
[Installation and compatibility](https://github.com/drfenixion/freecad.robotcad).

## Corrections and supporting references

- Rhoban's cylindrical-mate mapping produces a revolute joint; it does not
  automatically preserve both cylindrical degrees of freedom.
  [Joint conventions](https://onshape-to-robot.readthedocs.io/en/latest/design.html).
- The supplied SolidWorks link identifies
  [ros/solidworks_urdf_exporter](https://github.com/ros/solidworks_urdf_exporter),
  not a combined SolidWorks/Fusion 360 converter. Neither that reference nor the
  two selected tools establishes a turnkey USD/Isaac Sim pipeline for SeedCore.
- Use [Rhoban's examples](https://github.com/Rhoban/onshape-to-robot-examples)
  as conversion fixtures, with their settings inspected. Some examples disable
  collisions or use approximations; successful loading alone is not evidence
  of physical accuracy.
- **OpenArm is a candidate reference robot**, separate from the two design
  toolkits. Its [manufacturing CAD](https://github.com/enactic/openarm_hardware)
  and [MuJoCo assets](https://github.com/enactic/openarm_mujoco) provide a useful
  model-package test case. The MuJoCo repository also documents a browser viewer.
  Pin matching hardware/model revisions before comparing them.

## Proposed SeedCore integration sequence

1. **Import a versioned MJCF package.** Start with a reviewed Rhoban export and
   an asset manifest containing source identity, CAD configuration, exporter
   revision, mesh hashes, units, frames and declared joint/actuator limits.
   Define supported assets and model features explicitly.
2. **Check conversion fidelity.** Compare link masses, centers of mass and full
   inertia tensors in matching frames; compare forward-kinematic poses at
   multiple joint configurations. Inspect limits, collision coverage and any
   closed-chain constraint residuals. Record tolerances before evaluating a
   candidate, and report unsupported or omitted features.
3. **Run bounded experiments.** Preserve initial state, engine settings, task
   and acceptance criteria across comparisons. Record warnings, contact behavior,
   actuator saturation and measured outcomes alongside model identity.
4. **Add RobotCAD authoring tools.** Route selected document-editing operations
   through SeedCore's agent tool boundary. Produce reviewable CAD changes,
   export a new candidate and compare it against the baseline. CAD document
   mutations require their own scoped interface; the existing ephemeral
   simulation tools do not provide one.
5. **Calibrate against hardware.** Measure relevant actuator response, friction,
   backlash, latency and manufacturing variation. Keep model assumptions and
   experimental uncertainty visible when judging transfer to a real robot.

The first deliverable should be one imported mechanism with a reproducible
conversion report and experiment, before broadening the supported CAD/model
surface. A detailed mesh or a successful MuJoCo compilation is insufficient
evidence of hardware fidelity.

## Authority and evidence boundaries

Agents may propose designs, request scoped CAD edits, run admitted development
tools and explain experiment results. CAD output and simulation criteria do not
authorize physical motion, controller deployment or policy changes. Hardware
execution retains accountable Agent intent, PDP admission, bounded non-revoked
tokens/sessions, local enforcement and independent evidence closure.

Preserve failed checks and their diagnostics. Repeated deterministic failure
requires review of the verifier/runbook evidence rather than autonomous changes
to the acceptance threshold. See the [execution contract](robot_execution_contract.md)
and [policy gates](../policy_gate_matrix.md).

## Research provenance and verification limits

This assessment archives the user-supplied shortlist and the subsequent source
review on **2026-10-08**. References point to upstream default branches and
`latest` documentation as reviewed on that date; no immutable upstream commit
snapshot was captured for this research. Recheck and pin revisions before
implementation. The linked sources support their associated capability claims;
the selection order and SeedCore sequence are engineering recommendations.

No CAD toolkit was installed or exercised for this assessment. No comparative
precision benchmark, external-model import qualification, macOS RobotCAD test,
physical calibration or hardware acceptance was performed. Existing MuJoCo
workbench tests cover their documented primitive-model scope only.
