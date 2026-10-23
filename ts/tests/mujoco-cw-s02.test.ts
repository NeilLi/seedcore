import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { canonicalAssemblyString } from '@seedcore/contracts';
import { sha256Hex } from '@seedcore/drc-solver';
import {
  CW_S02_MUTATION_PATHS,
  CwS02Error,
  MUJOCO_WASM_BYTES,
  MUJOCO_WASM_PROFILE,
  MUJOCO_WASM_SHA256,
  MUJOCO_WASM_VERSION,
  MujocoBoundedExecutor,
  PLANAR_SIM3_WASM_BYTES,
  buildDeterministicRehearsalProposal,
  compileAssemblyToMjcf,
  createMujocoModelSession,
  loadVerifiedMujocoModule,
  readPinnedMujocoWasm,
  verifyPinnedMujocoWasmBytes,
  type CwS02AttemptBinding,
} from '@seedcore/wasm-sim-bridge';
import { studioReferenceInput } from './fixtures/cw-s01.js';

const wasmBytes = new Uint8Array(
  readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../node_modules/@mujoco/mujoco/mujoco.wasm')),
);

function makeCompiledReference(mode: 'position' | 'torque' = 'position') {
  const input = studioReferenceInput();
  input.options.actuatorMode = mode;
  if (mode === "position") input.options.positionGain = 1;
  const model = compileAssemblyToMjcf(input);
  const binding = {
    assemblyDigest: model.manifest.assemblyDigest,
    catalogDigest: model.manifest.catalogDigest,
    drcDigest: model.manifest.drcDigest,
    modelDigest: model.modelDigest,
  };
  const attempt: CwS02AttemptBinding = {
    ...binding,
    revisionDigest: model.manifest.assemblyDigest,
    authorityEpoch: 3,
    generation: 1,
    startedMonotonicMs: 1000,
    deadlineMonotonicMs: 4000,
  };
  return { model, binding, attempt };
}

test('CW-SIM-02 verifies exact pinned @mujoco/mujoco@3.15.0 Wasm bytes and SHA-256', async () => {
  const verified = await verifyPinnedMujocoWasmBytes(wasmBytes);
  assert.equal(verified.byteLength, MUJOCO_WASM_BYTES);
  const streamed = await readPinnedMujocoWasm(new Response(wasmBytes, { status: 200 }));
  assert.equal(streamed.byteLength, MUJOCO_WASM_BYTES);
});

test('CW-SIM-02 rejects corrupt magic headers, flipped Wasm bytes, truncated streams, and HTTP errors', async () => {
  const corrupted = new Uint8Array(wasmBytes);
  corrupted[corrupted.length - 1] ^= 0xff;
  await assert.rejects(
    () => verifyPinnedMujocoWasmBytes(corrupted),
    (err: unknown) => err instanceof CwS02Error && err.code === 'WASM_PIN_MISMATCH',
  );

  const badMagic = new Uint8Array(wasmBytes);
  badMagic[0] = 0x7f;
  await assert.rejects(
    () => verifyPinnedMujocoWasmBytes(badMagic),
    (err: unknown) => err instanceof CwS02Error && err.code === 'WASM_PIN_MISMATCH',
  );

  await assert.rejects(
    () => readPinnedMujocoWasm(new Response(wasmBytes.subarray(0, 4096), { status: 200 })),
    (err: unknown) => err instanceof CwS02Error && err.code === 'WASM_PIN_MISMATCH',
  );
  await assert.rejects(
    () => readPinnedMujocoWasm(new Response(null, { status: 404 })),
    (err: unknown) => err instanceof CwS02Error && err.code === 'WASM_FETCH_FAILED',
  );
});

test('CW-SIM-02 explicitly forbids silent fallback to the 13,242-byte planar SIM-3 Wasm binary', async () => {
  const planarBytes = new Uint8Array(PLANAR_SIM3_WASM_BYTES);
  await assert.rejects(
    () => verifyPinnedMujocoWasmBytes(planarBytes),
    (err: unknown) => err instanceof CwS02Error && err.code === 'PLANAR_FALLBACK_FORBIDDEN',
  );
  await assert.rejects(
    () => readPinnedMujocoWasm(new Response(planarBytes, { status: 200 })),
    (err: unknown) => err instanceof CwS02Error && err.code === 'PLANAR_FALLBACK_FORBIDDEN',
  );
  await assert.rejects(
    () => loadVerifiedMujocoModule(planarBytes),
    (err: unknown) => err instanceof CwS02Error && err.code === 'PLANAR_FALLBACK_FORBIDDEN',
  );
});

test('CW-SIM-02 loads verified CW-S01 model bundles, inspects topology/inertials, evaluates FK, and fences disposed sessions', async () => {
  const mujoco = await loadVerifiedMujocoModule(wasmBytes);
  const { model, binding } = makeCompiledReference('position');
  const session = createMujocoModelSession(mujoco, model, binding);
  const info = session.inspectModel();
  assert.equal(info.profile, MUJOCO_WASM_PROFILE);
  assert.equal(info.engineVersion, MUJOCO_WASM_VERSION);
  assert.equal(info.wasmSha256, MUJOCO_WASM_SHA256);
  assert.equal(info.planarFallbackUsed, false);
  assert.equal(info.physicalAcceptance, false);
  assert.equal(info.executionAuthority, 'none');
  assert.equal(info.nq, 2);
  assert.equal(info.nv, 2);
  assert.equal(info.nu, 2);
  assert.equal(info.nbody, 5);

  const fk = session.evaluateForwardKinematics([0.1, -0.1]);
  assert.equal(fk.bodies.length, 4);
  assert.deepEqual(fk.qpos, [0.1, -0.1]);

  session.dispose();
  assert.equal(session.isDisposed, true);
  assert.throws(
    () => session.inspectModel(),
    (err: unknown) => err instanceof CwS02Error && err.code === 'SESSION_DISPOSED',
  );
});

test('CW-SIM-02 rejects tampered model bindings, unsafe XML tags, and topology mismatches', async () => {
  const mujoco = await loadVerifiedMujocoModule(wasmBytes);
  const { model, binding } = makeCompiledReference('position');

  assert.throws(
    () => createMujocoModelSession(mujoco, model, { ...binding, modelDigest: '0'.repeat(64) }),
    (err: unknown) => err instanceof CwS02Error && err.code === 'MODEL_BINDING_MISMATCH',
  );

  const unsafeXml = model.xml.replace('<worldbody>', '<asset><mesh name="m" file="bad.stl"/></asset><worldbody>');
  const unsafePayload = {
    schemaVersion: model.schemaVersion,
    scope: model.scope,
    physicalAcceptance: model.physicalAcceptance,
    executionAuthority: model.executionAuthority,
    xml: unsafeXml,
    manifest: model.manifest,
  };
  const unsafeModel = { ...unsafePayload, modelDigest: sha256Hex(canonicalAssemblyString(unsafePayload)) };
  assert.throws(
    () => createMujocoModelSession(mujoco, unsafeModel, { ...binding, modelDigest: unsafeModel.modelDigest }),
    (err: unknown) => err instanceof CwS02Error && err.code === 'UNSUPPORTED_SUBSET',
  );

  const {modelDigest:_old,...wrongTopologyPayload} = structuredClone(model);
  wrongTopologyPayload.manifest.bodies.pop();
  const wrongTopology = {...wrongTopologyPayload,modelDigest:sha256Hex(canonicalAssemblyString(wrongTopologyPayload))};
  assert.throws(() => createMujocoModelSession(mujoco,wrongTopology,{...binding,modelDigest:wrongTopology.modelDigest}),
    (error: unknown) => error instanceof CwS02Error && error.code === 'MODEL_TOPOLOGY_MISMATCH');

  const wrongDtXml = model.xml.replace('timestep="0.002"', 'timestep="0.005"');
  const wrongDtPayload = { ...unsafePayload, xml: wrongDtXml };
  const wrongDtModel = { ...wrongDtPayload, modelDigest: sha256Hex(canonicalAssemblyString(wrongDtPayload)) };
  assert.throws(
    () => createMujocoModelSession(mujoco, wrongDtModel, { ...binding, modelDigest: wrongDtModel.modelDigest }),
    (err: unknown) => err instanceof CwS02Error && err.code === 'MODEL_TOPOLOGY_MISMATCH',
  );
});

test('CW-SIM-03 advances integer ticks, enforces decimation and catch-up ceiling, and reproduces identical traceDigest', async () => {
  const mujoco = await loadVerifiedMujocoModule(wasmBytes);
  const { model, binding, attempt } = makeCompiledReference('torque');
  const session = createMujocoModelSession(mujoco, model, binding);
  const restAngles = model.manifest.joints.map(j => j.restAngleRad);

  try {
    const runOnce = () => {
      const exec = new MujocoBoundedExecutor(session, {
        policyDecimation: 10,
        totalSubsteps: 40,
        maxSubstepsPerBatch: 8,
        maxStallMs: 250,
        maxCaptureSamples: 40,
        attempt,
      });
      let now = attempt.startedMonotonicMs;
      while (exec.getSummary().status === 'running') {
        now += 10;
        const due = exec.dueSubsteps(now);
        assert.ok(due <= 8);
        exec.stepBatch(now, due, policyStep =>
          buildDeterministicRehearsalProposal(attempt, session.actuatorCtrlRanges, restAngles, 'torque', policyStep, now),
        );
      }
      return exec.getSummary();
    };
    const s1 = runOnce();
    const s2 = runOnce();
    assert.equal(s1.status, 'completed');
    assert.equal(s1.executedSubsteps, 40);
    assert.equal(s1.capturedSamples, 40);
    assert.equal(s1.policyUpdates, 4);
    assert.deepEqual(s1.mutationPathsGuarded, CW_S02_MUTATION_PATHS);
    assert.equal(s1.traceDigest, s2.traceDigest);
  } finally {
    session.dispose();
  }
});

test('CW-SIM-03 fences UI/worker stalls beyond maxStallMs without enlarging dt or dropping captured samples', async () => {
  const mujoco = await loadVerifiedMujocoModule(wasmBytes);
  const { model, binding, attempt } = makeCompiledReference('torque');
  const session = createMujocoModelSession(mujoco, model, binding);
  const restAngles = model.manifest.joints.map(j => j.restAngleRad);

  try {
    const stalled = new MujocoBoundedExecutor(session, {
      policyDecimation: 10,
      totalSubsteps: 40,
      maxSubstepsPerBatch: 8,
      maxStallMs: 250,
      maxCaptureSamples: 40,
      attempt,
    });
    stalled.stepBatch(1004, stalled.dueSubsteps(1004), policyStep =>
      buildDeterministicRehearsalProposal(attempt, session.actuatorCtrlRanges, restAngles, 'torque', policyStep, 1004),
    );
    assert.equal(stalled.getSummary().executedSubsteps, 2);
    assert.throws(
      () => stalled.dueSubsteps(1300),
      (err: unknown) => err instanceof CwS02Error && err.code === 'CLOCK_STALL_FENCED',
    );
    assert.equal(stalled.getSummary().status, 'fenced');
    assert.equal(stalled.getSummary().fenceCode, 'CLOCK_STALL_FENCED');
    assert.equal(stalled.getSummary().capturedSamples, 2);
    assert.equal(session.model.opt.timestep, 0.002);
  } finally {
    session.dispose();
  }
});

test('CW-SIM-03 fences monotonic clock rollback, capture buffer overflow, and hidden-tab interruption before mj_step', async () => {
  const mujoco = await loadVerifiedMujocoModule(wasmBytes);
  const { model, binding, attempt } = makeCompiledReference('torque');
  const session = createMujocoModelSession(mujoco, model, binding);
  const restAngles = model.manifest.joints.map(j => j.restAngleRad);

  try {
    const rollback = new MujocoBoundedExecutor(session, {
      policyDecimation: 10,
      totalSubsteps: 20,
      attempt,
    });
    rollback.dueSubsteps(1010);
    assert.throws(
      () => rollback.dueSubsteps(1005),
      (err: unknown) => err instanceof CwS02Error && err.code === 'CLOCK_ROLLBACK_FENCED',
    );

    const overflow = new MujocoBoundedExecutor(session, {
      policyDecimation: 5,
      totalSubsteps: 10,
      maxCaptureSamples: 3,
      attempt,
    });
    assert.throws(
      () =>
        overflow.stepBatch(1010, 4, policyStep =>
          buildDeterministicRehearsalProposal(attempt, session.actuatorCtrlRanges, restAngles, 'torque', policyStep, 1010),
        ),
      (err: unknown) =>
        err instanceof CwS02Error && err.code === 'CAPTURE_OVERFLOW' && err.vetoReason === 'CAPTURE_OVERFLOW',
    );
    assert.equal(overflow.getSummary().executedSubsteps, 3);
    assert.equal(overflow.getSummary().capturedSamples, 3);

    const hidden = new MujocoBoundedExecutor(session, {
      policyDecimation: 5,
      totalSubsteps: 10,
      attempt,
    });
    hidden.stepSubstep(1002, policyStep =>
      buildDeterministicRehearsalProposal(attempt, session.actuatorCtrlRanges, restAngles, 'torque', policyStep, 1002),
    );
    hidden.notifyVisibilityHidden();
    assert.throws(
      () =>
        hidden.stepSubstep(1004, policyStep =>
          buildDeterministicRehearsalProposal(attempt, session.actuatorCtrlRanges, restAngles, 'torque', policyStep, 1004),
        ),
      (err: unknown) =>
        err instanceof CwS02Error && err.code === 'TAB_HIDDEN_FENCED' && err.vetoReason === 'TAB_HIDDEN_FENCED',
    );
    assert.equal(hidden.getSummary().executedSubsteps, 1);
  } finally {
    session.dispose();
  }
});

test('CW-SIM-04 clears unauthorized qfrc_applied and xfrc_applied disturbances before every substep', async () => {
  const mujoco = await loadVerifiedMujocoModule(wasmBytes);
  const { model, binding, attempt } = makeCompiledReference('torque');
  const session = createMujocoModelSession(mujoco, model, binding);
  const restAngles = model.manifest.joints.map(j => j.restAngleRad);

  try {
    const baseline = new MujocoBoundedExecutor(session, { policyDecimation: 5, totalSubsteps: 10, attempt });
    for (let k = 1; k <= 10; k++) {
      baseline.stepSubstep(1000 + k * 2, policyStep =>
        buildDeterministicRehearsalProposal(attempt, session.actuatorCtrlRanges, restAngles, 'torque', policyStep, 1000 + k * 2),
      );
    }
    const perturbed = new MujocoBoundedExecutor(session, { policyDecimation: 5, totalSubsteps: 10, attempt });
    for (let k = 1; k <= 10; k++) {
      session.data.qfrc_applied[0] = 99.5;
      session.data.xfrc_applied[6] = -42.0;
      perturbed.stepSubstep(1000 + k * 2, policyStep =>
        buildDeterministicRehearsalProposal(attempt, session.actuatorCtrlRanges, restAngles, 'torque', policyStep, 1000 + k * 2),
      );
    }
    assert.equal(perturbed.getSummary().clearedExternalMutations, 20);
    assert.deepEqual(perturbed.getSummary().finalQpos, baseline.getSummary().finalQpos);
    assert.deepEqual(perturbed.getSummary().finalQvel, baseline.getSummary().finalQvel);
  } finally {
    session.dispose();
  }
});

test('CW-SIM-04 detects and fences unauthorized direct qpos/qvel/act or timestep mutation between substeps', async () => {
  const mujoco = await loadVerifiedMujocoModule(wasmBytes);
  const { model, binding, attempt } = makeCompiledReference('torque');
  const session = createMujocoModelSession(mujoco, model, binding);
  const restAngles = model.manifest.joints.map(j => j.restAngleRad);

  try {
    const tamperedState = new MujocoBoundedExecutor(session, { policyDecimation: 5, totalSubsteps: 10, attempt });
    tamperedState.stepSubstep(1002, policyStep =>
      buildDeterministicRehearsalProposal(attempt, session.actuatorCtrlRanges, restAngles, 'torque', policyStep, 1002),
    );
    session.data.qpos[0] += 0.25;
    assert.throws(
      () => tamperedState.stepSubstep(1004),
      (err: unknown) =>
        err instanceof CwS02Error && err.code === 'EXTERNAL_STATE_TAMPERED' && err.vetoReason === 'EXTERNAL_STATE_TAMPERED',
    );
    assert.equal(tamperedState.getSummary().executedSubsteps, 1);

    const tamperedDt = new MujocoBoundedExecutor(session, { policyDecimation: 5, totalSubsteps: 10, attempt });
    session.model.opt.timestep = 0.008;
    assert.throws(
      () =>
        tamperedDt.stepSubstep(1002, policyStep =>
          buildDeterministicRehearsalProposal(attempt, session.actuatorCtrlRanges, restAngles, 'torque', policyStep, 1002),
        ),
      (err: unknown) =>
        err instanceof CwS02Error && err.code === 'TIMESTEP_ALTERED' && err.vetoReason === 'TIMESTEP_ALTERED',
    );
    session.model.opt.timestep = 0.002;
  } finally {
    session.dispose();
  }
});

test('CW-SIM-04 vetoes stale generation, wrong authorityEpoch, wrong modelDigest, and expired proposals before mj_step', async () => {
  const mujoco = await loadVerifiedMujocoModule(wasmBytes);
  const { model, binding, attempt } = makeCompiledReference('torque');
  const session = createMujocoModelSession(mujoco, model, binding);
  const restAngles = model.manifest.joints.map(j => j.restAngleRad);

  try {
    for (const [override, expectedReason] of [
      [{ generation: attempt.generation + 1 }, 'STALE_GENERATION'],
      [{ authorityEpoch: attempt.authorityEpoch + 1 }, 'AUTHORITY_EPOCH_MISMATCH'],
      [{ modelDigest: 'f'.repeat(64) }, 'MODEL_DIGEST_MISMATCH'],
      [{ proposedAtMonotonicMs: 1000, expiresAtMonotonicMs: 1001 }, 'CONTROL_EXPIRED'],
    ] as const) {
      const exec = new MujocoBoundedExecutor(session, { policyDecimation: 5, totalSubsteps: 10, attempt });
      exec.submitControlProposal({
        ...buildDeterministicRehearsalProposal(attempt, session.actuatorCtrlRanges, restAngles, 'torque', 0, 1002),
        ...override,
      });
      assert.throws(
        () => exec.stepSubstep(1002),
        (err: unknown) => err instanceof CwS02Error && err.vetoReason === expectedReason,
      );
      assert.equal(exec.getSummary().executedSubsteps, 0);
      assert.equal(exec.getSamples()[0].stepExecuted, false);
    }
  } finally {
    session.dispose();
  }
});

test('CW-SIM-04 vetoes missing, wrong-dimension, non-finite, and out-of-range controls without silent clamping', async () => {
  const mujoco = await loadVerifiedMujocoModule(wasmBytes);
  const { model, binding, attempt } = makeCompiledReference('torque');
  const session = createMujocoModelSession(mujoco, model, binding);
  const restAngles = model.manifest.joints.map(j => j.restAngleRad);

  try {
    const missing = new MujocoBoundedExecutor(session, { policyDecimation: 5, totalSubsteps: 10, attempt });
    assert.throws(
      () => missing.stepSubstep(1002),
      (err: unknown) => err instanceof CwS02Error && err.vetoReason === 'CONTROL_MISSING',
    );

    for (const [targetCtrl, expectedReason] of [
      [[0], 'CONTROL_DIMENSION_MISMATCH'],
      [[Number.NaN, 0], 'CONTROL_NONFINITE'],
      [[Number.POSITIVE_INFINITY, 0], 'CONTROL_NONFINITE'],
      [[9.99, 0], 'CONTROL_OUT_OF_RANGE'],
      [[0, -9.99], 'CONTROL_OUT_OF_RANGE'],
    ] as const) {
      const exec = new MujocoBoundedExecutor(session, { policyDecimation: 5, totalSubsteps: 10, attempt });
      exec.submitControlProposal({
        ...buildDeterministicRehearsalProposal(attempt, session.actuatorCtrlRanges, restAngles, 'torque', 0, 1002),
        targetCtrl,
      });
      assert.throws(
        () => exec.stepSubstep(1002),
        (err: unknown) => err instanceof CwS02Error && err.vetoReason === expectedReason,
      );
      assert.equal(exec.getSummary().executedSubsteps, 0);
      assert.deepEqual(Array.from(session.data.ctrl), [0, 0]);
    }
  } finally {
    session.dispose();
  }
});

test('CW-SIM-04 enforces mid-decimation revocation, attempt deadline expiration, and policy/model switch fencing', async () => {
  const mujoco = await loadVerifiedMujocoModule(wasmBytes);
  const { model, binding, attempt } = makeCompiledReference('torque');
  const session = createMujocoModelSession(mujoco, model, binding);
  const restAngles = model.manifest.joints.map(j => j.restAngleRad);

  try {
    const revocable = new MujocoBoundedExecutor(session, { policyDecimation: 10, totalSubsteps: 20, attempt });
    revocable.submitControlProposal(
      buildDeterministicRehearsalProposal(attempt, session.actuatorCtrlRanges, restAngles, 'torque', 0, 1002, 200),
    );
    revocable.stepSubstep(1002);
    revocable.stepSubstep(1004);
    assert.equal(revocable.getSummary().executedSubsteps, 2);
    revocable.revoke('Operator emergency stop at substep 2');
    assert.throws(
      () => revocable.stepSubstep(1006),
      (err: unknown) => err instanceof CwS02Error && err.vetoReason === 'REVOKED',
    );
    assert.equal(revocable.getSummary().executedSubsteps, 2);

    const expiredAttempt = new MujocoBoundedExecutor(session, { policyDecimation: 10, totalSubsteps: 20, attempt });
    assert.throws(
      () =>
        expiredAttempt.stepSubstep(attempt.deadlineMonotonicMs + 1, policyStep =>
          buildDeterministicRehearsalProposal(
            attempt,
            session.actuatorCtrlRanges,
            restAngles,
            'torque',
            policyStep,
            attempt.deadlineMonotonicMs + 1,
          ),
        ),
      (err: unknown) => err instanceof CwS02Error && err.vetoReason === 'ATTEMPT_DEADLINE_EXPIRED',
    );

    const switchExec = new MujocoBoundedExecutor(session, { policyDecimation: 10, totalSubsteps: 20, attempt });
    assert.throws(
      () => switchExec.assertAttemptMatch({ ...attempt, authorityEpoch: attempt.authorityEpoch + 1 }),
      (err: unknown) => err instanceof CwS02Error && err.code === 'AUTHORITY_FENCED',
    );
  } finally {
    session.dispose();
  }
});

test('CW-S02 requires immutable engine pins and explicit qualified dynamics settings', async () => {
  await assert.rejects(() => verifyPinnedMujocoWasmBytes(wasmBytes, wasmBytes.length, '0'.repeat(64)), /WASM_PIN_MISMATCH/);
  const mj = await loadVerifiedMujocoModule(wasmBytes);
  const source = studioReferenceInput(); // CW-S01 defaults remain kp=10.
  const model = compileAssemblyToMjcf(source);
  const binding = {modelDigest:model.modelDigest, assemblyDigest:model.manifest.assemblyDigest, catalogDigest:model.manifest.catalogDigest, drcDigest:model.manifest.drcDigest};
  const s = createMujocoModelSession(mj, model, binding);
  try {
    assert.throws(() => new MujocoBoundedExecutor(s, {policyDecimation:10,totalSubsteps:60,attempt:{...binding,revisionDigest:binding.assemblyDigest,generation:1,authorityEpoch:1,startedMonotonicMs:1000,deadlineMonotonicMs:4000}}), /RUNTIME_PROFILE_UNQUALIFIED/);
    model.manifest.options.positionGain = 1;
    assert.equal(s.artifact.manifest.options.positionGain, 10); // caller cannot alter retained model metadata
    const lower = s.actuatorCtrlRanges[0][0];
    try { (s.actuatorCtrlRanges[0] as [number,number])[0] = -99; } catch {}
    assert.equal(s.actuatorCtrlRanges[0][0], lower);
    assert.equal(Object.isFrozen(s.actuatorCtrlRanges[0]), true);
  } finally {s.dispose();}
});

test('CW-S02 XML grammar rejects resource allocation, replication and unsupported state before native compilation', async () => {
  const mj = await loadVerifiedMujocoModule(wasmBytes), {model,binding} = makeCompiledReference();
  for (const xml of [model.xml.replace('<worldbody>','<size memory="2G"/><worldbody>'), model.xml.replace('<worldbody>','<worldbody><replicate count="999999"/>'), model.xml.replace('gravity="0 0 -9.81"','gravity="0 0 -9.81" iterations="10000000"'), model.xml + ' '.repeat(131072)]) {
    const {modelDigest:_digest,...payload} = {...model,xml};
    const forged = {...payload,modelDigest:sha256Hex(canonicalAssemblyString(payload))};
    assert.throws(() => createMujocoModelSession(mj, forged, {...binding,modelDigest:forged.modelDigest}), /UNSUPPORTED_SUBSET/);
  }
});

test('CW-SIM-04 rechecks callback mutation, stop, revocation and failures at the mj_step boundary', async () => {
  const mj = await loadVerifiedMujocoModule(wasmBytes), {model,binding,attempt} = makeCompiledReference('torque');
  const session = createMujocoModelSession(mj,model,binding);
  try {
    for (const [mutate,code] of [
      [() => {session.data.qpos[0] += 0.1;},'EXTERNAL_STATE_TAMPERED'],
      [() => {session.data.qvel[0] += 0.1;},'EXTERNAL_STATE_TAMPERED'],
      [() => {session.data.time = 1;},'EXTERNAL_STATE_TAMPERED'],
      [() => {session.data.qacc_warmstart[0] = 1;},'EXTERNAL_STATE_TAMPERED'],
      [() => {session.model.opt.timestep = Number.NaN;},'TIMESTEP_ALTERED'],
      [(e: MujocoBoundedExecutor) => e.revoke(),'REVOKED'],
      [(e: MujocoBoundedExecutor) => e.notifyVisibilityHidden(),'TAB_HIDDEN_FENCED'],
      [(e: MujocoBoundedExecutor) => e.stop(),'AUTHORITY_FENCED'],
      [() => {throw new Error('provider failed');},'CONTROL_PROVIDER_FAILED'],
    ] as const) {
      session.model.opt.timestep=0.002;
      const exec = new MujocoBoundedExecutor(session,{policyDecimation:10,totalSubsteps:10,attempt});
      assert.throws(() => exec.stepSubstep(1002, () => {
        mutate(exec);
        return buildDeterministicRehearsalProposal(attempt,session.actuatorCtrlRanges,[], 'torque',0,1002);
      }), (error: unknown) => error instanceof CwS02Error && (error.code === code || error.vetoReason === code));
      assert.equal(exec.getSummary().executedSubsteps,0);
      assert.notEqual(exec.getSummary().status,'running');
    }
    session.model.opt.timestep=0.002;
    const exec = new MujocoBoundedExecutor(session,{policyDecimation:10,totalSubsteps:1,attempt});
    exec.stepSubstep(1002, () => {
      session.data.qfrc_applied[0]=100;session.data.xfrc_applied[6]=200;
      return buildDeterministicRehearsalProposal(attempt,session.actuatorCtrlRanges,[], 'torque',0,1002);
    });
    assert.equal(exec.getSummary().clearedExternalMutations,2);
    assert.equal(session.data.qfrc_applied[0],0);assert.equal(session.data.xfrc_applied[6],0);
  } finally {session.dispose();}
});

test('CW-SIM-04 refreshes callback time and treats deadlines and control ranges as strict bounds', async () => {
  const mj = await loadVerifiedMujocoModule(wasmBytes), {model,binding,attempt} = makeCompiledReference('torque');
  const s=createMujocoModelSession(mj,model,binding);
  try {
    for (const [clock,expiry,ctrl,reason] of [
      [() => 4000,4100,0,'ATTEMPT_DEADLINE_EXPIRED'],
      [() => 1002,1002,0,'CONTROL_EXPIRED'],
      [() => 1002,2000,s.actuatorCtrlRanges[0][1]+1e-13,'CONTROL_OUT_OF_RANGE'],
    ] as const) {
      const e=new MujocoBoundedExecutor(s,{policyDecimation:10,totalSubsteps:10,attempt,readMonotonicMs:clock});
      assert.throws(()=>e.stepSubstep(1002,()=>({...buildDeterministicRehearsalProposal(attempt,s.actuatorCtrlRanges,[],'torque',0,1002),expiresAtMonotonicMs:expiry,targetCtrl:[ctrl,0]})),(error: unknown) => error instanceof CwS02Error && (error.code === reason || error.vetoReason === reason));
      assert.equal(e.getSummary().executedSubsteps,0);
    }
    let wall=1002;
    const callbackDeadline=new MujocoBoundedExecutor(s,{policyDecimation:10,totalSubsteps:10,attempt,readMonotonicMs:()=>wall});
    assert.throws(()=>callbackDeadline.stepSubstep(wall,()=>{
      wall=attempt.deadlineMonotonicMs;
      return buildDeterministicRehearsalProposal(attempt,s.actuatorCtrlRanges,[],'torque',0,1002);
    }), (error: unknown)=>error instanceof CwS02Error && error.vetoReason==='ATTEMPT_DEADLINE_EXPIRED');
    wall=1004;
    const liveBatch=new MujocoBoundedExecutor(s,{policyDecimation:10,totalSubsteps:2,attempt,readMonotonicMs:()=>{wall+=0.01;return wall;}});
    liveBatch.stepBatch(1004,2,()=>buildDeterministicRehearsalProposal(attempt,s.actuatorCtrlRanges,[],'torque',0,1004));
    assert.equal(liveBatch.getSummary().executedSubsteps,2);
    const stalled=new MujocoBoundedExecutor(s,{policyDecimation:10,totalSubsteps:10,attempt});
    assert.throws(()=>stalled.stepSubstep(1300),/CLOCK_STALL_FENCED/);
    const invalid=new MujocoBoundedExecutor(s,{policyDecimation:10,totalSubsteps:10,attempt});
    s.data.qpos[0]=NaN;
    assert.throws(()=>invalid.stepSubstep(1002),/EXTERNAL_STATE_TAMPERED/);
    assert.equal(invalid.getSummary().finalStateValid,false);
    assert.match(invalid.getSummary().traceDigest,/^[a-f0-9]{64}$/);
  } finally {s.dispose();}
});

test('CW-SIM-03 owns immutable capture and hashes deterministic physics independently of wall-clock scheduling', async () => {
  const mj = await loadVerifiedMujocoModule(wasmBytes), {model,binding,attempt} = makeCompiledReference('torque');
  const s=createMujocoModelSession(mj,model,binding);
  try {
    const run=(shift:number)=>{
      const e=new MujocoBoundedExecutor(s,{policyDecimation:10,totalSubsteps:10,attempt});
      for(let k=1;k<=10;k++) {
        const sample=e.stepSubstep(1000+k*2+shift,p=>buildDeterministicRehearsalProposal(attempt,s.actuatorCtrlRanges,[],'torque',p,1000+k*2+shift));
        sample.qpos[0]=99;sample.tick=999;
      }
      const digest=e.getSummary().traceDigest;
      (e.getSamples() as any[]).splice(0,10);
      assert.equal(e.getSamples().length,10);assert.equal(e.getSummary().traceDigest,digest);
      return digest;
    };
    assert.equal(run(0),run(1));
  }finally{s.dispose();}
});
