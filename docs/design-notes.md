# SeedCore Design Notes

This is a living conceptual note for SeedCore. It captures enduring design intent and should not be treated as a migration log or implementation checklist.

## Runtime Intent

SeedCore is a zero-trust runtime for custody-aware digital twins where AI judgment, accountable agents, and real-world execution are separated by explicit policy and evidence boundaries.

Core intent:

- keep AI advisory by default
- require policy-verified authorization before high-consequence actions
- preserve replayable evidence for each governed state transition

## Plane Model (Current)

SeedCore uses a practical multi-plane model:

- **Intelligence Plane**: reasoning, planning, and context hydration
- **Control Plane**: policy evaluation, surprise/drift gating, execution decisioning
- **Execution Plane**: accountable agents and tool/actuator handoff
- **Infrastructure Plane**: distributed runtime substrate, data services, and telemetry

The plane model is a design aid for system boundaries. It is not a strict package/module taxonomy.

## Judgment vs Authority

A stable system boundary in SeedCore is the split between judgment and authority:

- `TaskPayload` carries planning and routing context
- `ActionIntent` carries an accountable, policy-evaluable action contract
- authorization occurs only after policy allow and tokenized handoff

This keeps the runtime auditable, deny-by-default, and safe under model uncertainty.

## Fast Path and Escalation

SeedCore favors low-latency default handling for routine cases, with deliberate escalation for high-surprise or high-risk situations. In practice:

- routine decisions stay on the hot path
- surprising states escalate to deeper reasoning and stricter governance
- execution remains policy-constrained in both paths

## Design Guardrails

When introducing new components, preserve these guardrails:

- no direct LLM-to-actuator execution bypassing policy checks
- no hidden side effects without signed or verifiable receipts
- no coupling that prevents deterministic replay of high-consequence workflows

## Advanced Guardrails (Current)

The current guardrail architecture follows a shared governed-mutation model across tool execution, direct API mutations, HAL actuation, and replay.

In practical terms, SeedCore now assumes:

- mutating paths must declare an explicit mutation contract
- contract enforcement is fail-closed for governed paths
- signed mutation receipts are the default proof surface for side effects
- replay services must support deterministic dependency injection for high-consequence workflows

This is the implementation shape that the current codebase is converging around, rather than a future-only target.

## Shared Mutation Contract

SeedCore uses a common contract to describe side-effecting behavior before execution occurs.

The contract expresses:

- `effect_class`: what kind of state is being changed
- `requires_execution_token`: whether governed authorization is mandatory
- `requires_signed_receipt`: whether the mutation must emit a signed receipt
- `snapshot_binding_required`: whether the mutation must remain pinned to policy/context state
- `replay_mode`: the expected replay stability requirement

This keeps mutation semantics visible at registration time instead of relying on naming conventions or implicit runtime assumptions.

## Governed Mutation Flow

The intended high-consequence mutation path is now a shared wrapper, not a collection of one-off code paths.

```mermaid
flowchart LR
    A["Tool Or API Mutation"] --> B["Contract Lookup"]
    B --> C["RBAC Check"]
    C --> D["Execution Token Validation"]
    D --> E["Snapshot / Policy Binding Check"]
    E --> F["Deterministic Payload Hashing"]
    F --> G["Mutation Execution"]
    G --> H["Signed Mutation Receipt"]
    H --> I["Governed Audit / Evidence Bundle"]
    I --> J["Replay / Verification Surface"]
```

This flow preserves the judgment-versus-authority split:

- AI may recommend or prepare actions
- governed runtime components decide whether the mutation may execute
- execution proof is attached to receipts and audit artifacts, not to model output alone

## Five Implementation Themes

The advanced guardrail work now resolves into five stable design themes.

### 1. Shared Mutation Contract And Fail-Closed Enforcement

Mutating components should not depend on tool-name pattern matching as their primary safety mechanism.

The runtime direction is:

- register or derive a `GovernedMutationContract`
- fail closed when a known mutating path has no valid contract
- require RBAC and token validation on governed mutations
- keep HAL execution-token enforcement enabled by default at the actuator boundary

This ensures new side-effecting code enters the system through an explicit contract surface.

### 2. Standardized Signed Receipts

Side effects should emit signed, hash-bound receipts that can be linked into append-only audit evidence.

The normalized receipt shape centers on:

- `receipt_id`
- `payload_hash`
- `executed_at`
- `previous_receipt_hash`
- actor, intent, token, and policy references where applicable

Receipt issuance is now treated as part of the mutation boundary, not as optional logging.

### 3. Unified Governed Mutation Entrypoints

SeedCore is moving away from bespoke mutation code paths toward a shared governed wrapper used by:

- tool execution
- identity mutations
- tracking event creation
- source registration mutations
- HAL-backed mutation evidence

The architectural goal is simple: if a component mutates governed state, it should look like every other governed mutation at the execution boundary.

### 4. Deterministic Replay For High-Consequence Workflows

Replay logic for custody, trust, and verification surfaces must be able to run from pinned artifacts with deterministic dependencies.

For high-consequence workflows this means:

- inject `Clock`-like time providers instead of calling ambient time directly in replay-sensitive logic
- inject ID generators instead of relying on ambient UUID generation in replay-sensitive logic
- pin `snapshot_id` or equivalent policy/context references where mutation semantics depend on policy state
- derive fallback replay identifiers from stable payload data when source IDs are absent

Replay should be reproducible from evidence artifacts, not from whatever environment happens to exist at verification time.

### 5. Deterministic Service Dependencies Beyond Replay

Determinism is not only a replay concern. Services that feed replay or trust surfaces should expose deterministic hooks as well.

That principle now extends to replay-adjacent services such as custody graph lineage and dispute flows:

- dispute and lineage identifiers should be stable or provider-injected where replay depends on them
- time-sensitive service behavior should support injected clocks in verification-sensitive paths
- artifact-producing services should prefer deterministic fallbacks over ambient randomness

## New Component Contract

When adding a new side-effecting component, treat the following as the default admission contract.

1. Declare a governed mutation contract.
2. Require an execution token for high-consequence side effects.
3. Emit a signed receipt for every mutation that changes governed state.
4. Persist enough lineage to link the receipt into audit, evidence, or custody history.
5. Separate pure decision logic from IO adapters so replay can run on artifacts.
6. Inject time and ID dependencies anywhere deterministic replay matters.
7. Add replay-oriented tests that assert stable outputs for stable inputs.

If a new component cannot satisfy these expectations, that should be an explicit design exception rather than an unexamined shortcut.

## Architectural Outcome

The practical result of these guardrails is that SeedCore behaves less like a chat system with tools and more like a governed execution runtime:

- policy and approval state decide authority
- execution tokens scope side effects
- signed receipts make mutations externally provable
- custody and audit records preserve lineage
- replay and trust surfaces reconstruct what happened from evidence, not narration

That is the core design intent to preserve as new components are added.

## Canonical References

For normative implementation details and active execution priorities, use:

- [Architecture Overview](architecture/overview/architecture.md)
- [Zero-Trust Custody and Digital-Twin Runtime](architecture/overview/zero_trust_custody_digital_twin_runtime.md)
- [Sequence Of Trust: Zero-Trust Physical Custody](architecture/overview/sequence_of_trust_zero_trust_physical_custody.md)
- [Gemini Extension: Owner / Creator Layer Implementation](architecture/overview/gemini_owner_creator_extension.md)
- [Owner / Creator External SDK and Plugin Surface](development/owner_creator_external_sdk_and_plugin_surface.md)
- [Gemini Owner/Creator Phase 1-3 Quickstart](development/gemini_phase1_quickstart.md)
- [SeedCore 2026 Execution Plan](development/seedcore_2026_execution_plan.md)
- [Agent Action Gateway Contract](development/agent_action_gateway_contract.md)
