# Multi-Agent Safety Research Alignment

Date: 2026-07-03
Status: Strategy memo for proposal shaping and roadmap comparison

## Purpose

This memo maps SeedCore's current trust-runtime implementation against the
four priority areas in the 2026 multi-agent safety research call:

1. sandboxes and testbeds
2. science of agent networks
3. strengthening agent infrastructure
4. oversight and control

The useful positioning is narrow:

```text
SeedCore is a governed execution and proof substrate for multi-principal agent
transactions, demonstrated through Restricted Custody Transfer.
```

SeedCore should not be framed as a generic multi-agent platform, coding-agent
harness, marketplace, or cybersecurity detector. The core claim is that
multi-agent systems become safer when high-consequence actions must pass
through typed intent, deterministic admission, scoped authority, evidence
capture, and replayable closure.

## External Call Snapshot

The call describes a funding program for multi-agent AI safety research with up
to $10M available across the four areas above. The Schmidt Sciences portal
lists the deadline as August 9, 2026 07:59 EDT, which corresponds to
August 8, 2026 AoE.

References:

- Google DeepMind announcement:
  <https://deepmind.google/blog/investing-in-multi-agent-ai-safety-research/>
- Schmidt Sciences application portal:
  <https://schmidtsciences.smapply.io/prog/scaling_ai_safety_for_a_multi_agent_world/>
- Linked arXiv paper:
  <https://arxiv.org/html/2511.21990v1>

## SeedCore Baseline

SeedCore already has a strong baseline for governed single-workflow and
multi-principal custody transitions:

- strict `ActionIntent` schemas and agent-action gateway contracts
- deterministic PDP evaluation against policy, delegation, context, and
  evidence gates
- scoped, short-lived `ExecutionToken`s with revocation and execution
  preconditions
- owner-twin delegation, workload identity helpers, DPoP/SPIFFE seams, and
  authz graph checks
- transition receipts, evidence bundles, replay, and `RESULT_VERIFIER`
  fail-closed closure
- virtual NFC and rare-shoe RCT fixtures for realistic physical/economic
  evidence boundaries
- governance-aware learning and scenario generation in shadow-only form
- operator verification surfaces, runbooks, replay detail, and quarantine
  workflows

The main gap is not the core trust boundary. The main gap is population-scale
research instrumentation around that boundary: many-agent testbeds, network
metrics, adversarial agent populations, commitment/reputation stress tests, and
fleet-level oversight controls.

## Area 1: Sandboxes And Testbeds

### Current Fit

SeedCore is already testbed-shaped, but the testbed is intentionally narrow.
The strongest implemented lane is commerce-bound Restricted Custody Transfer:
economic identifiers, asset identity, physical evidence, policy admission,
tokenized execution, and replayable verifier closure.

Current anchors:

- `docs/development/rare_shoes_collecting_transfer_demo_spec.md`
- `docs/development/virtual_nfc_simulation_plan.md`
- `docs/development/governance_aware_learning_next_stage_plan.md`
- `docs/development/agent_system_eval_schedule.md`
- `docs/development/gvisor_and_sandbox_hardening_strategy.md`
- `docs/development/cubesandbox_dependency_integration_sketch.md`
- `src/seedcore/ml/curriculum/governance_scenarios.py`
- `tests/test_rare_shoe_rct_demo.py`
- `tests/test_rct_commerce_drill_matrix.py`
- `tests/test_governance_learning_harness.py`

### Gaps

SeedCore does not yet provide a research-grade multi-agent ecosystem testbed.
Missing pieces include:

- many-agent synthetic populations with heterogeneous goals and authority
  levels
- repeated market interactions across buyers, sellers, authenticators,
  couriers, marketplaces, compliance agents, and adversarial agents
- standardized episode traces for multi-agent workflows
- collusion, Sybil, reputation laundering, and marketplace manipulation
  scenarios
- configurable environment parameters such as liquidity, fraud rate, evidence
  quality, network latency, revocation delay, and verifier lag
- population-scale benchmark outputs rather than only workflow-level pass/fail
  outputs

### Adaptation

Build an **RCT virtual marketplace testbed** around the existing rare-shoe RCT
lane.

The environment should include:

- buyer agents that issue purchase or custody requests
- seller/consignor agents that register assets and negotiate transfer
- authenticator agents that emit provenance, condition, and scan evidence
- courier or edge agents that request scoped custody movement authority
- marketplace/listing agents that provide `product_ref`, `quote_ref`,
  `order_ref`, `declared_value_usd`, and economic hash context
- compliance agents that request step-up, co-signature, or quarantine
- adversarial agents that attempt replay, substitution, stale evidence,
  hidden delegation, collusion, or forged commitments

Every mutating action remains on the SeedCore spine:

```text
agent proposal
-> typed ActionIntent
-> PDP allow / deny / escalate / quarantine
-> scoped ExecutionToken or no-execute
-> actuator / sandbox attempt
-> evidence bundle
-> replay / RESULT_VERIFIER
-> verified, rejected, review_required, or quarantined
```

The testbed should expose simulation knobs, but no simulation success may
become execution authority.

### Proposal Angle

SeedCore can offer a realistic testbed where agent-market behavior is studied
against deterministic ground truth. Instead of asking whether agents sound
cooperative, the testbed asks whether their requested actions were admissible,
evidence-bound, and replay-verifiable.

## Area 2: Science Of Agent Networks

### Current Fit

SeedCore has architectural seams for recursive delegation and agent behavior,
but it does not yet study emergent population behavior as a first-class
research object.

Current anchors:

- `docs/development/agentic_delegation_control_plane.md`
- `docs/development/authz_graph_engine_evolution_plan.md`
- `docs/development/agent_system_eval_schedule.md`
- `docs/development/governance_aware_learning_next_stage_plan.md`
- `src/seedcore/agents/`
- `src/seedcore/ops/pkg/authz_graph/`
- `src/seedcore/ml/curriculum/governance_scenarios.py`
- `tests/test_agents_roles.py`
- `tests/test_agents_behaviors.py`
- `tests/test_agent_self_regulation_drill.py`

### Gaps

Missing network-science capabilities:

- topology-aware simulation of agent populations
- measurements of emergent capability, volatility, herding, collusion, and
  authority amplification
- detection of dangerous population-level properties before they become
  individual execution attempts
- multi-hop delegation cascade analysis
- population-level benchmarks across policy, network, and evidence conditions
- explicit distinction between benign coordination and suspicious convergence

### Adaptation

Add a **population metrics layer** over SeedCore receipts, replay records,
delegation paths, and verifier outcomes.

Candidate metrics:

| Metric | Meaning | SeedCore evidence source |
| --- | --- | --- |
| Authority amplification factor | Whether delegation fanout increases effective actuation reach | `ExecutionToken` lineage, delegated subtokens, authz graph paths |
| Scope widening pressure | Frequency of attempted child actions broader than parent authority | PDP deny reasons, delegation gate failures |
| Token storm index | Sudden surge in scoped execution attempts across related agents | gateway/PDP audit rows, policy outcome stream |
| No-execute compliance rate | Whether agents stop after deny/quarantine/escalate | agent traces, tool-call logs, replay absence |
| Collusive closure suspicion | Mutually reinforcing evidence from related agents with weak external anchors | evidence bundles, signer lineage, graph relations |
| Quarantine propagation | How verifier failures spread through assets, agents, issuers, or facilities | `RESULT_VERIFIER` outcomes, custody graph, revocation state |
| Hidden tool-call rate | Mutating actions lacking visible policy receipts or token refs | replay/tool-call timeline |
| Commitment default rate | Accepted commitments that fail evidence closure or settlement | transfer approvals, transition receipts, verifier outcomes |

These metrics should be advisory or oversight signals. They may trigger a
governed intervention request, but they must not mutate trust state directly.

### Proposal Angle

SeedCore can support research into when individual safe-looking agents become
unsafe as a population. Its advantage is that the network study is grounded in
explicit authority attempts, receipt graphs, and verifier outcomes rather than
only prompt transcripts.

## Area 3: Strengthening Agent Infrastructure

### Current Fit

This is SeedCore's strongest area today.

Implemented or drafted infrastructure aligns directly with identity,
reputation, and commitment protocol stress testing:

- principal identity and identity proof requirements in the agent-action
  gateway
- owner delegation and scope constraints
- workload identity helpers for SPIFFE and DPoP
- scoped `ExecutionToken`s with preconditions and revocation
- authz graph checks and revocation-safe cache behavior
- signed context, causality, mutation receipt, and freshness-gate plans
- approval envelopes, dual-control, and co-signature patterns for high-value
  transfers

Current anchors:

- `docs/development/agent_action_gateway_contract.md`
- `docs/development/policy_gate_matrix.md`
- `docs/development/agentic_delegation_control_plane.md`
- `docs/development/execution_token_lifecycle_management.md`
- `docs/development/verifying_delegation_frontier_ai_architectures.md`
- `docs/development/ap2_seedcore_rct_alignment_memo.md`
- `src/seedcore/models/action_intent.py`
- `src/seedcore/ops/identity/workload.py`
- `src/seedcore/ops/pkg/authz_graph/`
- `tests/test_workload_identity.py`
- `tests/test_authz_cache_security.py`
- `tests/test_agent_action_gateway_productization.py`

### Gaps

Identity and authority boundaries are stronger than reputation and commitment.
Current gaps:

- no first-class agent reputation protocol
- no adversarial stress harness for reputation laundering, Sybil clusters, or
  reciprocal endorsement loops
- commitment semantics are embedded in RCT/AP2-adjacent docs rather than
  generalized as a reusable cross-platform commitment primitive
- full KMS/key-registry signature verification remains a hardening item for
  some authority-adjacent promotion receipts
- delegated subtoken/capability-chain semantics are still partly roadmap
- no standard external conformance suite for third-party agent platforms

### Adaptation

Build an **identity, commitment, and reputation stress harness** that treats
SeedCore as the enforcement/proof layer and external agents as untrusted
participants.

Stress cases:

- Sybil sellers create fake provenance and mutually reinforce reputation
- authenticator colludes with seller to emit stale or forged evidence
- courier replays a prior valid custody scan for a different order
- buyer agent tries to widen delegated scope after an accepted quote
- marketplace agent changes price or item identity after approval
- compliance agent attempts same-channel approval for a sensitive action
- child agent attempts a tool call outside parent token constraints
- revocation arrives between approval and execution
- identity proof is valid but authority scope is missing

Protocol outputs should include:

- explicit PDP decision and deny/quarantine/escalate reason
- token posture and constraint hash
- commitment hash and issuer identity
- evidence completeness
- verifier outcome
- replay bundle ref
- reputation impact proposal, not automatic reputation mutation

### Proposal Angle

SeedCore can make infrastructure protocols falsifiable. Instead of claiming an
identity, reputation, or commitment scheme is safe, the harness asks whether it
survives adversarial multi-agent transaction episodes with replayable proof.

## Area 4: Oversight And Control

### Current Fit

SeedCore already has strong case-level oversight:

- operator verification queue and replay surfaces
- `RESULT_VERIFIER` outcomes
- quarantine and fail-closed twin mutation
- runbook lookup and remediation workflows
- operator copilot as a read-only explanation surface
- governance-aware shadow advisory that cannot alter PDP or verifier outcomes

Current anchors:

- `docs/development/q2_2026_audit_trail_ui_spec.md`
- `docs/development/productized_verification_surface_protocol.md`
- `docs/development/execution_replay_studio_development_plan.md`
- `docs/development/result_verifier_quarantine_remediation_runbook.md`
- `docs/development/statistical_model_audit_shadow_contract.md`
- `src/seedcore/services/result_verifier_engine.py`
- `src/seedcore/services/replay_service.py`
- `ts/services/verification-api/`
- `tests/test_result_verifier.py`
- `tests/test_replay_router.py`

### Gaps

Oversight is currently workflow-centered, not population-centered.

Missing capabilities:

- fleet-level and ecosystem-level dashboards
- issuer, facility, agent-cluster, or marketplace-level aggregation
- topology-aware quarantine recommendations
- collective-harm metrics across many small individually admissible actions
- controlled intervention workflows such as issuer revocation waves, policy
  class freeze, cluster step-up, or evidence-grade escalation
- measurements of operator load and intervention precision at population scale

### Adaptation

Build a **population oversight plane** that consumes policy outcomes, token
attempts, evidence state, replay results, and verifier outcomes.

Oversight signals may propose interventions such as:

- freeze a policy class for a high-risk asset family
- require step-up for a suspicious agent cluster
- revoke an issuer or signing key after verifier failures
- quarantine a facility, courier route, or marketplace lane
- downgrade evidence grade when telemetry quality degrades
- require dual control for a class of commitments
- raise freshness requirements during volatility

Important boundary:

```text
Oversight detects and proposes.
SeedCore PDP/verifier/operator controls still decide and execute intervention.
```

Intervention requests should themselves be governed actions with typed intent,
policy evaluation, approval requirements, scoped tokens where needed, evidence
capture, and replay.

### Proposal Angle

SeedCore can study oversight at the level where harm actually appears: not only
one bad agent, but populations of agents whose interactions stress authority,
evidence, and commitment boundaries.

## Best Proposal Shape

Recommended proposal title:

```text
Replayable Testbeds and Oversight for Multi-Principal Agent Commerce
```

Core thesis:

```text
Multi-agent safety needs environments where agent behavior can be evaluated
against explicit authority, commitment, evidence, and replay outcomes.
SeedCore provides a trust-runtime testbed for that question: agents may propose,
but only deterministic policy admission, scoped execution tokens, and verifier
closure can turn a proposed transaction into an admissible state transition.
```

Research questions:

1. What multi-agent market behaviors create unsafe authority amplification even
   when each individual agent appears locally compliant?
2. Which identity, reputation, and commitment protocols resist collusion,
   replay, stale context, and scope-widening under realistic transaction
   pressure?
3. Which population-level signals predict verifier failure, quarantine
   propagation, or hidden delegation risk?
4. How can oversight systems intervene at population scale without becoming an
   unbounded authority source?

Deliverables:

- RCT virtual marketplace simulator
- multi-agent transaction episode schema
- authority/evidence/replay trace corpus
- adversarial scenario pack for identity, commitment, reputation, and
  delegation stress
- network metrics library for authority amplification, token storms, no-execute
  compliance, collusive closure, and quarantine propagation
- population oversight prototype that proposes governed interventions
- benchmark report comparing baseline agents, adversarial populations, and
  mitigation policies

## Implementation Track

### Track A: Testbed Envelope

Create a simulation envelope around the current RCT gateway and replay path.

Minimum work:

- define `MultiAgentRCTEpisodeV1`
- define agent roles and scenario parameters
- compose agent proposals into existing gateway requests
- persist per-agent tool-call and policy-decision traces
- export replay-linked episode summaries

Acceptance:

- every mutating simulated action has a policy decision or explicit no-execute
  result
- no simulator component can mint tokens or close verifier evidence
- episode output can reconstruct actor, action, authority, evidence, and
  closure sequence

### Track B: Network Metrics

Add offline metrics computed from episode traces.

Minimum work:

- parse policy outcomes, token attempts, delegation refs, evidence refs, and
  verifier outcomes
- compute population-level metrics
- emit JSONL summaries for benchmark runs
- compare benign, adversarial, and mixed populations

Acceptance:

- metrics are deterministic over the same trace corpus
- metrics cannot alter PDP or verifier output
- dangerous population properties are linked back to concrete replay refs

### Track C: Infrastructure Stress Harness

Codify adversarial protocol tests.

Minimum work:

- create stress cases for identity proof, delegated scope, commitment hash,
  reputation signal, and evidence closure
- map each stress case to expected PDP and verifier outcomes
- generate replayable negative examples for governance learning

Acceptance:

- reason-code match and verifier-outcome match are reported
- reputation and commitment outputs remain proposals until governed promotion
- failure cases stop before execution or quarantine after verifier mismatch

### Track D: Population Oversight Prototype

Create a read-only oversight worker that proposes interventions.

Minimum work:

- consume episode summaries and verifier outcomes
- detect cluster-level risk conditions
- emit `OversightInterventionProposalV1`
- route proposed interventions through an explicit governed-action path in
  shadow first

Acceptance:

- oversight proposals are replay-linked and explainable
- no oversight signal directly mutates custody, policy, quarantine, revocation,
  or enforcement state
- operator surface can show why an intervention was proposed

## What To Avoid

Do not claim:

- SeedCore is a general AI-agent marketplace
- SeedCore is a generic sandbox or agent benchmark suite
- SeedCore detects maliciousness as a cybersecurity product
- reputation, memory, learning, or oversight scores are authority sources
- simulation success implies production deployment readiness
- marketplace or AP2-like commerce protocols are replaced by SeedCore

Prefer:

- governed execution
- scoped authority
- replayable proof
- multi-principal transaction safety
- identity, commitment, evidence, and verifier stress testing
- population oversight with governed intervention

## Recommendation

The strongest fit is a combined Area 1 + Area 3 + Area 4 proposal, with Area 2
as the scientific measurement layer:

```text
Build a realistic RCT virtual marketplace testbed, stress identity /
commitment / reputation infrastructure inside it, measure emergent network
risks, and prototype population oversight that proposes governed interventions
without bypassing PDP, ExecutionToken, evidence, replay, or RESULT_VERIFIER.
```

This keeps SeedCore commercially coherent while making it relevant to the
funded research agenda.
