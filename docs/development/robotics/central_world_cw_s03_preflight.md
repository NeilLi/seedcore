# CW-S03: policy/model compatibility preflight and refusal report

Date: 2026-10-26
Status: Local offline preflight slice delivered; both real policy-execution candidates blocked; full CW-POL-01 / browser policy execution remains open
Review: CW-POL-01-PREFLIGHT (local review reference, not a production deny code)
Owner role: Simulation/policy lead with verification review
Bounded effort: one workday, 4–6 focused hours; review date 26 October

## Scope and input boundary

The [canonical queue](../current_next_steps.md) selected a compatibility preflight
following the [CW-S02 fixed-preset runtime](central_world_cw_s02_mujoco.md).
This slice inventories current bytes, evaluates declared contracts, reproduces
available CPU artifact replay and emits exact refusal reasons. It adds no
browser ONNX provider, trained controller, model migration or actuator path.

[`policyCompatibility.ts`](../../../ts/packages/wasm-sim-bridge/src/policyCompatibility.ts)
exports `assessPolicyCompatibility` and `computePolicyAdapterDigest`. The bounded
`seedcore.cw-s03.policy-preflight.v1` input binds independently retained policy,
selected model and adapter digests to typed policy/model/adapter contracts.
The report binds the canonical input and all findings with its own digest.
It checks exact tensor names/shapes/dtypes, body identity/topology, joint order,
full-precision observation home, action scale/meaning, observation field units
and layout, normalization, previous-action semantics, actuator equivalence and
integer physics/policy cadence. Unknown, malformed, oversized or nonfinite
inputs cannot produce a consistent result.

Evidence roles are separate: artifact replay, independent training checkpoint
outputs, runtime/model/policy pair validation, browser operator coverage and
browser inference timing. Verified records require source hashes and current
policy/model/adapter bindings appropriate to their role. A replay record cannot
be relabeled as checkpoint evidence or reuse the replay golden hash as its
independent reference. These are metadata and evidence-binding checks, not
publisher authentication or a review of arbitrary external evidence bytes.
The local inventory collector establishes the inspected metadata from local pins;
other callers must retain their expected pins independently.

Every report has `physicalAcceptance: false`, `executionAuthority: none` and
`runtimeQualification: not_granted`. `contract_consistent` is an offline contract
result, never permission to run a policy. The positive fixture is explicitly
`synthetic_fixture`: declared mathematical contracts with no ONNX file,
training result or qualified inference path. Declared synthetic evidence is rejected for
an input labeled as real local artifacts.

## Local inventory and available evidence

[`policy_preflight_inventory.py`](../../../src/seedcore/robotics/policy_preflight_inventory.py)
reads bounded local files and immutable Git objects without downloading or
executing upstream code. The
[input pin manifest](../../../packages/robotics-profiles/reviews/cw-s03-preflight-inputs-v1.json)
freezes the existing deployment profile, golden file and observation encoder.
The existing model-package verifier checks all body-package bytes against its
pinned manifest. Existing catalog, deployment, policy and model source pins are
not rewritten.

Observed on the local verification environment:

- `alpha_walking.onnx`: **793,705 bytes**, SHA-256
  `e36332d383997d51401897734cd3e79cf5038406feddb18b4d57ecfb141daa6c`.
  Actual ports are `obs: float32[1,61]` and `actions: float32[1,14]`.
- The 14 policy joints, embedded normalization and 20 ms policy period retain
  the existing Microduck source contract. Rounded ONNX display home metadata
  never replaces the full-precision deployment home. ONNX `run_path` is `None`.
- Seven pinned runtime/RL source files were available and matched immutable
  source bytes in local checkouts. Missing checkouts on another host remain
  explicitly missing in the inventory; no fetch is attempted.
- `onnxruntime==1.31.0`, CPU-only: all **16 retained artifact golden cases**
  passed at existing observation `atol=1e-6`, action `atol=1e-5`, `rtol=0`.
  The goldens derive from pinned Rust observation construction and ONNX
  ReferenceEvaluator output. They are not independent training-checkpoint
  outputs; `training_checkpoint_parity: not_available` is preserved.
- Optional `onnx==1.17.0` graph inventory found opset 18 and nine top-level
  nodes using `Div`, `Elu`, `Gemm` and `Sub`. This inventories operators, without
  asserting that a browser provider supports them or meets inference deadlines.
- Policy license/source-run evidence and exact trained actuator equivalence
  are unrecorded. The body's Apache-2.0 record does not establish policy rights.

No MuJoCo stepping, hardware access, provider installation or dependency upgrade
occurs in the inventory or compatibility check.

## Candidate decisions

| Candidate | Actual scope | Decision and principal blockers |
| --- | --- | --- |
| Microduck native policy candidate | Pinned floating-base body, 14 actions and the existing read-only observation contract | **BLOCKED**: no policy-to-runtime adapter, independent checkpoint outputs, trained actuator equivalence, qualified runtime pair, recorded policy license, browser operator coverage or browser timing |
| Microduck policy on CW-S02 tabletop | CW-S01 compiled two-joint reference, `dt=0.002`, position `kp=1`; existing CW-S02 rehearsal runtime | **BLOCKED**: all policy evidence gaps above, plus wrong policy body/topology, 14-vs-2 action dimensions, exact joint/home mismatch, missing policy tensors and observation encoder |

The second candidate does not reinterpret the 61/14 Microduck contract as a
custom tabletop controller. The first does not promote the read-only driver
into a governed motor/control path. A current artifact-replay result cannot
close either candidate's missing training/browser evidence.

## Reproduction and retained evidence

```bash
# Offline preflight; missing optional policy cache/dependencies are explicit.
node tools/robotics/verify-cw-s03.cjs

# Strict local acceptance: fail unless the pinned CPU artifact replay executes.
node tools/robotics/verify-cw-s03.cjs --require-artifact-replay
```

The runner rebuilds contracts/DRC/bridge, typechecks, runs **43 TS refusal and
consistency tests + 7 Python inventory tests**, generates the inventory, and
repeats report generation to verify byte-identical output. It removes stale
output files before running. Invalid source pins or failed inspection/replay
fail the verifier. An expected blocked runtime decision is a valid preflight
software result, labeled `checks_passed_runtime_blocked`.

Broader local regressions passed `verify-authoring.cjs --browser` (**195 workspace
TS + 22 API tests + 36 Chrome checks + 2 native download tests**),
`verify-cw-s02.cjs` (**18 TS + 15 native tests**) and the existing Microduck
read-only suite (**33 Python tests**). These preserve the prior authoring,
fixed-preset runtime and no-motion observation boundaries.

With no policy cache or optional dependencies, the default run can report
`checks_passed_artifact_replay_not_run_runtime_blocked`; it cannot claim artifact
replay acceptance. `--require-artifact-replay` fails in that case. CI does not
silently download the policy or install policy inference dependencies.

Retained under `artifacts/robotics/cw-s03/`:

- `inventory.json`: exact local byte/source inventory, observed ports/metadata,
  operator list, replay case count/errors and unresolved evidence.
- `compatibility.json`: both complete inputs and blocked decisions with source,
  adapter, input, report and matrix digests.
- `verification.json`: verification status, source hashes, checks, replay inclusion
  flag and unique blocker codes for each candidate.

CI retains all three files. They are local software evidence, not signed
hardware receipts. The [acceptance matrix](central_world_acceptance_matrix.md)
keeps full CW-POL-01 open.

## Handoff and remaining work

This completes the bounded CW-S03 **preflight** allocation. **CW-S04 bounded
tabletop gesture compilation/replay is next** and can use the existing CW-S02
profile without a trained policy. Full CW-S03 inference/runtime integration
resumes only with compatible, independently referenced policy/model/actuator
semantics, rights and browser provider/timing evidence. CW-D01 physical data,
live Agent/PDP admission and hardware gates remain separate.
