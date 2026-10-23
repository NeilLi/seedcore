import { canonicalAssemblyString } from '@seedcore/contracts';
import { sha256Hex } from '@seedcore/drc-solver';
import {
  CW_S02_MUTATION_PATHS,
  CwS02Error,
  assertQualifiedMujocoSettings,
  MUJOCO_WASM_PROFILE,
  MUJOCO_WASM_VERSION,
  type CwS02AttemptBinding,
  type CwS02ControlProposal,
  type CwS02ErrorCode,
  type CwS02ExecutionSummary,
  type CwS02ExecutorConfig,
  type CwS02SubstepSample,
  type CwS02VetoReason,
} from './mujocoAsset.js';
import { type MujocoModelSession } from './mujocoRuntime.js';

const HEX64 = /^[0-9a-f]{64}$/;
const finiteArray = (values: ArrayLike<number>): number[] => {
  const copy = Array.from(values); return copy.every(Number.isFinite) ? copy : [];
};

function isHex64(value: unknown): value is string {
  return typeof value === 'string' && HEX64.test(value);
}

/** Deterministic offline rehearsal control trajectory strictly inside actuator ctrlrange. */
export function buildDeterministicRehearsalProposal(
  attempt: CwS02AttemptBinding,
  ctrlRanges: readonly (readonly [number, number])[],
  restAngles: readonly number[],
  actuatorMode: 'position' | 'torque',
  policyStep: number,
  nowMonotonicMs: number,
  ttlMs: number = 100,
): CwS02ControlProposal {
  const targetCtrl = ctrlRanges.map(([min, max], index) => {
    const center = actuatorMode === 'position' ? Math.min(max, Math.max(min, restAngles[index] ?? 0)) : 0;
    const span = Math.min(max - center, center - min);
    const scale = actuatorMode === 'position' ? 0.002 : 0.05;
    const halfSpan = span * scale;
    const phase = 0.25 * policyStep + index * 0.7;
    const raw = center + halfSpan * Math.sin(phase);
    return Number(raw.toFixed(12));
  });
  return {
    generation: attempt.generation,
    authorityEpoch: attempt.authorityEpoch,
    modelDigest: attempt.modelDigest,
    proposedAtMonotonicMs: nowMonotonicMs,
    expiresAtMonotonicMs: nowMonotonicMs + ttlMs,
    targetCtrl,
  };
}

/**
 * State-owning MuJoCo Wasm executor (CW-SIM-03 & CW-SIM-04).
 * Enforces integer tick clocks, bounded catch-up, complete capture fencing,
 * external force/state clearing, and per-substep control veto before every mj_step.
 */
export class MujocoBoundedExecutor {
  readonly policyDecimation: number;
  readonly totalSubsteps: number;
  readonly maxSubstepsPerBatch: number;
  readonly maxStallMs: number;
  readonly maxCaptureSamples: number;
  readonly attempt: Readonly<CwS02AttemptBinding>;
  readonly frozenTimestepSeconds: number;

  private status: CwS02ExecutionSummary['status'] = 'idle';
  private vetoReason: CwS02VetoReason | null = null;
  private fenceCode: CwS02ErrorCode | null = null;
  private errorMessage: string | null = null;
  private executedSubsteps = 0;
  private policyUpdates = 0;
  private batchesExecuted = 0;
  private clearedExternalMutations = 0;
  private lastWallMs: number;
  private activeProposal: CwS02ControlProposal | null = null;
  private revoked = false;
  private tabHidden = false;
  private readonly samples: CwS02SubstepSample[] = [];
  private readonly shadowQpos: Float64Array;
  private readonly shadowQvel: Float64Array;
  private readonly shadowAct: Float64Array;
  private readonly shadowWarmstart: Float64Array;
  private shadowTime = 0;
  private readMonotonicMs?: () => number;

  constructor(
    readonly session: MujocoModelSession,
    config: CwS02ExecutorConfig,
  ) {
    session.assertOpen();
    assertQualifiedMujocoSettings(session.artifact);
    const {
      policyDecimation,
      totalSubsteps,
      maxSubstepsPerBatch = 8,
      maxStallMs = 250,
      maxCaptureSamples = totalSubsteps,
      attempt,
    } = config;

    if (
      !Number.isInteger(policyDecimation) ||
      policyDecimation < 1 ||
      policyDecimation > 50 ||
      !Number.isInteger(totalSubsteps) ||
      totalSubsteps < 1 ||
      totalSubsteps > 120 ||
      !Number.isInteger(maxSubstepsPerBatch) ||
      maxSubstepsPerBatch < 1 ||
      maxSubstepsPerBatch > 32 ||
      typeof maxStallMs !== 'number' ||
      !Number.isFinite(maxStallMs) ||
      maxStallMs < 10 ||
      maxStallMs > 500 ||
      !Number.isInteger(maxCaptureSamples) ||
      maxCaptureSamples < 1 ||
      maxCaptureSamples > 4096
    ) {
      throw new CwS02Error('CLOCK_CONFIG_INVALID', 'Invalid CW-S02 clock, decimation, batch ceiling or capture bound');
    }

    if (
      !attempt ||
      !Number.isSafeInteger(attempt.generation) ||
      attempt.generation < 1 ||
      !Number.isSafeInteger(attempt.authorityEpoch) ||
      attempt.authorityEpoch < 0 ||
      !isHex64(attempt.revisionDigest) ||
      !isHex64(attempt.assemblyDigest) ||
      !isHex64(attempt.catalogDigest) ||
      !isHex64(attempt.drcDigest) ||
      !isHex64(attempt.modelDigest) ||
      typeof attempt.startedMonotonicMs !== 'number' ||
      !Number.isFinite(attempt.startedMonotonicMs) ||
      typeof attempt.deadlineMonotonicMs !== 'number' ||
      !Number.isFinite(attempt.deadlineMonotonicMs) ||
      attempt.deadlineMonotonicMs <= attempt.startedMonotonicMs
    ) {
      throw new CwS02Error('AUTHORITY_FENCED', 'Invalid CW-S02 attempt binding or monotonic deadline');
    }

    if (
      attempt.modelDigest !== session.artifact.modelDigest ||
      attempt.assemblyDigest !== session.binding.assemblyDigest ||
      attempt.catalogDigest !== session.binding.catalogDigest ||
      attempt.drcDigest !== session.binding.drcDigest
    ) {
      throw new CwS02Error('MODEL_BINDING_MISMATCH', 'Attempt binding does not match loaded MuJoCo model session');
    }

    this.policyDecimation = policyDecimation;
    this.totalSubsteps = totalSubsteps;
    this.maxSubstepsPerBatch = maxSubstepsPerBatch;
    this.maxStallMs = maxStallMs;
    this.maxCaptureSamples = maxCaptureSamples;
    this.attempt = Object.freeze({ ...attempt });
    this.frozenTimestepSeconds = session.artifact.manifest.options.timestepSeconds;
    this.lastWallMs = attempt.startedMonotonicMs;
    this.readMonotonicMs = config.readMonotonicMs;

    session.resetToHome();
    this.shadowQpos = new Float64Array(session.data.qpos);
    this.shadowQvel = new Float64Array(session.data.qvel);
    this.shadowAct = new Float64Array(session.data.act);
    this.shadowWarmstart = new Float64Array(session.data.qacc_warmstart);
    this.status = 'running';
  }

  private fence(code: CwS02ErrorCode, message: string, vetoReason?: CwS02VetoReason): never {
    this.session.data.ctrl.fill(0);
    this.session.data.qfrc_applied.fill(0);
    this.session.data.xfrc_applied.fill(0);
    if (vetoReason) {
      this.status = 'vetoed';
      this.vetoReason = vetoReason;
      if (this.samples.length < this.maxCaptureSamples && this.hasFiniteState()) {
        this.samples.push({
          tick: this.executedSubsteps,
          policyStep: Math.floor(this.executedSubsteps / this.policyDecimation),
          simTimeSeconds: this.session.data.time,
          monotonicMs: this.lastWallMs,
          qpos: Array.from(this.session.data.qpos),
          qvel: Array.from(this.session.data.qvel),
          ctrl: Array.from(this.session.data.ctrl),
          qfrcActuator: Array.from(this.session.data.qfrc_actuator),
          xpos: Array.from(this.session.data.xpos),
          clearedExternalMutations: 0,
          stepExecuted: false,
          vetoReason,
        });
      }
    } else {
      this.status = 'fenced';
    }
    this.fenceCode = code;
    this.errorMessage = message;
    throw new CwS02Error(code, message, vetoReason);
  }

  private ensureRunning(): void {
    this.session.assertOpen();
    if (this.status !== 'running') {
      throw new CwS02Error(
        this.fenceCode ?? 'AUTHORITY_FENCED',
        this.errorMessage ?? `Executor is no longer running (status=${this.status})`,
        this.vetoReason ?? undefined,
      );
    }
  }

  private hasFiniteState(): boolean {
    return !this.session.isDisposed && Number.isFinite(this.session.data.time) &&
      [this.session.data.qpos, this.session.data.qvel, this.session.data.act,
        this.session.data.ctrl, this.session.data.qfrc_actuator, this.session.data.xpos].every(a => Array.from(a as Float64Array).every(Number.isFinite));
  }

  /** Fence immediately if the studio/model/policy binding changes during an attempt. */
  assertAttemptMatch(
    live: Pick<
      CwS02AttemptBinding,
      'generation' | 'authorityEpoch' | 'revisionDigest' | 'assemblyDigest' | 'catalogDigest' | 'drcDigest' | 'modelDigest'
    >,
  ): void {
    this.session.assertOpen();
    for (const key of [
      'generation',
      'authorityEpoch',
      'revisionDigest',
      'assemblyDigest',
      'catalogDigest',
      'drcDigest',
      'modelDigest',
    ] as const) {
      if (live[key] !== this.attempt[key]) {
        const veto: CwS02VetoReason =
          key === 'generation'
            ? 'STALE_GENERATION'
            : key === 'authorityEpoch'
              ? 'AUTHORITY_EPOCH_MISMATCH'
              : 'MODEL_DIGEST_MISMATCH';
        this.fence('AUTHORITY_FENCED', `Attempt binding changed on ${key}; fresh admission required`, veto);
      }
    }
  }

  submitControlProposal(proposal: CwS02ControlProposal): void {
    this.ensureRunning();
    if (!proposal || typeof proposal !== 'object') this.fence('CONTROL_VETOED', 'Malformed control proposal', 'CONTROL_MISSING');
    this.activeProposal = {
      ...proposal,
      targetCtrl: Array.isArray(proposal.targetCtrl) && proposal.targetCtrl.length === this.session.model.nu ? [...proposal.targetCtrl] : [],
    };
    this.policyUpdates++;
  }

  revoke(reason: string = 'Attempt revoked by operator or supervisor'): void {
    this.revoked = true;
    this.errorMessage = reason;
  }

  notifyVisibilityHidden(): void {
    this.tabHidden = true;
    this.errorMessage = 'Simulation attempt fenced because the page/tab became hidden';
  }

  stop(reason: string = 'Stopped by operator'): void {
    if (this.status === 'running') {
      this.status = 'stopped';
      this.errorMessage = reason;
      this.session.data.ctrl.fill(0);
      this.session.data.qfrc_applied.fill(0);
      this.session.data.xfrc_applied.fill(0);
    }
  }

  /** Compute due substeps under the bounded catch-up ceiling; stalls or rollbacks fence the attempt. */
  dueSubsteps(nowMonotonicMs: number): number {
    this.ensureRunning();
    if (
      typeof nowMonotonicMs !== 'number' ||
      !Number.isFinite(nowMonotonicMs) ||
      nowMonotonicMs < this.lastWallMs ||
      nowMonotonicMs < this.attempt.startedMonotonicMs
    ) {
      this.fence('CLOCK_ROLLBACK_FENCED', 'Monotonic clock rollback detected');
    }
    const deltaMs = nowMonotonicMs - this.lastWallMs;
    const simulatedMs = this.executedSubsteps * this.frozenTimestepSeconds * 1000;
    const lagMs = nowMonotonicMs - this.attempt.startedMonotonicMs - simulatedMs;
    if (deltaMs > this.maxStallMs || lagMs > this.maxStallMs) {
      this.fence(
        'CLOCK_STALL_FENCED',
        `Simulation pacing stalled (${Math.max(deltaMs, lagMs).toFixed(1)} ms > ${this.maxStallMs} ms); refusing to enlarge dt or drop capture`,
      );
    }
    this.lastWallMs = nowMonotonicMs;
    const targetTick = Math.min(
      this.totalSubsteps,
      Math.floor((nowMonotonicMs - this.attempt.startedMonotonicMs) / (this.frozenTimestepSeconds * 1000)),
    );
    return Math.min(this.maxSubstepsPerBatch, Math.max(0, targetTick - this.executedSubsteps));
  }

  private clearExternalForceArrays(): number {
    let cleared = 0;
    const qfrc = this.session.data.qfrc_applied;
    for (let i = 0; i < qfrc.length; i++) {
      if (qfrc[i] !== 0) {
        qfrc[i] = 0;
        cleared++;
      }
    }
    const xfrc = this.session.data.xfrc_applied;
    for (let i = 0; i < xfrc.length; i++) {
      if (xfrc[i] !== 0) {
        xfrc[i] = 0;
        cleared++;
      }
    }
    this.clearedExternalMutations += cleared;
    return cleared;
  }

  private verifyOwnedStateUnchanged(): void {
    if (this.session.data.time !== this.shadowTime ||
      Array.from(this.session.data.qacc_warmstart as Float64Array).some((v, i) => !Object.is(v, this.shadowWarmstart[i]))) {
      this.fence('EXTERNAL_STATE_TAMPERED', 'Unauthorized mutation of time or solver warmstart state', 'EXTERNAL_STATE_TAMPERED');
    }
    const { qpos, qvel, act } = this.session.data;
    for (let i = 0; i < this.shadowQpos.length; i++) {
      if (!Object.is(qpos[i], this.shadowQpos[i])) {
        this.fence('EXTERNAL_STATE_TAMPERED', `Unauthorized external mutation of qpos[${i}] between substeps`, 'EXTERNAL_STATE_TAMPERED');
      }
    }
    for (let i = 0; i < this.shadowQvel.length; i++) {
      if (!Object.is(qvel[i], this.shadowQvel[i])) {
        this.fence('EXTERNAL_STATE_TAMPERED', `Unauthorized external mutation of qvel[${i}] between substeps`, 'EXTERNAL_STATE_TAMPERED');
      }
    }
    for (let i = 0; i < this.shadowAct.length; i++) {
      if (!Object.is(act[i], this.shadowAct[i])) {
        this.fence('EXTERNAL_STATE_TAMPERED', `Unauthorized external mutation of act[${i}] between substeps`, 'EXTERNAL_STATE_TAMPERED');
      }
    }
  }

  /** Execute a single physics substep with mandatory pre-step control/state/clock/buffer gating. */
  stepSubstep(
    nowMonotonicMs: number,
    controlProvider?: (
      policyStep: number,
      tick: number,
      qpos: readonly number[],
      qvel: readonly number[],
    ) => CwS02ControlProposal,
  ): CwS02SubstepSample {
    this.ensureRunning();
    nowMonotonicMs = this.readMonotonicMs?.() ?? nowMonotonicMs;
    if (
      typeof nowMonotonicMs !== 'number' ||
      !Number.isFinite(nowMonotonicMs) ||
      nowMonotonicMs < this.lastWallMs ||
      nowMonotonicMs < this.attempt.startedMonotonicMs
    ) {
      this.fence('CLOCK_ROLLBACK_FENCED', 'Monotonic clock rollback detected before substep');
    }
    const deltaMs = nowMonotonicMs - this.lastWallMs;
    this.lastWallMs = nowMonotonicMs;
    if (this.tabHidden) {
      this.fence('TAB_HIDDEN_FENCED', 'Attempt fenced because page/tab became hidden', 'TAB_HIDDEN_FENCED');
    }
    if (this.revoked) {
      this.fence('CONTROL_VETOED', this.errorMessage ?? 'Attempt revoked before substep', 'REVOKED');
    }
    if (nowMonotonicMs >= this.attempt.deadlineMonotonicMs) {
      this.fence('CONTROL_VETOED', 'Attempt monotonic deadline expired before substep', 'ATTEMPT_DEADLINE_EXPIRED');
    }
    const lagMs = nowMonotonicMs - this.attempt.startedMonotonicMs - this.executedSubsteps * this.frozenTimestepSeconds * 1000;
    if (deltaMs > this.maxStallMs || lagMs > this.maxStallMs) this.fence('CLOCK_STALL_FENCED', 'Substep pacing stalled; refusing to resume');
    if (this.session.model.opt.timestep !== this.frozenTimestepSeconds) {
      this.fence('TIMESTEP_ALTERED', 'MuJoCo model timestep was altered during execution', 'TIMESTEP_ALTERED');
    }

    this.verifyOwnedStateUnchanged();
    let clearedOnStep = this.clearExternalForceArrays();

    if (this.executedSubsteps % this.policyDecimation === 0 && controlProvider) {
      try {
      const proposal = controlProvider(
        Math.floor(this.executedSubsteps / this.policyDecimation),
        this.executedSubsteps,
        Array.from(this.session.data.qpos),
        Array.from(this.session.data.qvel),
      );
      this.submitControlProposal(proposal);
      } catch (error) {
        if (this.status !== 'running') throw error;
        this.fence('CONTROL_PROVIDER_FAILED', `Control provider failed: ${String(error)}`);
      }
    }

    // User callbacks can revoke/stop or mutate Wasm state. Recheck at the actual
    // execution boundary, after every callback and immediately before mj_step.
    this.ensureRunning();
    const boundaryNow = this.readMonotonicMs?.() ?? nowMonotonicMs;
    if (!Number.isFinite(boundaryNow) || boundaryNow < this.lastWallMs) this.fence('CLOCK_ROLLBACK_FENCED', 'Clock rollback during control evaluation');
    if (boundaryNow >= this.attempt.deadlineMonotonicMs) this.fence('CONTROL_VETOED', 'Deadline expired during control evaluation', 'ATTEMPT_DEADLINE_EXPIRED');
    if (boundaryNow - this.lastWallMs > this.maxStallMs ||
      boundaryNow - this.attempt.startedMonotonicMs - this.executedSubsteps * this.frozenTimestepSeconds * 1000 > this.maxStallMs) {
      this.fence('CLOCK_STALL_FENCED', 'Control evaluation stalled; refusing overdue step');
    }
    nowMonotonicMs = boundaryNow;
    this.lastWallMs = boundaryNow;
    if (this.tabHidden) this.fence('TAB_HIDDEN_FENCED', 'Hidden during control evaluation', 'TAB_HIDDEN_FENCED');
    if (this.revoked) this.fence('CONTROL_VETOED', 'Revoked during control evaluation', 'REVOKED');
    if (this.session.model.opt.timestep !== this.frozenTimestepSeconds) this.fence('TIMESTEP_ALTERED', 'Timestep changed during control evaluation', 'TIMESTEP_ALTERED');
    this.verifyOwnedStateUnchanged();
    clearedOnStep += this.clearExternalForceArrays();

    const proposal = this.activeProposal;
    if (!proposal) {
      this.fence('CONTROL_VETOED', 'Missing control proposal for substep', 'CONTROL_MISSING');
    }
    if (proposal.generation !== this.attempt.generation) {
      this.fence('CONTROL_VETOED', `Stale control generation ${proposal.generation} !== ${this.attempt.generation}`, 'STALE_GENERATION');
    }
    if (proposal.authorityEpoch !== this.attempt.authorityEpoch) {
      this.fence(
        'CONTROL_VETOED',
        `Control authorityEpoch ${proposal.authorityEpoch} !== ${this.attempt.authorityEpoch}`,
        'AUTHORITY_EPOCH_MISMATCH',
      );
    }
    if (proposal.modelDigest !== this.attempt.modelDigest) {
      this.fence('CONTROL_VETOED', 'Control modelDigest does not match active model', 'MODEL_DIGEST_MISMATCH');
    }
    if (
      typeof proposal.proposedAtMonotonicMs !== 'number' ||
      !Number.isFinite(proposal.proposedAtMonotonicMs) ||
      typeof proposal.expiresAtMonotonicMs !== 'number' ||
      !Number.isFinite(proposal.expiresAtMonotonicMs) ||
      nowMonotonicMs < proposal.proposedAtMonotonicMs ||
      nowMonotonicMs >= proposal.expiresAtMonotonicMs
    ) {
      this.fence('CONTROL_VETOED', 'Control proposal expired or has invalid monotonic window', 'CONTROL_EXPIRED');
    }
    if (!Array.isArray(proposal.targetCtrl) || proposal.targetCtrl.length !== this.session.model.nu) {
      this.fence(
        'CONTROL_VETOED',
        `Control vector length ${proposal.targetCtrl?.length} !== nu (${this.session.model.nu})`,
        'CONTROL_DIMENSION_MISMATCH',
      );
    }
    for (let i = 0; i < this.session.model.nu; i++) {
      const u = proposal.targetCtrl[i];
      if (typeof u !== 'number' || !Number.isFinite(u)) {
        this.fence('CONTROL_VETOED', `Non-finite control value at actuator ${i}`, 'CONTROL_NONFINITE');
      }
      const [min, max] = this.session.actuatorCtrlRanges[i];
      if (u < min || u > max) {
        this.fence(
          'CONTROL_VETOED',
          `Control value ${u} at actuator ${i} exceeds ctrlrange [${min}, ${max}]; silent clamping is forbidden`,
          'CONTROL_OUT_OF_RANGE',
        );
      }
    }

    if (this.samples.length >= this.maxCaptureSamples) {
      this.fence('CAPTURE_OVERFLOW', `Capture buffer reached ceiling (${this.maxCaptureSamples}); refusing uncaptured step`, 'CAPTURE_OVERFLOW');
    }

    for (let i = 0; i < this.session.model.nu; i++) {
      this.session.data.ctrl[i] = proposal.targetCtrl[i];
    }

    try { this.session.mujoco.mj_step(this.session.model, this.session.data); }
    catch (error) { this.fence('ENGINE_STEP_FAILED', `MuJoCo step failed: ${String(error)}`); }
    this.executedSubsteps++;
    if (!this.hasFiniteState() || Math.abs(this.session.data.time - this.executedSubsteps * this.frozenTimestepSeconds) > 1e-12) {
      this.fence('ENGINE_STEP_FAILED', 'Non-finite state or unexpected engine time/reset after mj_step; capture incomplete');
    }
    this.shadowQpos.set(this.session.data.qpos);
    this.shadowQvel.set(this.session.data.qvel);
    this.shadowAct.set(this.session.data.act);
    this.shadowWarmstart.set(this.session.data.qacc_warmstart);
    this.shadowTime = this.session.data.time;

    const sample: CwS02SubstepSample = {
      tick: this.executedSubsteps,
      policyStep: Math.floor((this.executedSubsteps - 1) / this.policyDecimation),
      simTimeSeconds: this.session.data.time,
      monotonicMs: nowMonotonicMs,
      qpos: Array.from(this.session.data.qpos),
      qvel: Array.from(this.session.data.qvel),
      ctrl: Array.from(this.session.data.ctrl),
      qfrcActuator: Array.from(this.session.data.qfrc_actuator),
      xpos: Array.from(this.session.data.xpos),
      clearedExternalMutations: clearedOnStep,
      stepExecuted: true,
      vetoReason: null,
    };
    this.samples.push(sample);

    if (this.executedSubsteps >= this.totalSubsteps) {
      this.status = 'completed';
    }
    return structuredClone(sample);
  }

  /** Step up to maxSubstepsPerBatch in one bounded batch. */
  stepBatch(
    nowMonotonicMs: number,
    requestedSubsteps: number,
    controlProvider?: (
      policyStep: number,
      tick: number,
      qpos: readonly number[],
      qvel: readonly number[],
    ) => CwS02ControlProposal,
  ): CwS02SubstepSample[] {
    this.ensureRunning();
    if (!Number.isInteger(requestedSubsteps) || requestedSubsteps < 0 || requestedSubsteps > this.maxSubstepsPerBatch) {
      this.fence(
        'CLOCK_STALL_FENCED',
        `Requested batch size ${requestedSubsteps} exceeds maxSubstepsPerBatch (${this.maxSubstepsPerBatch})`,
      );
    }
    const batchOut: CwS02SubstepSample[] = [];
    const count = Math.min(requestedSubsteps, this.totalSubsteps - this.executedSubsteps);
    if (count > 0) {
      this.batchesExecuted++;
    }
    for (let k = 0; k < count; k++) {
      batchOut.push(this.stepSubstep(nowMonotonicMs, controlProvider));
      if (this.status !== 'running') break;
    }
    return batchOut;
  }

  getSamples(): readonly CwS02SubstepSample[] {
    return structuredClone(this.samples);
  }

  getSummary(): CwS02ExecutionSummary {
    return {
      profile: MUJOCO_WASM_PROFILE,
      engineVersion: MUJOCO_WASM_VERSION,
      wasmSha256: this.session.wasmSha256,
      scope: 'offline_simulation_only',
      physicalAcceptance: false,
      executionAuthority: 'none',
      planarFallbackUsed: false,
      status: this.status,
      vetoReason: this.vetoReason,
      fenceCode: this.fenceCode,
      errorMessage: this.errorMessage,
      attempt: { ...this.attempt },
      timestepSeconds: this.frozenTimestepSeconds,
      policyDecimation: this.policyDecimation,
      totalSubsteps: this.totalSubsteps,
      executedSubsteps: this.executedSubsteps,
      policyUpdates: this.policyUpdates,
      batchesExecuted: this.batchesExecuted,
      maxSubstepsPerBatch: this.maxSubstepsPerBatch,
      maxCaptureSamples: this.maxCaptureSamples,
      capturedSamples: this.samples.length,
      clearedExternalMutations: this.clearedExternalMutations,
      mutationPathsGuarded: CW_S02_MUTATION_PATHS,
      finalStateValid: this.hasFiniteState(),
      finalSimTimeSeconds: this.session.isDisposed || !Number.isFinite(this.session.data.time) ? null : this.session.data.time,
      finalQpos: this.session.isDisposed ? [] : finiteArray(this.session.data.qpos),
      finalQvel: this.session.isDisposed ? [] : finiteArray(this.session.data.qvel),
      finalCtrl: this.session.isDisposed ? [] : finiteArray(this.session.data.ctrl),
      traceDigest: sha256Hex(canonicalAssemblyString({
        modelDigest: this.attempt.modelDigest, timestepSeconds: this.frozenTimestepSeconds,
        policyDecimation: this.policyDecimation,
        samples: this.samples.map(({ monotonicMs: _wallTime, ...physics }) => physics),
      })),
    };
  }
}
