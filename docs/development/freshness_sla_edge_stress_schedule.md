# Freshness SLA Edge Stress Schedule

Date: 2026-06-10
Status: Working schedule for telemetry freshness stress lanes

## Purpose

This schedule turns the hardware freshness discussion into an execution order
for SeedCore.

The goal is to establish freshness-SLA metrics without confusing local
agent/workstation compute with physical closure evidence. RTX Spark /
DGX Spark-class systems may accelerate proposal, simulation, diagnosis, and
repair. They are not the first physical closure target unless explicitly
enrolled as evidence-producing devices.

The physical closure loop needs deterministic timing, cryptographic binding,
and replay-visible evidence from dedicated edge or robot-adjacent silicon.

## Cross-Lane Rule

Every lane must preserve the same authority boundary:

```text
agent or model proposes
PDP decides
ExecutionToken scopes the admitted attempt
edge or robot telemetry proves physical closure
verifier replay accepts, denies, quarantines, or escalates
```

No lane may treat local LLM output, workload provenance, cached memory, or
hardware capability as execution authority by itself.

## Critical Metric

The control metric across all lanes is **Convergence P99 Latency**.

Definition:

```text
source mutation or telemetry event accepted by context pipeline
-> local PDP view can prove freshness at or beyond the request causality token
```

Why it matters:

- if Convergence P99 drifts above the lane's freshness bound, strict PDP checks
  will create false-positive authorization blocks;
- if engineers relax the bound to avoid those blocks, SeedCore loses the
  fail-closed freshness guarantee;
- if the latency stays predictably tight, fail-closed behavior becomes an
  operational advantage instead of a support burden.

Every stress run should report:

- Convergence P50, P95, and P99;
- PDP decision latency P50, P95, and P99;
- signature verification latency P50, P95, and P99;
- freshness-failure count by reason code;
- false-positive quarantine count;
- replay parity rate;
- evidence bundle completeness;
- packet or envelope size on the hot path.

## Lane 1: RCT Fixture / Simulator

Focus:

- deterministic replay stability with 1:1 parity and no physical chaos.

Freshness-SLA target:

- less than 1 ms simulated data loop for fixture-local freshness checks.

Strategic objective:

- establish the core telemetry contract using deterministic fixture data,
  mock `state_binding_hash` formats, signed telemetry refs, and replay-visible
  freshness outcomes.

Work schedule:

1. Freeze fixture schemas for `DeviceIdentity`, `HardwareSignerRef`,
   `SignedEdgeTelemetryRefV0`, freshness windows, causality tokens, and
   `state_binding_hash` inputs.
2. Add synthetic network-partition fixtures that delay context propagation
   beyond the declared freshness SLA.
3. Verify that the PDP fails closed immediately when the simulated causality
   token is fresher than the local view can prove.
4. Add stale telemetry, missing telemetry, replayed telemetry, wrong asset,
   wrong zone, and payload-hash mismatch cases to the RCT degraded-edge matrix.
5. Persist replay artifacts that show the freshness bound, causality token,
   local-view ref, telemetry refs, signer refs, and verifier outcome.

Exit criteria:

- replay parity is 1:1 for happy path and toxic-path fixtures;
- stale or causality-breached context never settles as accepted;
- freshness reason codes are stable enough for operator surfaces and dashboards;
- Convergence P99 and false-positive quarantine count are emitted by the test
  harness.

## Lane 2: Jetson Orin Prototype Edge

Focus:

- embedded optimization and lightweight policy-adjacent execution on prototype
  edge boards.

Freshness-SLA target:

- 5 ms to 20 ms for edge bus and prototype hardware scheduling.

Strategic objective:

- benchmark local signature verification and in-process token attenuation on
  Jetson-class devices without introducing dangerous jitter into robot or
  custody routines.

Work schedule:

1. Implement a `prototype_edge` enrollment fixture for Jetson Orin / AGX Orin
   with explicit signer key refs, hardware fingerprint, trusted zones, and
   allowed evidence kinds.
2. Run signed context envelope verification on-device with bounded packet
   sizes and memory allocation telemetry.
3. Benchmark candidate policy-adjacent mechanisms such as Biscuit/Datalog or
   Cedar WASM as local attenuation inputs, while keeping the final authority
   decision on the SeedCore PDP path.
4. Measure jitter during signature verification, hash checks, telemetry
   serialization, and local bus reads for NFC / QR / weight / scan evidence.
5. Feed Jetson telemetry into the RCT fixture contract and prove the same
   replay outcomes as Lane 1.

Exit criteria:

- freshness checks stay inside the 5 ms to 20 ms prototype target under load;
- signature verification does not create unsafe allocation or scheduling jitter;
- Jetson evidence is distinguishable from simulator evidence in replay;
- failures still map to the same deny/quarantine/escalate taxonomy as Lane 1.

## Lane 3: IGX Thor / T5000 Trusted Edge

Focus:

- production-grade industrial safety posture and hardware-rooted attestation.

Freshness-SLA target:

- sub-millisecond to 5 ms strict real-time bounds, depending on the specific
  trusted-edge deployment profile.

Strategic objective:

- integrate the context supply chain with hardware-rooted signer posture so
  unsigned, weakly signed, or provenance-missing telemetry fails closed as a
  policy-bypass attempt.

Work schedule:

1. Extend the edge enrollment schema with IGX software lane, kernel/driver,
   firmware, secure-boot posture, trust-anchor type, and attestation metadata.
2. Add TPM, KMS, TEE, or HSM-backed signer refs to telemetry envelopes and
   closure evidence bundles.
3. Treat telemetry lacking verifiable hardware-root provenance as an
   unconditional local fail-closed condition for trusted-edge profiles.
4. Add adversarial drills for stale node health, telemetry tamper, mismatched
   closure node identity, cross-node token replay, and revoked signer posture.
5. Capture IGX lane replay artifacts that show signer chain, trust-bundle
   membership, firmware/software-lane metadata, freshness result, and verifier
   disposition.

Exit criteria:

- trusted-edge closures cannot settle with simulator or prototype-only signer
  posture unless policy explicitly admits that profile;
- stale node health and missing hardware provenance fail closed locally;
- Convergence P99 stays inside the selected trusted-edge profile;
- replay can explain device identity, signer chain, firmware/software lane,
  telemetry payload hash, freshness, and final disposition.

## Lane 4: Robotics Handoff Environments

Focus:

- real-world physical execution loops and multi-entity custody transfers.

Candidate environments:

- Unitree B2-class custody movement or courier actor;
- Reachy Mini-class manipulation, handoff, or operator-facing demo actor;
- equivalent hardware-in-the-loop custody environments.

Freshness-SLA target:

- dynamic and kinematic-dependent.

Examples:

- joint-space telemetry must be fresher during high-velocity motion than during
  a stationary custody state;
- custody-zone evidence may tolerate a wider freshness window than collision,
  gripper, or handoff-state telemetry;
- final closure still requires freshness, asset, zone, signer, and replay
  compatibility.

Strategic objective:

- after Lanes 1 through 3 stabilize the telemetry contract, roll the stateless
  PDP pattern to live physical systems and evaluate the final allow/deny
  execution token at the execution boundary.

Work schedule:

1. Define per-state freshness classes for stationary custody, handoff approach,
   active manipulation, high-velocity movement, and closure confirmation.
2. Bind each class to required telemetry kinds, signer posture, local-view
   freshness, and fail-closed disposition.
3. Evaluate the final token at the execution boundary and stop immediately when
   connection quality, local-view freshness, node health, or telemetry
   provenance degrades beyond policy bounds.
4. Add multi-entity custody drills for courier/robot handoff, wrong recipient,
   stale zone, cross-asset replay, connection degradation, and delayed closure.
5. Keep public proof narrow while operator forensics shows the richer telemetry
   and signer chain.

Exit criteria:

- physical handoff stops when freshness or connection quality violates policy;
- dynamic freshness windows are replay-visible and tied to motion/custody state;
- live robotics evidence produces the same verifier taxonomy as fixture,
  Jetson, and trusted-edge lanes;
- no robot, local runtime, or perception subsystem can mint authority outside
  PDP, ExecutionToken, evidence closure, and verifier acceptance.

## Recommended Timeline

### Now to 30 Days

- complete Lane 1 fixture schema and toxic-path coverage;
- add Convergence P99, false-positive quarantine, and replay parity metrics to
  the fixture harness;
- expose freshness outcomes in Execution Replay Studio fixture payloads;
- document the operator reason-code taxonomy for stale context and stale
  telemetry.

### 30 to 60 Days

- run Lane 2 on Jetson-class prototype hardware or a faithful Jetson-profile
  lab substitute;
- benchmark signature verification, envelope size, local attenuation checks,
  and bus-read jitter;
- confirm Jetson telemetry can use the same replay and verifier contract as
  Lane 1;
- decide whether candidate Biscuit/Datalog or Cedar WASM work belongs in the
  hot path, the edge precheck path, or only as advisory attenuation metadata.

### 60 to 120 Days

- prepare Lane 3 trusted-edge enrollment fields and signer metadata;
- wire TPM/KMS/TEE/HSM-backed signer refs into telemetry fixtures and replay;
- add trusted-edge adversarial drills for missing hardware provenance, stale
  node health, cross-node replay, telemetry tamper, and revoked signer;
- set the initial IGX/T5000 profile target only after hardware and software
  lane evidence is available.

### After Lanes 1 to 3 Are Stable

- begin Lane 4 robotics handoff tests;
- start with slow, bounded custody states before high-velocity or manipulation
  states;
- graduate to Unitree B2 / Reachy Mini-class demonstrations only when dynamic
  freshness windows, execution-boundary token checks, and fail-closed stop
  behavior are replay-visible.

## Non-Goals

- do not use Spark/DGX-class workstations as a substitute for edge closure
  evidence;
- do not make Biscuit, Cedar WASM, local memory, model output, or robot runtime
  state an authority source;
- do not relax freshness checks to avoid false-positive blocks;
- do not require IGX Thor before the Jetson prototype lane proves the contract;
- do not move the full SeedCore trust plane onto edge hardware.

## Monitoring References

Use these references as a standing horizon radar. They are inputs for
experiments, benchmarks, and drills; they do not become authority surfaces by
themselves.

### Emerging Open Standards

- [W3C Verifiable Credentials Data Model 2.0](https://www.w3.org/TR/vc-data-model-2.0/) -
  monitor for signed identity, delegated credential, and evidence-envelope
  interoperability.
- [IETF RATS RFC 9334](https://datatracker.ietf.org/doc/rfc9334/) -
  keep SeedCore's attester, evidence, verifier, appraisal-policy, and relying
  party language aligned with standard remote-attestation vocabulary.
- [IETF WIMSE Working Group](https://datatracker.ietf.org/wg/wimse/about/) -
  track workload identity semantics for service, agent, and edge workload
  provenance.
- [IETF SCITT Working Group](https://datatracker.ietf.org/group/scitt/about/) -
  track signed statements, transparency receipts, and supply-chain integrity
  patterns that may strengthen replay bundle anchoring.
- [Biscuit authorization tokens](https://www.biscuitsec.org/) -
  monitor caveat-style attenuation and offline restriction patterns for scoped
  authority envelopes.

### Performance Optimization Technologies

- [Open Policy Agent WebAssembly](https://openpolicyagent.org/docs/wasm) -
  benchmark compiled policy evaluation only as a deterministic precheck or
  candidate hot-path component after replay parity is proven.
- [Cedar policy language](https://docs.cedarpolicy.com/) -
  track schema tooling, policy expressiveness, and evaluation performance for
  attribute-scoped authorization.
- [Wasmtime](https://docs.wasmtime.dev/) -
  monitor lightweight WebAssembly embedding and ahead-of-time compilation for
  edge precheck experiments.
- [WasmEdge](https://wasmedge.org/) -
  watch edge-oriented WebAssembly runtime performance and deployment ergonomics
  for Jetson or trusted-edge experiments.

### Operational Vulnerability Spaces

- [CISA Principles for Secure Integration of AI in Operational Technology](https://www.cisa.gov/resources-tools/resources/principles-secure-integration-artificial-intelligence-operational-technology) -
  map AI-in-OT guidance into SeedCore negative-path drills for robotics and
  hardware-critical flows.
- [MITRE ATT&CK for ICS](https://attack.mitre.org/matrices/ics/) -
  use ICS tactics and techniques as a source for telemetry tamper, unsafe
  actuation, and degraded-edge adversarial scenarios.
- [NIST SP 800-193 Platform Firmware Resiliency Guidelines](https://csrc.nist.gov/pubs/sp/800/193/final) -
  track root-of-trust, firmware protection, detection, and recovery concepts
  for trusted-edge enrollment and node-health evidence.
- [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework) -
  use risk management language for operator-facing AI governance and incident
  framing, while keeping PDP and verifier semantics deterministic.

## Related Documents

- [Current Next Steps](current_next_steps.md)
- [SeedCore 2026 Execution Plan](seedcore_2026_execution_plan.md)
- [Hardware-Anchored Telemetry MVP Contract](hardware_anchored_telemetry_mvp_contract.md)
- [RTX Spark Autonomous Era Investigation](rtx_spark_autonomous_era_investigation.md)
- [ADR 0001: PDP Hot Path](../architecture/adr/adr-0001-pdp-hot-path.md)
- [ADR 0003: IGX Thor Trusted Edge Profile](../architecture/adr/adr-0003-igx-thor-trusted-edge-profile.md)
- [ADR 0010: Hardware-Anchored Telemetry as Execution Proof](../architecture/adr/adr-0010-hardware-anchored-telemetry-execution-proof.md)
