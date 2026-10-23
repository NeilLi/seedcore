import { type CurrentModelBinding, type CompiledMjcf } from './compiler.js';

export const MUJOCO_WASM_PROFILE = 'seedcore.cw-s02.mujoco-wasm-st.v1' as const;
export const MUJOCO_WASM_ENGINE = '@mujoco/mujoco' as const;
export const MUJOCO_WASM_VERSION = '3.15.0' as const;
export const MUJOCO_WASM_BYTES = 10370402 as const;
export const MUJOCO_WASM_SHA256 = 'd59c489dd521c80af6965756c5b90daff549fa281566544e4540c170d937633d' as const;
export const MUJOCO_JS_BYTES = 293619 as const;
export const MUJOCO_JS_SHA256 = 'a5d5f00c4c16d327cf8275f88ddd47c857a5e9baec8ca4174d676fe299267a0c' as const;
export const CW_S02_WORKER_PROTOCOL = 'seedcore.cw-s02.worker.v1' as const;
export const PLANAR_SIM3_WASM_BYTES = 13242 as const;
export const CW_S02_TIMESTEP_SECONDS = 0.002 as const;
export const CW_S02_POSITION_GAIN = 1 as const;

/** Dynamics qualification is for these explicit settings, not every compiler option. */
export function assertQualifiedMujocoSettings(artifact: CompiledMjcf): void {
  const o = artifact.manifest.options;
  if (o.timestepSeconds !== CW_S02_TIMESTEP_SECONDS ||
      (o.actuatorMode === 'position' && o.positionGain !== CW_S02_POSITION_GAIN)) {
    throw new CwS02Error('RUNTIME_PROFILE_UNQUALIFIED', 'CW-S02 rehearsal requires dt=0.002 and position kp=1 (torque gain is not applicable). Recompile with the explicit rehearsal preset.');
  }
}

export const CW_S02_MUTATION_PATHS = [
  'ctrl',
  'qfrc_applied',
  'xfrc_applied',
  'qpos_qvel_act_state',
  'opt_timestep',
  'policy_model_switch',
] as const;
export type CwS02MutationPath = (typeof CW_S02_MUTATION_PATHS)[number];

export type CwS02ErrorCode =
  | 'WASM_PIN_MISMATCH'
  | 'WASM_FETCH_FAILED'
  | 'PLANAR_FALLBACK_FORBIDDEN'
  | 'MODEL_BINDING_MISMATCH'
  | 'MODEL_TOPOLOGY_MISMATCH'
  | 'UNSUPPORTED_SUBSET'
  | 'ENGINE_COMPILE_FAILED'
  | 'CLOCK_CONFIG_INVALID'
  | 'CLOCK_ROLLBACK_FENCED'
  | 'CLOCK_STALL_FENCED'
  | 'CAPTURE_OVERFLOW'
  | 'CONTROL_VETOED'
  | 'AUTHORITY_FENCED'
  | 'EXTERNAL_STATE_TAMPERED'
  | 'TIMESTEP_ALTERED'
  | 'TAB_HIDDEN_FENCED'
  | 'SESSION_DISPOSED'
  | 'RUNTIME_PROFILE_UNQUALIFIED'
  | 'CONTROL_PROVIDER_FAILED'
  | 'ENGINE_STEP_FAILED';

export type CwS02VetoReason =
  | 'STALE_GENERATION'
  | 'AUTHORITY_EPOCH_MISMATCH'
  | 'MODEL_DIGEST_MISMATCH'
  | 'CONTROL_MISSING'
  | 'CONTROL_EXPIRED'
  | 'CONTROL_DIMENSION_MISMATCH'
  | 'CONTROL_NONFINITE'
  | 'CONTROL_OUT_OF_RANGE'
  | 'ATTEMPT_DEADLINE_EXPIRED'
  | 'REVOKED'
  | 'TAB_HIDDEN_FENCED'
  | 'EXTERNAL_STATE_TAMPERED'
  | 'TIMESTEP_ALTERED'
  | 'CAPTURE_OVERFLOW';

export class CwS02Error extends Error {
  constructor(
    readonly code: CwS02ErrorCode,
    message: string,
    readonly vetoReason?: CwS02VetoReason,
  ) {
    super(`${code}: ${message}`);
    this.name = 'CwS02Error';
  }
}

export interface CwS02BodyFrameSnapshot {
  nodeId: string;
  bodyName: string;
  bodyId: number;
  xpos: [number, number, number];
  xquat: [number, number, number, number];
  xmat: number[];
  xipos: [number, number, number];
  ximat: number[];
  bodyMass: number;
  bodySubtreeMass: number;
  bodyInertia: [number, number, number];
}

export interface CwS02ForwardSnapshot {
  qpos: number[];
  rootSubtreeCom: [number, number, number];
  bodies: CwS02BodyFrameSnapshot[];
}

export interface CwS02ModelInspection {
  profile: typeof MUJOCO_WASM_PROFILE;
  engine: typeof MUJOCO_WASM_ENGINE;
  engineVersion: typeof MUJOCO_WASM_VERSION;
  wasmBytes: number;
  wasmSha256: string;
  scope: 'offline_simulation_only';
  physicalAcceptance: false;
  executionAuthority: 'none';
  planarFallbackUsed: false;
  modelDigest: string;
  nq: number;
  nv: number;
  nu: number;
  nbody: number;
  njnt: number;
  timestepSeconds: number;
  bodyIds: Record<string, number>;
  jointIds: Record<string, number>;
  actuatorIds: Record<string, number>;
  bodyMass: number[];
  bodySubtreeMass: number[];
  bodyInertia: [number, number, number][];
  qpos0: number[];
  jointRanges: [number, number][];
  actuatorCtrlRanges: [number, number][];
  actuatorForceRanges: [number, number][];
  jointActuatorForceRanges: [number, number][];
  actuatorGain0: number[];
}

export interface CwS02AttemptBinding extends CurrentModelBinding {
  revisionDigest: string;
  authorityEpoch: number;
  generation: number;
  startedMonotonicMs: number;
  deadlineMonotonicMs: number;
}

export interface CwS02ControlProposal {
  generation: number;
  authorityEpoch: number;
  modelDigest: string;
  proposedAtMonotonicMs: number;
  expiresAtMonotonicMs: number;
  targetCtrl: readonly number[];
}

export interface CwS02SubstepSample {
  tick: number;
  policyStep: number;
  simTimeSeconds: number;
  monotonicMs: number;
  qpos: number[];
  qvel: number[];
  ctrl: number[];
  qfrcActuator: number[];
  xpos: number[];
  clearedExternalMutations: number;
  stepExecuted: boolean;
  vetoReason: CwS02VetoReason | null;
}

export interface CwS02ExecutorConfig {
  /** Worker-owned monotonic clock, refreshed after control callbacks. */
  readMonotonicMs?: () => number;
  policyDecimation: number;
  totalSubsteps: number;
  maxSubstepsPerBatch?: number;
  maxStallMs?: number;
  maxCaptureSamples?: number;
  attempt: CwS02AttemptBinding;
}

export interface CwS02ExecutionSummary {
  profile: typeof MUJOCO_WASM_PROFILE;
  engineVersion: typeof MUJOCO_WASM_VERSION;
  wasmSha256: string;
  scope: 'offline_simulation_only';
  physicalAcceptance: false;
  executionAuthority: 'none';
  planarFallbackUsed: false;
  status: 'idle' | 'running' | 'completed' | 'vetoed' | 'fenced' | 'stopped';
  vetoReason: CwS02VetoReason | null;
  fenceCode: CwS02ErrorCode | null;
  errorMessage: string | null;
  attempt: CwS02AttemptBinding;
  timestepSeconds: number;
  policyDecimation: number;
  totalSubsteps: number;
  executedSubsteps: number;
  policyUpdates: number;
  batchesExecuted: number;
  maxSubstepsPerBatch: number;
  maxCaptureSamples: number;
  capturedSamples: number;
  clearedExternalMutations: number;
  mutationPathsGuarded: readonly CwS02MutationPath[];
  finalSimTimeSeconds: number | null;
  finalStateValid: boolean;
  finalQpos: number[];
  finalQvel: number[];
  finalCtrl: number[];
  traceDigest: string;
}

const WASM_MAGIC = [0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00] as const;

export async function sha256BytesHex(bytes: BufferSource): Promise<string> {
  const view =
    bytes instanceof ArrayBuffer
      ? new Uint8Array(bytes)
      : new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const copy = new Uint8Array(view.byteLength);
  copy.set(view);
  const digest = await crypto.subtle.digest('SHA-256', copy.buffer);
  return Array.from(new Uint8Array(digest), v => v.toString(16).padStart(2, '0')).join('');
}

/** Verify exact pinned @mujoco/mujoco@3.15.0 Wasm bytes; never fall back to the planar SIM-3 engine. */
export async function verifyPinnedMujocoWasmBytes(
  bytes: BufferSource,
  expectedBytes: number = MUJOCO_WASM_BYTES,
  expectedSha256: string = MUJOCO_WASM_SHA256,
): Promise<Uint8Array<ArrayBuffer>> {
  if (
    expectedBytes !== MUJOCO_WASM_BYTES || expectedSha256 !== MUJOCO_WASM_SHA256
  ) {
    throw new CwS02Error('WASM_PIN_MISMATCH', 'Invalid MuJoCo Wasm build pin configuration');
  }
  const view =
    bytes instanceof ArrayBuffer
      ? new Uint8Array(bytes)
      : new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (view.byteLength === PLANAR_SIM3_WASM_BYTES) {
    throw new CwS02Error(
      'PLANAR_FALLBACK_FORBIDDEN',
      'Refusing 13,242-byte planar SIM-3 Wasm binary; CW-S02 requires pinned MuJoCo 3.15.0 Wasm',
    );
  }
  if (view.byteLength !== expectedBytes) {
    throw new CwS02Error(
      'WASM_PIN_MISMATCH',
      `MuJoCo Wasm byte count mismatch: expected ${expectedBytes}, received ${view.byteLength}`,
    );
  }
  for (let i = 0; i < WASM_MAGIC.length; i++) {
    if (view[i] !== WASM_MAGIC[i]) {
      throw new CwS02Error('WASM_PIN_MISMATCH', 'Invalid WebAssembly binary magic/version header');
    }
  }
  const out = new Uint8Array(expectedBytes);
  out.set(view);
  const actualSha256 = await sha256BytesHex(out);
  if (actualSha256 !== expectedSha256) {
    throw new CwS02Error(
      'WASM_PIN_MISMATCH',
      `MuJoCo Wasm SHA-256 mismatch: expected ${expectedSha256}, received ${actualSha256}`,
    );
  }
  return out;
}

/** Streaming-bounded fetch reader for pinned @mujoco/mujoco@3.15.0 Wasm before compilation. */
export async function readPinnedMujocoWasm(
  response: Response,
  expectedBytes: number = MUJOCO_WASM_BYTES,
  expectedSha256: string = MUJOCO_WASM_SHA256,
): Promise<Uint8Array<ArrayBuffer>> {
  if (
    expectedBytes !== MUJOCO_WASM_BYTES || expectedSha256 !== MUJOCO_WASM_SHA256
  ) {
    throw new CwS02Error('WASM_PIN_MISMATCH', 'Invalid MuJoCo Wasm build pin configuration');
  }
  if (!response.ok || !response.body) {
    throw new CwS02Error('WASM_FETCH_FAILED', `Pinned MuJoCo Wasm fetch failed (${response.status})`);
  }
  const out = new Uint8Array(expectedBytes);
  const reader = response.body.getReader();
  let offset = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (offset + value.byteLength > expectedBytes) {
        if (offset + value.byteLength === PLANAR_SIM3_WASM_BYTES) {
          throw new CwS02Error('PLANAR_FALLBACK_FORBIDDEN', 'Planar SIM-3 Wasm fallback is forbidden');
        }
        throw new CwS02Error('WASM_PIN_MISMATCH', 'MuJoCo Wasm stream exceeds pinned byte count');
      }
      out.set(value, offset);
      offset += value.byteLength;
    }
  } catch (error) {
    try {
      await reader.cancel();
    } catch {}
    if (error instanceof CwS02Error) throw error;
    throw new CwS02Error('WASM_FETCH_FAILED', String(error));
  } finally {
    reader.releaseLock();
  }
  if (offset === PLANAR_SIM3_WASM_BYTES) {
    throw new CwS02Error(
      'PLANAR_FALLBACK_FORBIDDEN',
      'Refusing 13,242-byte planar SIM-3 Wasm binary; CW-S02 requires pinned MuJoCo 3.15.0 Wasm',
    );
  }
  if (offset !== expectedBytes) {
    throw new CwS02Error(
      'WASM_PIN_MISMATCH',
      `MuJoCo Wasm byte count mismatch: expected ${expectedBytes}, received ${offset}`,
    );
  }
  return verifyPinnedMujocoWasmBytes(out, expectedBytes, expectedSha256);
}
