# ADR 0003: Adopt an IGX Thor Trusted Edge Profile for High-Regulation SeedCore Deployments

- Status: Proposed
- Date: 2026-04-06
- Scope: SeedCore physical execution plane for industrial, medical, and robotics edge nodes that cross the governed custody boundary
- Related: [ADR 0001: Keep the PDP Stateless and Synchronous at Decision Time](./adr-0001-pdp-hot-path.md), [Architecture Overview](../overview/architecture.md), [Zero-Trust Custody and Digital-Twin Runtime](../overview/zero_trust_custody_digital_twin_runtime.md), [Current Next Steps](../../development/current_next_steps.md), [SeedCore 2026 Execution Plan](../../development/seedcore_2026_execution_plan.md), [Agent Action Gateway Contract](../../development/agent_action_gateway_contract.md), [Draft: signed edge telemetry and twin settlement](../../development/edge_telemetry_evidence_closure_draft.md), [SeedCore 2027 Significant Direction](../../development/seedcore_2027_high_vertical_direction.md)

## Context

SeedCore's current roadmap already assumes a real physical boundary:

- 2026 remains centered on one must-win workflow: `Restricted Custody Transfer`
- the trust plane stays cloud-resident around the PDP, replay, and verification surfaces
- the Q4 pilot story already expects a Jetson AGX Orin-class edge node and hardware-in-the-loop telemetry
- the Agent Action Gateway already models a `hardware_fingerprint`
- closure paths already model signed `telemetry_refs` and transition receipts

The open architecture question is not whether SeedCore needs an edge node. It does. The question is what class of edge node SeedCore should treat as the preferred long-lived trust boundary once the product moves beyond prototype robotics and into regulated industrial, medical, or mission-critical deployments.

Recent NVIDIA IGX Thor documentation points to a materially different profile from a generic embedded GPU board:

- IGX Thor is positioned as an enterprise-grade edge AI platform for safety-critical, real-time industrial, medical, and robotics workloads with up to a 10-year lifecycle.
- The T7000 board kit adds a BMC and ConnectX-7 networking, including high-speed networking and GPU Direct RDMA validation in NVIDIA's certification program.
- The safety story is hardware-backed, including a Functional Safety Island inside Thor and a safety MCU path in the platform safety materials.
- IGX-SW 2.0 is now the production software baseline for IGX Thor, with a CUDA 13 compute stack, TensorRT 10.13, cuDNN 9.12, a Canonical-signed LTS kernel, and an NVIDIA-optimized preemptible real-time kernel.
- NVIDIA is explicitly pairing IGX Thor with AI Enterprise, long-term software support, Holoscan, Isaac, Metropolis, Triton, NIM, and selective JetPack-on-IGX flexibility.
- IGX T5000 is also positioned as a migration-friendly path for Jetson-class designs, with pin compatibility called out in the platform overview.

For SeedCore, the important implication is architectural, not promotional:

- IGX Thor looks suitable as a durable physical execution boundary
- Jetson still looks suitable as the fast-moving prototype and early pilot boundary
- neither platform replaces SeedCore's policy, delegation, execution-token, or replay model

## Decision

SeedCore will adopt a **two-profile edge strategy**:

- `Prototype Edge Profile`: Jetson-class nodes remain the default path for simulation, development, early robotics iteration, and the near-term 2026 pilot lane.
- `Trusted Edge Profile`: IGX Thor becomes the preferred production target when SeedCore is expected to govern high-consequence industrial, medical, or robotics execution and to present the node itself as part of the trust boundary.

### Decision Shape

- SeedCore's authoritative trust plane remains cloud-resident by default:
  - synchronous PDP decision
  - execution-token minting
  - governed receipt creation
  - forensic block assembly
  - replay and verification surfaces
- IGX Thor is treated as the preferred **physical execution and evidence boundary**, not as a replacement for the PDP.
- SeedCore will support rapid migration and development paths on Jetson and JetPack, but for production-grade regulated deployments it will prefer the IGX Thor lane with longer support windows, stronger remote-management posture, and clearer safety/integration story.
- When IGX Thor is used, SeedCore will consume its hardware-management and safety-adjacent signals as **policy inputs and evidence inputs**, not as standalone authorization truth.

### Operating Rules

- SeedCore will not require IGX Thor for all edge integrations in 2026.
- SeedCore will keep the current Jetson-based Q4 pilot story intact.
- SeedCore will use IGX Thor as the reference target for the 2027 "hardware-bound execution identity" expansion path.
- For IGX Thor deployments, SeedCore will prefer the IGX OS / NVIDIA AI Enterprise lane for production operations.
- `JetPack on IGX` remains acceptable for T5000-based prototyping, migration, and robotics experimentation, but it should not be treated as the default production lane.
- T7000 deployments should assume `IGX OS` as the software baseline because NVIDIA's current stack-options guidance says JetPack on IGX is not supported on T7000.

## Decision Boundaries

This ADR does not require:

- moving the final PDP decision onto the edge node
- treating NVIDIA functional-safety features as a substitute for SeedCore authorization
- immediate ingestion of every BMC, safety MCU, or firmware artifact into the current forensic schema
- immediate replacement of the Jetson-based pilot lane
- standardizing on one robotics middleware or one VLA stack

This ADR does require that SeedCore's future production-grade physical lane be designed around **hardware-bound identity, signed evidence, remote-manageable edge operations, and long-lived deployment support**, with IGX Thor as the preferred target for that lane.

## Software Stack Positioning

The software stack matters to this decision because SeedCore is not choosing only a board. It is choosing the operational substrate that shapes determinism, evidence capture, patching, remote management, and support boundaries.

### Preferred Production Lane on IGX Thor

For production-grade trusted-edge deployments, SeedCore should treat the current IGX-SW 2.0 lane as the reference baseline:

- `IGX OS` as the production operating environment
- `NVAIE-IGX` as the enterprise support and validated-configuration lane
- CUDA / cuDNN / TensorRT as the local inference substrate
- Triton and NIM as the model-serving bridge from cloud development to edge execution
- Holoscan / Isaac / Metropolis as domain SDKs above the compute substrate
- BMC + firmware bundle management as part of the node operations contract

The current IGX-SW 2.0 release notes also list concrete platform-management versions that matter operationally:

- `BMC Firmware`: `5.4`
- `MCU Firmware`: `2.00.02`

This is a much better match for SeedCore than treating the edge node as "just Linux plus a robot app."

### Software Path Rules

- `T7000`: default to IGX OS plus NVAIE-IGX for production. This should be treated as the canonical trusted-edge software lane.
- `T5000 / Developer Kit Mini`: allow either IGX OS or JetPack on IGX depending on whether the work is supportability-first or customization-first.
- `Jetson`: continue as the prototype and early pilot path where development speed matters more than enterprise support guarantees.

### Why the IGX-SW 2.0 Stack Is Relevant to SeedCore

The current release gives SeedCore several properties that map directly onto its trust model:

- a real-time kernel path for bounded sensor and actuation behavior
- a signed and supportable OS lane suitable for long-lived regulated environments
- a current AI compute stack for running local policy-adjacent inference, perception, and safety workloads
- out-of-band management through the BMC for firmware, power, and telemetry operations
- a high-speed networking and sensor-ingest story through ConnectX-7 / DOCA-OFED / RDMA-oriented workflows

## Software Stack Consequences for SeedCore

The software stack decision implies a few concrete architecture rules.

### 1. Separate Deployment Lanes by Intent

SeedCore should explicitly separate:

- `prototype lane`: Jetson / JetPack
- `custom trusted-edge lane`: T5000 with JetPack on IGX when deep kernel or BSP customization is unavoidable
- `production trusted-edge lane`: T7000 or T5000 on IGX OS with NVAIE-IGX

That split keeps experimentation from quietly becoming the production default.

### 2. Treat Software-Lane Identity as Evidence-Relevant

For trusted-edge enrollments, SeedCore should eventually record software-lane metadata such as:

- `os_lane`: `igx_os` or `jetpack_on_igx`
- `release_ref`
- `kernel_ref`
- `driver_ref`
- `bmc_fw_ref`
- `smcu_fw_ref`
- `security_posture`

This does not make software version a policy decision by itself, but it does make the node posture replay-visible and auditable.

### 3. Prefer ConnectX / RDMA-Oriented Capture for High-Value Sensor Paths

Where the physical handshake depends on high-rate imaging or low-latency sensor ingest, SeedCore should prefer the ConnectX-backed path rather than assuming generic Ethernet is equivalent. This is especially relevant for Holoscan-class pipelines and GPU-resident sensor flows.

### 4. Model Current Release Limitations Explicitly

The ADR should not assume every marketed capability is ready for immediate SeedCore use. In the current IGX-SW 2.0 release, some constraints are directly relevant:

- MIG is not supported in this release and should not be part of the SeedCore isolation story yet.
- X11 is the primary supported window system for production workloads in this release; Wayland assumptions should be avoided in operator-console or local-HMI plans.
- The base image does not enable a host firewall by default; provisioning must harden this before treating the node as production-ready.
- NVIDIA recommends applying Ubuntu security updates after initial setup; SeedCore runbooks should treat this as required bring-up hygiene.
- Shipped IGX kits have secure boot disabled by default; if SeedCore wants to claim a hardened trusted-edge profile, secure-boot posture must be explicitly provisioned and recorded rather than assumed.

These are not reasons to reject IGX Thor. They are reasons to model the software lane honestly.

## Why

This decision is the best fit for the current repository and roadmap because it strengthens the physical trust boundary without forcing SeedCore to abandon its existing cloud trust-plane architecture.

### Why IGX Thor fits the SeedCore direction

- SeedCore already wants the physical node identity to matter. The gateway contract, telemetry work, TPM maturity work, and 2027 direction all point toward exact hardware-bound authority rather than generic "robot role" authority.
- SeedCore already separates judgment from authority. IGX Thor improves the deployment substrate for perception, control, and evidence capture, but it does not pressure SeedCore to collapse policy into the robotics stack.
- SeedCore already needs better closure evidence. IGX Thor's positioning around real-time sensor processing, networking, safety, and lifecycle support aligns better with a replayable forensic handshake than an ad hoc edge box.

### Why a two-profile strategy is better than a single hardware bet

- Jetson remains cheaper, faster, and more iteration-friendly for early product work.
- IGX Thor is better aligned with the environments SeedCore ultimately wants to enter: industrial, medical-adjacent, and regulated robotics deployments.
- The platform overview and JetPack-on-IGX direction reduce migration risk by keeping the software path adjacent rather than discontinuous.

### Why SeedCore should not move the trust plane fully onto IGX Thor

- ADR 0001 already establishes that the core authorization boundary should remain synchronous, deterministic, and tightly governed over pinned inputs.
- SeedCore's verification, replay, and operator surfaces are already centered in the cloud trust slice.
- Pushing the full trust plane onto the edge would make rollout, replay, and multi-party governance harder before it makes them better.

## Consequences

Positive:

- SeedCore gets a clearer 2027 production story for industrial, medical, and robotics edge deployments.
- The roadmap can preserve Jetson for near-term pilots while still naming a stronger long-term trusted edge target.
- Hardware-bound identity, signed telemetry, and physical-evidence closure become easier to explain as first-class product requirements instead of optional hardening.
- The architecture gains a more credible remote-operations story through BMC-managed nodes and certified system validation.
- High-bandwidth sensor and multi-model physical AI deployments have a more realistic substrate than a generic embedded dev board.

Negative:

- SeedCore now needs to maintain two explicit edge profiles rather than a single generic edge story.
- The team will need a sharper contract for device enrollment, hardware identity, and evidence provenance across Jetson and IGX lanes.
- The NVIDIA-specific lane increases ecosystem dependence and may narrow portability if not abstracted carefully.
- IGX Thor-class systems raise hardware cost, integration overhead, and certification coordination compared with simpler Jetson pilots.
- Some IGX capabilities are only useful if SeedCore actually models and persists the related evidence or health state.

## Implementation Notes

SeedCore should preserve the current trust-plane shape and introduce the IGX Thor lane through additive profile work.

### 1. Freeze an Edge Enrollment Contract

The current `hardware_fingerprint` shape is the right starting point, but the trusted-edge lane should likely add explicit profile fields such as:

- `device_profile`
- `platform_family`
- `firmware_measurement_ref`
- `facility_ref`
- `zone_scope`
- `allowed_capabilities`

The important rule is that allow-time authority must bind to a concrete node identity, not only an agent role.

### 2. Build One Thin Edge Trust Adapter First

The first adapter should stay narrow:

- validate scoped `ExecutionToken` from SeedCore
- verify node identity and scope match before actuation
- sign local telemetry and closure evidence
- post canonical closure evidence back to SeedCore

That adapter should be compatible with the current Jetson pilot lane but shaped so IGX Thor becomes the preferred production target without changing the cloud trust plane.

### 3. Extend the Forensic Handshake Selectively

The current telemetry and forensic-block work should eventually add room for trusted-edge-specific fields such as:

- device identity hash
- authority scope hash
- firmware or software lane reference
- safety-monitor or node-health reference

These should be added only where they materially improve replay and quarantine decisions.

### 4. Keep Safety and Governance Separate

IGX Thor's safety features are valuable, but SeedCore should treat them as deployment and evidence primitives, not as business authorization primitives.

Operationally:

- safety monitors may constrain whether execution is admissible
- SeedCore still decides whether the action is allowed
- the replay surface should explain both policy outcome and physical/safety convergence

### 5. Use Software Lanes Intentionally

- Jetson / JetPack remains the fast-moving prototype lane.
- JetPack on IGX can be used on T5000 when migration speed or kernel/BSP customization matters.
- IGX OS / NVIDIA AI Enterprise should be the default production lane when supportability, certification posture, lifecycle stability, and signed-kernel discipline matter more than maximum experimentation speed.

### 6. Turn Software Posture into Enrollment and Quarantine Inputs

SeedCore should eventually be able to reason over trusted-edge software posture in a bounded way, for example:

- deny or quarantine closure evidence from unenrolled software lanes
- flag stale BMC / SMCU / kernel references as operator-visible trust gaps
- require stronger review when disk-encryption, secure-boot, or firmware posture does not match the enrolled node profile

That is a better use of the IGX software stack than trying to collapse all safety and OS semantics into one binary policy switch.

## Follow-On Work

- Freeze a SeedCore edge enrollment schema for `Jetson` and `IGX Thor` profiles.
- Implement the first `SeedCore Edge Trust Adapter v0.1` against the current Agent Action Gateway and closure surfaces.
- Extend the signed edge telemetry and forensic-block contracts with optional device-identity and software-lane metadata.
- Add node-profile fields for IGX software lane, kernel/driver versions, and firmware posture in the enrollment and closure surfaces.
- Add adversarial drills for cross-node token replay, stale node health, telemetry tamper, and mismatched closure node identity.
- Add hardening runbook steps for IGX OS provisioning, including firewall enablement, required package updates, and secure-boot / encrypted-rootfs posture capture where applicable.
- Keep the 2026 Q4 pilot on the Jetson lane unless IGX hardware is actually available, but define the IGX Thor lane in docs and contracts now so 2027 work does not reopen the trust model.

## Alternatives Considered

### Keep Jetson as the Only Edge Story

Rejected as the long-term default. It is adequate for development and early pilot work, but it leaves SeedCore without a strong production answer for regulated, high-consequence, remotely managed edge environments.

### Move the Full SeedCore Trust Plane onto IGX Thor

Rejected. SeedCore's advantage is the cloud-resident governed trust slice with replayable evidence and multi-party authorization semantics. IGX Thor should strengthen the physical boundary, not absorb the whole trust plane by default.

### Stay Fully Hardware-Agnostic and Name No Preferred Trusted Edge Platform

Rejected. The current roadmap already points toward hardware-bound execution identity. Refusing to name a preferred trusted-edge target would weaken the architecture at the exact point where SeedCore needs more clarity.

### Treat NVIDIA Safety Infrastructure as a Replacement for SeedCore Governance

Rejected. Functional safety and system certification are critical deployment properties, but they do not replace SeedCore's delegation, policy evaluation, execution-token, or forensic replay contracts.

## References

External:

- [NVIDIA IGX Thor Powers Industrial, Medical, and Robotics Edge AI Applications](https://developer.nvidia.com/blog/nvidia-igx-thor-powers-industrial-medical-and-robotics-edge-ai-applications/)
- [NVIDIA IGX Platform Overview](https://docs.nvidia.com/igx/user-guide/latest/OV/introduction.html)
- [IGX-SW 2.0 Production Release](https://docs.nvidia.com/igx/user-guide/latest/software-releases/software-release-2-0-thor-notes-pr.html)
- [IGX Software Stack Options](https://docs.nvidia.com/igx/user-guide/latest/SW/igx-software-stack-options.html)
- [JetPack on IGX](https://docs.nvidia.com/igx/user-guide/latest/SW/using-jetson-linux-bsp.html)
- [NVIDIA AI Enterprise Software Stack for IGX](https://docs.nvidia.com/igx/user-guide/latest/NVAIE/nvaie.html)
- [Using the BMC — NVIDIA IGX Developer Guide](https://docs.nvidia.com/igx/user-guide/latest/bmc.html)
- [SMCU NFW — NVIDIA IGX Developer Guide](https://docs.nvidia.com/igx/user-guide/latest/SMCU/smcu.html)
- [Secure Boot for IGX](https://docs.nvidia.com/igx/user-guide/latest/SW/security/secure-boot.html)
- [Enable Disk Encryption for IGX Thor](https://docs.nvidia.com/igx/user-guide/latest/SW/security/fde.html)
- [NVIDIA IGX Certification Program](https://docs.nvidia.com/igx/user-guide/latest/NVAIE/thor-certification.html)
- [Holoscan Sensor Bridge](https://docs.nvidia.com/holoscan/sdk-user-guide/holoscan_sensor_bridge.html)
- [NVIDIA Halos for Outside-In Safety Agents Early Access](https://developer.nvidia.com/halos-for-outside-in-safety-agents-early-access)
- [NVIDIA IGX](https://developer.nvidia.com/igx)

Internal:

- [README](../../../README.md)
- [Current Next Steps](../../development/current_next_steps.md)
- [SeedCore 2026 Execution Plan](../../development/seedcore_2026_execution_plan.md)
- [Agent Action Gateway Contract](../../development/agent_action_gateway_contract.md)
- [Draft: signed edge telemetry and twin settlement](../../development/edge_telemetry_evidence_closure_draft.md)
- [TPM Fleet Rollout Maturity Decision Memo](../../development/tpm_fleet_rollout_maturity_decision_memo.md)
- [SeedCore 2027 Significant Direction](../../development/seedcore_2027_high_vertical_direction.md)
