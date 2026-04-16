# Nous-Style Instruction Tuning Patterns For SeedCore

Date: 2026-04-16  
Status: Draft research-to-application note

This note translates a narrow slice of the Nous Research / Hermes post-training
approach into SeedCore terms.

The question is not whether Hermes is broadly capable.

The question is:

> which instruction-tuning and post-training patterns from Hermes could help
> SeedCore become more legible, tool-disciplined, and abstention-safe without
> weakening the synchronous PDP boundary?

## Short Answer

The most relevant Hermes pattern for SeedCore is not personality tuning.

It is **contract-following post-training**:

- supervised instruction tuning for exact response shapes
- explicit tool-use training
- structured output / JSON-mode training
- preference optimization that favors disciplined behavior over improvisation

For SeedCore, this should be adapted into:

- **contract-shaped outputs**
- **tool-call discipline**
- **authority abstention**
- **evidence-grounded explanation**

## What Nous / Hermes Appears To Be Doing

From the Hermes public materials, the useful pattern is:

1. large-scale instruction tuning on high-quality instruction/chat data
2. a second-stage preference optimization pass
3. explicit training for function calling and structured outputs
4. strong system-prompt and role steerability

The Hermes 3 technical report explicitly states that the training recipe has:

- a **supervised fine-tuning (SFT)** phase
- a **direct preference optimization (DPO)** phase

It also describes explicit training for:

- tool use via tool schemas and parseable tool-call tags
- structured outputs / JSON mode
- interpretable use of retrieval and external tools

## Why This Matters For SeedCore

SeedCore does not need a more theatrical assistant in the hot path.

SeedCore needs learned components that are better at:

- obeying strict contracts
- refusing to improvise authority
- producing typed intermediate outputs
- grounding explanations in replayable artifacts
- using tools predictably instead of hallucinating outcomes

That aligns directly with the rule already stated in
[`governance_aware_learning_next_stage_plan.md`](/Users/ningli/project/seedcore/docs/development/governance_aware_learning_next_stage_plan.md:1):

> The model may learn. SeedCore still decides.

## What SeedCore Should Reuse

### 1. Contract-shaped instruction tuning

The highest-value reuse is to fine-tune for exact, bounded outputs instead of
free-form assistant prose.

Good target outputs for SeedCore include:

- `reason_code`
- `trust_gap_codes`
- `required_obligations`
- `abstain`
- `warnings`
- `operator_explanation`
- `verification_summary`

This is the right use of instruction tuning inside SeedCore because these are
all **compilable governance components**, not alternate authority systems.

### 2. Tool-use tuning for SeedCore surfaces

Hermes puts unusual emphasis on function calling and structured tool use. That
is directly relevant to SeedCore’s model-facing surfaces.

Best candidates:

- owner-context preflight
- `agent-actions/evaluate` with `no_execute=true`
- verification/replay retrieval
- policy-assistant support flows
- operator copilot read-only evidence lookup

This means the model should be trained to:

- choose the right tool
- supply valid structured arguments
- wait for tool responses
- summarize returned data without inventing missing facts

### 3. Authority abstention tuning

This is the most important SeedCore-specific adaptation.

General instruction tuning often makes a model more eager to satisfy the user.
That is dangerous near authority boundaries.

SeedCore should instead tune for explicit abstention categories such as:

- `unsure_of_authority`
- `insufficient_evidence`
- `stale_context`
- `scope_mismatch`
- `requires_manual_review`

If Hermes teaches "follow the user well," the SeedCore version must teach:

> follow the contract well, and halt when authority or evidence is ambiguous.

### 4. Evidence-grounded explanation scaffolds

Hermes-style structured generation is also useful for explanation surfaces, but
only when explanations are grounded in artifacts and runtime outputs.

Good SeedCore uses:

- operator case summaries
- replay verification summaries
- preflight explanation scaffolds
- policy-assistant draft explanations

Bad SeedCore use:

- free-form justifications that outrun the actual artifacts
- summarization that implies authority was granted when it was not

## What SeedCore Should Not Reuse Directly

### 1. General roleplay as a primary goal

Hermes openly optimizes for roleplay and strong persona steerability.

That may be useful for broad assistant products, but it is not the core need
for SeedCore’s trust runtime surfaces.

For SeedCore:

- role conditioning is acceptable
- theatrical persona conditioning is low priority
- hot-path-adjacent assistants should optimize for precision, not theatricality

### 2. User-pleasing helpfulness near authority boundaries

SeedCore should not import any tuning norm that pushes the model to "find a way
to help" when the correct answer is to halt.

Near governed boundaries, the preferred behavior is:

- stop
- classify the problem
- request missing evidence
- route to preflight
- route to human review

### 3. Any path that turns the model into a soft PDP

Instruction tuning is acceptable for:

- prediction
- explanation
- refinement
- abstention
- preflight support

It is not acceptable as a replacement for:

- policy evaluation
- execution-token minting
- final governed disposition

## Best-Fit SeedCore Workstreams

### Workstream A: Distilled preflight scaffold

Train a model to produce bounded preflight-support outputs from gateway-shaped
requests and replay examples.

Target outputs:

- likely `reason_code`
- likely `trust_gap_codes`
- likely `required_obligations`
- `abstain`

This aligns with the "Distilled Policy Scaffolds" objective in
[`governance_aware_learning_next_stage_plan.md`](/Users/ningli/project/seedcore/docs/development/governance_aware_learning_next_stage_plan.md:72).

### Workstream B: Abstention-first authority behavior

Build a supervised and preference-tuned dataset from:

- denied requests
- stale-context cases
- scope mismatch cases
- incomplete evidence cases
- manual escalation examples

Preferred behavior:

- explicit abstention over invented confidence

This aligns with the "HALT / Abstention Behavior" objective in
[`governance_aware_learning_next_stage_plan.md`](/Users/ningli/project/seedcore/docs/development/governance_aware_learning_next_stage_plan.md:89).

### Workstream C: Tool-call discipline for policy/operator assistants

Train models against SeedCore tools and schemas so they can:

- call preflight correctly
- call read-only verification/replay tools correctly
- return exact structured summaries
- avoid fabricating non-tool-backed claims

This is especially relevant for the surfaces described in
[`policy_assistant_mvp_spec.md`](/Users/ningli/project/seedcore/docs/development/policy_assistant_mvp_spec.md:1)
and the operator/verification UX contract family.

### Workstream D: Evidence-grounded explanation generation

Teach the model to generate concise explanation scaffolds only from:

- replay artifacts
- verification results
- trust-gap lists
- policy outputs

This should produce explanations that are:

- schema-bounded
- citation-friendly
- operator-legible
- replay-linkable

## A SeedCore-Specific Training Taxonomy

If SeedCore adapts the Hermes pattern, the task families should probably be:

- **preflight classification**
  - predict reason codes, trust gaps, obligations, abstention
- **tool invocation**
  - select and call the correct tool with valid arguments
- **artifact-grounded summarization**
  - summarize verification or replay outputs without invention
- **authority abstention**
  - produce halt-style outputs when evidence is missing or scope is invalid
- **repair suggestion**
  - propose deterministic next steps for malformed evidence or missing fields

These are better fits than generic "assistant chat" data because they map onto
typed, replay-linkable runtime seams.

## Suggested First Experiment

The best first experiment is small and strict.

### Dataset

Build a compact supervised set from real SeedCore examples:

- `allow`
- `deny`
- `quarantine`
- `escalate`
- stale telemetry
- missing approval
- scope mismatch
- missing evidence / trust-gap cases

Input shape:

- gateway request
- relevant preflight context
- selected replay/verification snippets

Output shape:

```json
{
  "reason_code": "scope_mismatch",
  "trust_gap_codes": ["owner_trust_modality_violation"],
  "required_obligations": ["manual_review"],
  "abstain": true,
  "operator_explanation": "Observed telemetry and declared scope do not align."
}
```

### Objective

Optimize first for:

- exact field validity
- taxonomy validity
- abstention precision
- tool-call validity

Do not optimize first for:

- eloquence
- conversational style
- broad roleplay quality

### Promotion rule

The resulting student artifact should be:

- shadow-evaluated only
- never the final PDP
- fail-closed when uncertain
- pinned to schema and version

## Recommended SeedCore Framing

When describing this line of work internally, the best framing is:

> SeedCore should borrow Hermes-style instruction tuning only where it improves
> contract obedience, tool discipline, abstention, and evidence-grounded
> explanation.

Not:

> SeedCore should train a nicer assistant.

## Bottom Line

Nous/Hermes is relevant to SeedCore because it demonstrates that post-training
can strongly improve:

- instruction following
- structured output reliability
- tool use
- steerability

The SeedCore adaptation should be narrow and trust-runtime-aligned:

- train for **typed governance outputs**
- train for **tool correctness**
- train for **abstention under authority uncertainty**
- train for **artifact-grounded explanations**

The model may learn better behavior.
SeedCore still owns the decision.

## External References

- [Hermes 3 model card](https://huggingface.co/NousResearch/Hermes-3-Llama-3.1-405B)
- [Hermes 3 technical report (Aug 15, 2024)](https://nousresearch.com/wp-content/uploads/2024/08/Hermes-3-Technical-Report.pdf?_bhlid=2cea4464ae5cd2d7bf193f58bed975ea31c5b689)
- [Hermes Function Calling repo](https://github.com/NousResearch/Hermes-Function-Calling)
- [OpenHermes 2.5 dataset card](https://huggingface.co/datasets/teknium/OpenHermes-2.5)
- [Hermes 4.3 blog](https://nousresearch.com/introducing-hermes-4-3)
