/** CW-G01 candidate preparation only. A browser digest never grants execution authority. */
import { canonicalAssemblyString } from '@seedcore/contracts';
import type { CompiledMjcf } from './compiler.js';
import { MUJOCO_WASM_PROFILE, MUJOCO_WASM_VERSION, MUJOCO_WASM_SHA256 } from './mujocoAsset.js';
import { CW_S04_DT, assertCompiledGestureCurrent, freezeGestureValue, gestureHash, type CompiledGesture, type GestureBinding } from './gesture.js';

export const CW_G01_CANDIDATE = 'seedcore.cw-g01.candidate.v1' as const;
export interface CwBuildCandidate {
  schemaVersion: typeof CW_G01_CANDIDATE;
  scope: 'offline_simulation_only'; physicalAcceptance: false; executionAuthority: 'none';
  endpointId: string;
  binding: GestureBinding;
  runtime: {profile: typeof MUJOCO_WASM_PROFILE; engineVersion: typeof MUJOCO_WASM_VERSION; wasmSha256: typeof MUJOCO_WASM_SHA256;
    timestepSeconds: number; actuatorMode: 'position'; positionKp: 1};
  behavior: {compiler: CompiledGesture['compiler']; gestureDigest: string; totalTicks: number; durationSeconds: number;
    joints: {jointId: string; lowerRad: number; upperRad: number; maxVelocityRadS: number; maxAccelerationRadS2: number;
      requestedMaxVelocityRadS: number; requestedMaxAccelerationRadS2: number}[]};
  candidateDigest: string;
}

/** Freeze the current compiler outputs and requested endpoint; no registration/signing/PDP call. */
export function createCwBuildCandidate(model: CompiledMjcf, gesture: CompiledGesture, binding: GestureBinding, endpointId: string): CwBuildCandidate {
  if (typeof endpointId !== 'string' || !/^cw_sim:\/\/[a-zA-Z0-9][a-zA-Z0-9._/-]{0,127}$/.test(endpointId) ||
      endpointId.split('/').includes('..') || endpointId.split('/').includes('.')) throw new Error('A bounded cw_sim:// simulation endpoint is required');
  assertCompiledGestureCurrent(gesture,model,binding,gesture.gestureDigest);
  const payload = {
    schemaVersion:CW_G01_CANDIDATE,scope:'offline_simulation_only' as const,physicalAcceptance:false as const,executionAuthority:'none' as const,
    endpointId,binding:{...binding},
    runtime:{profile:MUJOCO_WASM_PROFILE,engineVersion:MUJOCO_WASM_VERSION,wasmSha256:MUJOCO_WASM_SHA256,
      timestepSeconds:CW_S04_DT,actuatorMode:'position' as const,positionKp:1 as const},
    behavior:{compiler:gesture.compiler,gestureDigest:gesture.gestureDigest,totalTicks:gesture.totalTicks,durationSeconds:gesture.totalTicks*CW_S04_DT,
      joints:gesture.tracks.map((track,i) => ({jointId:track.jointId,
        lowerRad:Math.min(...track.segments.map(s => s.minPositionRad)),upperRad:Math.max(...track.segments.map(s => s.maxPositionRad)),
        maxVelocityRadS:Math.max(...track.segments.map(s => s.maxVelocityRadS)),maxAccelerationRadS2:Math.max(...track.segments.map(s => s.maxAccelerationRadS2)),
        requestedMaxVelocityRadS:gesture.draft.tracks[i].maxVelocityRadS,requestedMaxAccelerationRadS2:gesture.draft.tracks[i].maxAccelerationRadS2}))},
  };
  return freezeGestureValue({...payload,candidateDigest:gestureHash(payload)});
}

export function assertCwBuildCandidateCurrent(candidate: CwBuildCandidate, model: CompiledMjcf, gesture: CompiledGesture, binding: GestureBinding, endpointId: string): void {
  if (canonicalAssemblyString(candidate) !== canonicalAssemblyString(createCwBuildCandidate(model,gesture,binding,endpointId))) {
    throw new Error('Review candidate changed; freeze the current build, gesture and endpoint again');
  }
}
