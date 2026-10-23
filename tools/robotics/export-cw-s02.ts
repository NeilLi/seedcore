/** Export CW-S02 Wasm model inspections, FK snapshots, and bounded rollouts for native parity verification. */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  MUJOCO_WASM_BYTES,
  MUJOCO_WASM_PROFILE,
  MUJOCO_WASM_SHA256,
  MUJOCO_WASM_VERSION,
  MujocoBoundedExecutor,
  assessSimulationReadiness,
  buildDeterministicRehearsalProposal,
  compileAssemblyToMjcf,
  createMujocoModelSession,
  loadVerifiedMujocoModule,
  type CompilerInput,
} from '../../ts/packages/wasm-sim-bridge/src/index.js';
import { makeSyntheticSimulationInput, realStarterInput, studioReferenceInput } from '../../ts/tests/fixtures/cw-s01.js';

async function main() {
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
  const out = resolve(process.argv[2] ?? resolve(root, 'artifacts/robotics/cw-s02/models'));
  mkdirSync(out, { recursive: true });

  const wasmPath = resolve(root, 'ts/node_modules/@mujoco/mujoco/mujoco.wasm');
  const wasmBytes = readFileSync(wasmPath);
  const mujoco = await loadVerifiedMujocoModule(wasmBytes);

  const cases: { name: string; input: CompilerInput }[] = [];
  for (const joints of [1, 2, 3] as const) {
    for (const rotated of [false, true]) {
      for (const mode of ['position', 'torque'] as const) {
        const input = makeSyntheticSimulationInput(joints, rotated);
        input.options.actuatorMode = mode;
        cases.push({ name: `serial-${joints}-${rotated ? 'rotated' : 'aligned'}-${mode}`, input });
      }
    }
  }
  for (const mode of ['position', 'torque'] as const) {
    const input = studioReferenceInput();
    input.options.actuatorMode = mode;
    cases.push({ name: `studio-reference-${mode}`, input });
  }

  const exportedModels = [];
  for (const { name, input } of cases) {
    if (input.options.actuatorMode === "position") input.options.positionGain = 1;
    const model = compileAssemblyToMjcf(input);
    const binding = {
      assemblyDigest: model.manifest.assemblyDigest,
      catalogDigest: model.manifest.catalogDigest,
      drcDigest: model.manifest.drcDigest,
      modelDigest: model.modelDigest,
    };
    const session = createMujocoModelSession(mujoco, model, binding);
    try {
      const inspection = session.inspectModel();
      const nJoints = model.manifest.joints.length;
      const restAngles = model.manifest.joints.map(j => j.restAngleRad);
      const fkStates = [
        restAngles,
        new Array(nJoints).fill(0),
        new Array(nJoints).fill(-0.5),
        new Array(nJoints).fill(0.5),
        Array.from({ length: nJoints }, (_, i) => 0.15 - i * 0.1),
      ];
      const fkSnapshots = fkStates.map(qpos => session.evaluateForwardKinematics(qpos));

      const totalSubsteps = 120;
      const policyDecimation = 10;
      const dtMs = model.manifest.options.timestepSeconds * 1000;
      const attempt = {
        ...binding,
        revisionDigest: model.manifest.assemblyDigest,
        authorityEpoch: 1,
        generation: 1,
        startedMonotonicMs: 1000,
        deadlineMonotonicMs: 5000,
      };
      const executor = new MujocoBoundedExecutor(session, {
        policyDecimation,
        totalSubsteps,
        maxSubstepsPerBatch: 8,
        maxStallMs: 250,
        maxCaptureSamples: totalSubsteps,
        attempt,
      });
      let nowMs = attempt.startedMonotonicMs;
      while (executor.getSummary().status === 'running') {
        nowMs += 4 * dtMs;
        const due = executor.dueSubsteps(nowMs);
        if (due > 0) {
          executor.stepBatch(nowMs, due, policyStep =>
            buildDeterministicRehearsalProposal(
              attempt,
              session.actuatorCtrlRanges,
              restAngles,
              model.manifest.options.actuatorMode,
              policyStep,
              nowMs,
              100,
            ),
          );
        }
      }
      const rolloutSummary = executor.getSummary();
      const rolloutSamples = executor.getSamples();

      exportedModels.push({
        name,
        model,
        inspection,
        fkStates,
        fkSnapshots,
        rollout: {
          summary: rolloutSummary,
          samples: rolloutSamples,
        },
      });
    } finally {
      session.dispose();
    }
  }

  const starter = realStarterInput();
  writeFileSync(
    resolve(out, 'cases.json'),
    JSON.stringify(
      {
        scope: 'offline_simulation_only',
        physicalAcceptance: false,
        executionAuthority: 'none',
        profile: MUJOCO_WASM_PROFILE,
        engineVersion: MUJOCO_WASM_VERSION,
        wasmBytes: MUJOCO_WASM_BYTES,
        wasmSha256: MUJOCO_WASM_SHA256,
        planarFallbackUsed: false,
        models: exportedModels,
        starter: {
          drc: starter.drcReport,
          readiness: assessSimulationReadiness(starter),
        },
      },
      null,
      2,
    ) + '\n',
  );
  console.log(`CW-S02 exported ${exportedModels.length} Wasm-evaluated models; actual starter stays blocked.`);
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
