/** Read-only integrity/coverage projection. Hashes are not signer authentication or physical proof. */
import { canonicalAssemblyString, parseStrictJson } from '@seedcore/contracts';
import type { CompiledMjcf } from './compiler.js';
import { CW_S02_MUTATION_PATHS, MUJOCO_WASM_PROFILE, MUJOCO_WASM_VERSION, MUJOCO_WASM_SHA256, type CwS02ExecutionSummary, type CwS02SubstepSample } from './mujocoAsset.js';
import { CW_S04_DT, GestureError, assertCompiledGestureCurrent, assertGestureBinding, freezeGestureValue, gestureFrameAtTick, gestureHash, type CompiledGesture, type GestureBinding } from './gesture.js';

export const CW_S04_REPLAY = 'seedcore.cw-s04.replay.v1' as const;
export interface GestureReplay {
  schemaVersion: typeof CW_S04_REPLAY;
  scope: 'offline_simulation_only'; physicalAcceptance: false; executionAuthority: 'none';
  gesture: CompiledGesture;
  summary: CwS02ExecutionSummary;
  samples: CwS02SubstepSample[];
  replayDigest: string;
}
export interface GestureReplayExpected {
  binding: GestureBinding; gestureDigest: string; generation: number;
  /** Retain from the original executor/worker terminal message, never from imported JSON. */
  captureDigest: string;
}
export interface GestureReplayProjection {
  disposition: 'completed_simulation_capture' | 'interrupted_simulation_capture';
  executionStatus: CwS02ExecutionSummary['status'];
  capturedTicks: number;
  plannedTicks: number;
  frames: {tick: number; simTimeSeconds: number; targetRad: number[]; observedRad: number[]; observedVelocityRadS: number[]; virtualLed: string}[];
}
const reject = (message: string): never => { throw new GestureError('REPLAY_INVALID', message); };
function finite(value: unknown): value is number { return typeof value === 'number' && Number.isFinite(value); }
function vector(value: unknown, length: number): value is number[] {
  return Array.isArray(value) && value.length === length && value.every(finite);
}
const same = (a: unknown, b: unknown) => canonicalAssemblyString(a) === canonicalAssemblyString(b);
const shape = (value: unknown, keys: readonly string[]) => Boolean(value && typeof value === 'object' && !Array.isArray(value) &&
  Object.keys(value).length === keys.length && keys.every(k => Object.hasOwn(value,k)));
const hex = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const counter = (value: unknown, max: number): value is number => Number.isSafeInteger(value) && (value as number) >= 0 && (value as number) <= max;
const vetoCodes: Record<string, readonly string[]> = {
  STALE_GENERATION:['CONTROL_VETOED','AUTHORITY_FENCED'], AUTHORITY_EPOCH_MISMATCH:['CONTROL_VETOED','AUTHORITY_FENCED'],
  MODEL_DIGEST_MISMATCH:['CONTROL_VETOED','AUTHORITY_FENCED'], CONTROL_MISSING:['CONTROL_VETOED'], CONTROL_EXPIRED:['CONTROL_VETOED'],
  CONTROL_DIMENSION_MISMATCH:['CONTROL_VETOED'], CONTROL_NONFINITE:['CONTROL_VETOED'], CONTROL_OUT_OF_RANGE:['CONTROL_VETOED'],
  ATTEMPT_DEADLINE_EXPIRED:['CONTROL_VETOED'], REVOKED:['CONTROL_VETOED'], TAB_HIDDEN_FENCED:['TAB_HIDDEN_FENCED'],
  EXTERNAL_STATE_TAMPERED:['EXTERNAL_STATE_TAMPERED'], TIMESTEP_ALTERED:['TIMESTEP_ALTERED'], CAPTURE_OVERFLOW:['CAPTURE_OVERFLOW'],
};

/** Snapshot identity for local capture integrity, not a signature or physical attestation. */
export function gestureCaptureDigest(summary: CwS02ExecutionSummary, samples: readonly CwS02SubstepSample[]): string {
  if (!Array.isArray(samples) || samples.length > 120) reject('Capture exceeds the bounded sample budget');
  const text = canonicalAssemblyString({summary,samples});
  if (new TextEncoder().encode(text).length > 262144) reject('Capture exceeds 256 KiB');
  return gestureHash({summary,samples});
}

/** Bounded raw import; independent expected bindings are mandatory, never read from the bundle itself. */
function inspectReplay(raw: unknown, model: CompiledMjcf, expected: GestureReplayExpected): { replay: GestureReplay; projection: GestureReplayProjection } {
  let r: GestureReplay;
  try {
    const text = typeof raw === 'string' ? raw : canonicalAssemblyString(raw);
    r = parseStrictJson(text) as GestureReplay;
  } catch (e) { return reject(`Malformed/bounded replay JSON: ${String(e)}`); }
  if (!r || typeof r !== 'object' || Array.isArray(r) ||
      Object.keys(r).sort().join(',') !== ['schemaVersion','scope','physicalAcceptance','executionAuthority','gesture','summary','samples','replayDigest'].sort().join(',') ||
      r.schemaVersion !== CW_S04_REPLAY || r.scope !== 'offline_simulation_only' || r.physicalAcceptance !== false || r.executionAuthority !== 'none') reject('Replay scope/shape mismatch');
  const { replayDigest, ...payload } = r;
  if (!hex(replayDigest) || gestureHash(payload) !== replayDigest) reject('Replay digest mismatch');
  if (!shape(expected,['binding','gestureDigest','generation','captureDigest']) || !Number.isSafeInteger(expected.generation) || expected.generation < 1 ||
      !hex(expected.gestureDigest) || !hex(expected.captureDigest)) reject('Missing independent attempt/capture identity');
  if (gestureCaptureDigest(r.summary,r.samples) !== expected.captureDigest) reject('Capture differs from the independently retained original attempt');
  assertCompiledGestureCurrent(r.gesture, model, expected.binding, expected.gestureDigest);
  const s = r.summary;
  if (!shape(s,['profile','engineVersion','wasmSha256','scope','physicalAcceptance','executionAuthority','planarFallbackUsed','status','vetoReason','fenceCode','errorMessage',
      'attempt','timestepSeconds','policyDecimation','totalSubsteps','executedSubsteps','policyUpdates','batchesExecuted','maxSubstepsPerBatch','maxCaptureSamples',
      'capturedSamples','clearedExternalMutations','mutationPathsGuarded','finalSimTimeSeconds','finalStateValid','finalQpos','finalQvel','finalCtrl','traceDigest']) ||
      !s.attempt || s.scope !== 'offline_simulation_only' || s.physicalAcceptance !== false || s.executionAuthority !== 'none' ||
      s.profile !== MUJOCO_WASM_PROFILE || s.engineVersion !== MUJOCO_WASM_VERSION || s.wasmSha256 !== MUJOCO_WASM_SHA256 || s.planarFallbackUsed !== false ||
      s.timestepSeconds !== CW_S04_DT || s.policyDecimation !== 1 || s.totalSubsteps !== r.gesture.totalTicks ||
      !['completed','stopped','vetoed','fenced'].includes(s.status)) reject('Wrong runtime profile, duration, terminal state or scope');
  const a = s.attempt;
  if (!shape(a,['assemblyDigest','catalogDigest','drcDigest','modelDigest','revisionDigest','authorityEpoch','generation','startedMonotonicMs','deadlineMonotonicMs'])) reject('Unknown attempt fields');
  assertGestureBinding({assemblyDigest:a.assemblyDigest,catalogDigest:a.catalogDigest,drcDigest:a.drcDigest,modelDigest:a.modelDigest,
    revisionDigest:a.revisionDigest,authorityEpoch:a.authorityEpoch}, expected.binding);
  if (a.generation !== expected.generation || !finite(a.startedMonotonicMs) || a.startedMonotonicMs < 0 || !finite(a.deadlineMonotonicMs) || a.deadlineMonotonicMs <= a.startedMonotonicMs) reject('Attempt generation/deadline mismatch');
  if (!Number.isSafeInteger(s.executedSubsteps) || s.executedSubsteps < 0 || s.executedSubsteps > s.totalSubsteps ||
      !Array.isArray(r.samples) || r.samples.length > 120 || s.capturedSamples !== r.samples.length ||
      !Number.isSafeInteger(s.maxCaptureSamples) || s.maxCaptureSamples < r.samples.length || s.maxCaptureSamples > 4096 ||
      s.finalStateValid !== true) reject('Invalid/incomplete capture metadata or final state');
  if (!counter(s.policyUpdates,s.executedSubsteps+1) || s.policyUpdates < s.executedSubsteps ||
      !counter(s.batchesExecuted,s.executedSubsteps+1) || !counter(s.maxSubstepsPerBatch,32) || s.maxSubstepsPerBatch < 1 ||
      !counter(s.clearedExternalMutations,2*(model.manifest.joints.length+6*(model.manifest.bodies.length+1))*(s.executedSubsteps+1)) ||
      !same(s.mutationPathsGuarded,CW_S02_MUTATION_PATHS)) reject('Invalid clock/control/mutation counters or mutation guard inventory');
  if (s.status === 'completed' && (s.executedSubsteps !== s.totalSubsteps || s.fenceCode !== null || s.vetoReason !== null)) reject('Completed status lacks complete execution');
  if ((s.status === 'completed' && (s.errorMessage !== null || s.policyUpdates !== s.executedSubsteps)) ||
      (s.status !== 'completed' && (typeof s.errorMessage !== 'string' || !s.errorMessage || s.errorMessage.length > 1024 || s.executedSubsteps >= s.totalSubsteps)) ||
      (s.status === 'stopped' && (s.fenceCode !== null || s.vetoReason !== null || s.policyUpdates !== s.executedSubsteps)) ||
      (s.status === 'fenced' && (typeof s.fenceCode !== 'string' || !s.fenceCode || s.vetoReason !== null)) ||
      (s.status === 'vetoed' && (typeof s.fenceCode !== 'string' || !s.fenceCode || typeof s.vetoReason !== 'string' || !s.vetoReason))) reject('Conflicting terminal status/reason metadata');
  if ((s.status === 'fenced' && !['CLOCK_ROLLBACK_FENCED','CLOCK_STALL_FENCED','CONTROL_PROVIDER_FAILED','ENGINE_STEP_FAILED'].includes(s.fenceCode!)) ||
      (s.status === 'vetoed' && (!Object.hasOwn(vetoCodes,s.vetoReason!) || !vetoCodes[s.vetoReason!].includes(s.fenceCode!)))) reject('Unknown or conflicting fence/veto reason');
  const count = model.manifest.joints.length, frames: GestureReplayProjection['frames'] = [];
  let tick = 0, terminal = false, previousWall = a.startedMonotonicMs, cleared = 0;
  for (const sample of r.samples) {
    if (!shape(sample,['tick','policyStep','simTimeSeconds','monotonicMs','qpos','qvel','ctrl','qfrcActuator','xpos','clearedExternalMutations','stepExecuted','vetoReason']) ||
        !Number.isSafeInteger(sample.tick) || !Number.isSafeInteger(sample.policyStep) || !finite(sample.simTimeSeconds) ||
        !finite(sample.monotonicMs) || sample.monotonicMs < previousWall ||
        !vector(sample.qpos,count) || !vector(sample.qvel,count) || !vector(sample.ctrl,count) || !vector(sample.qfrcActuator,count) ||
        !vector(sample.xpos,(model.manifest.bodies.length+1)*3) || !Number.isSafeInteger(sample.clearedExternalMutations) || sample.clearedExternalMutations < 0) reject('Malformed/nonfinite capture sample');
    previousWall = sample.monotonicMs; cleared += sample.clearedExternalMutations;
    if (sample.stepExecuted === true) {
      tick++;
      if (terminal || sample.tick !== tick || sample.policyStep !== tick-1 || sample.vetoReason !== null ||
          sample.monotonicMs >= a.deadlineMonotonicMs || Math.abs(sample.simTimeSeconds-tick*CW_S04_DT) > 1e-12) reject('Missing, reordered, duplicated or overdue simulation tick');
      const frame = gestureFrameAtTick(r.gesture,tick);
      if (!sample.ctrl.every((v,i) => v === frame.targetRad[i])) reject('Captured controls differ from compiled gesture');
      frames.push({tick,simTimeSeconds:sample.simTimeSeconds,...frame,observedRad:[...sample.qpos],observedVelocityRadS:[...sample.qvel]});
    } else if (sample.stepExecuted === false) {
      if (terminal || sample.tick !== tick || sample.policyStep !== tick || sample.vetoReason !== s.vetoReason ||
          sample.vetoReason === null || s.status !== 'vetoed' || sample.ctrl.some(v => v !== 0) ||
          Math.abs(sample.simTimeSeconds-tick*CW_S04_DT) > 1e-12) reject('Invalid terminal veto event');
      terminal = true;
    } else reject('Unknown step/capture semantics');
  }
  if (tick !== s.executedSubsteps || !finite(s.finalSimTimeSeconds) || Math.abs(s.finalSimTimeSeconds-tick*CW_S04_DT) > 1e-12 ||
      !vector(s.finalQpos,count) || !vector(s.finalQvel,count) || !vector(s.finalCtrl,count)) reject('Summary and capture coverage disagree');
  if (cleared > s.clearedExternalMutations || (s.status === 'completed' && cleared !== s.clearedExternalMutations) ||
      (s.status !== 'completed' && s.finalCtrl.some(v => v !== 0))) reject('Conflicting cleared-force or terminal-control metadata');
  const last = r.samples.at(-1);
  if (last && (!same(last.qpos,s.finalQpos) || !same(last.qvel,s.finalQvel))) reject('Final state differs from retained capture');
  if (s.status === 'completed' && last && !same(last.ctrl,s.finalCtrl)) reject('Final control differs from retained capture');
  const traceDigest = gestureHash({modelDigest:a.modelDigest,timestepSeconds:s.timestepSeconds,policyDecimation:s.policyDecimation,
    samples:r.samples.map(({monotonicMs:_wall,...physics}) => physics)});
  if (traceDigest !== s.traceDigest) reject('Physics trace digest mismatch');
  return freezeGestureValue({replay:r,projection:{
    disposition:s.status === 'completed' ? 'completed_simulation_capture' : 'interrupted_simulation_capture',
    executionStatus:s.status,capturedTicks:tick,plannedTicks:s.totalSubsteps,frames,
  }});
}

export function inspectGestureReplay(raw: unknown, model: CompiledMjcf, expected: GestureReplayExpected): { replay: GestureReplay; projection: GestureReplayProjection } {
  try { return inspectReplay(raw,model,expected); }
  catch (error) {
    if (error instanceof GestureError) throw error;
    return reject(`Malformed replay: ${String(error instanceof Error ? error.message : error).slice(0,500)}`);
  }
}

export function createGestureReplay(gesture: CompiledGesture, summary: CwS02ExecutionSummary, samples: readonly CwS02SubstepSample[], model: CompiledMjcf, expected: GestureReplayExpected): GestureReplay {
  const payload = {schemaVersion:CW_S04_REPLAY,scope:'offline_simulation_only' as const,physicalAcceptance:false as const,executionAuthority:'none' as const,
    gesture,summary,samples:[...samples]};
  return inspectGestureReplay({...payload,replayDigest:gestureHash(payload)},model,expected).replay;
}
