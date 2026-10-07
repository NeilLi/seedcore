# SIM-1 local qualification — 2026-10-07

Local SIM-1 passes the stated numerical, protocol, transfer and browser harness
checks. This is engineering evidence for the known two-link JS model. It is not
a qualification of general dynamics, hardware, tablets or the full release.

Environment: Apple M3, 8 CPU cores, 8 GiB RAM; macOS 26.5.1 build 25F80;
Chrome 155.0.0.0; Node 25.9.0; repository TypeScript 5.9.3. Browser measurements
ran in a foreground tab over localhost HTTP. Chrome reports a privacy-reduced
macOS 10.15.7 user agent and an 8 GiB device-memory bucket; host OS/RAM above
were read independently. There is one measured run per case, not a population
or endurance result.

## Automated acceptance

`node tools/mini-sim/verify.cjs` passes: generated JS/declarations agree with
strict TypeScript compilation, syntax checks pass, and all 37 tests pass.
The original 12 numerical invariants remain unchanged. Worker tests cover every
sample of all three lessons against the direct engine, pause/reset, stale
commands, identity mismatch, exact-tick controls within chunks, same-tick order,
queue capacity, real transfer detachment, pool exhaustion and reset with loans.
UI tests cover identity/frame rejection, in-flight pauses, missing observations,
timeout recovery and hidden-tab pausing. Compiler tests independently compare
SHA-256 with Node crypto and lock a golden model/recipe/reset fixture.

## Browser harness

Serve the repository root, then open
`http://127.0.0.1:8766/tools/mini-sim/browser-qualification.html`.
The [raw report](qualification-2026-10-07.json) contains exact identities,
timings, diagnostics and browser metadata.

| Case | Active wall time for 6 sim seconds | Foreground RAF p95 | Pause ack | Observations | Max trace error |
| --- | ---: | ---: | ---: | ---: | ---: |
| Reach | 6002.7 ms | 9.3 ms | 0.1 ms | 361 | 0 |
| Motors off | 6002.6 ms | 9.2 ms | 0.4 ms | 361 | 0 |
| Heavy arm | 6003.6 ms | 9.2 ms | 0.3 ms | 361 | 0 |
| Reach, 250 ms UI stall | 6252.7 ms | 9.2 ms | 1.8 ms after UI unblocked | 361 | 0 |

Every case ends at tick 2880. Exactly three 96-byte snapshot buffers are
allocated; the stall case reaches three outstanding loans and reports one
buffer wait. The worker stays at tick 24 until the page returns ownership,
acknowledges pause without a spare buffer, then continues without gaps or
duplicates. No live engine state is transferred. Zero trace error compares joint
position (rad) and velocity (rad/s) with the same browser's direct JS reference;
this is not a cross-engine accuracy claim.

Normal wall pacing is approximately 1× with a declared tolerance of one
16.7 ms timer quantum over six seconds. The stall case deliberately takes
longer and must report its buffer wait. All measured pause acknowledgements are
below the proposed 100 ms budget. RAF p95 is below 33 ms for the developer
harness; it does not measure the learner Canvas renderer. The longest measured
normal physics chunk is 1.3 ms. Strictly greater-than-or-equal-to-1× wall pacing
without timing tolerance is not established by these runs.

An initial full-period-after-work scheduler measured 0.943–0.955× in normal
cases. Switching to monotonic deadlines removes cumulative computation delay.
Late callbacks still rebase the schedule and keep the same fixed physics step,
so load slows simulated time instead of dropping ticks.

The learner page was separately checked for single step, continue and target
completion: it displays Finished at 6.00 s with a settled tip and enabled
recorded replay/save controls. See the [UI capture](learner-ui-2026-10-07.png).

## Remaining qualification

Representative low-power laptop/tablet, other browsers, full learner-renderer
frame intervals, cold-load network/startup budgets, compressed transfer size,
whole-browser memory, offline reopening and moderated learner usability remain
open. Wasm memory/build limits and complete resumable state belong to SIM-2.
The three-buffer footprint is a transport bound, not a whole-process memory
measurement. No SeedCore admission, external deployment or hardware experiment
was added.
