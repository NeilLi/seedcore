import {
  CW_S02_WORKER_PROTOCOL,
  CwS02Error,
  MujocoBoundedExecutor,
  buildDeterministicRehearsalProposal,
  createMujocoModelSession,
  loadVerifiedMujocoModule,
  readPinnedMujocoWasm,
  type CompiledMjcf,
  type CwS02AttemptBinding,
  type MujocoModelSession,
} from '@seedcore/wasm-sim-bridge';

declare const __MUJOCO_WASM_SHA256__: string;
declare const __MUJOCO_WASM_BYTES__: number;

const worker = globalThis as unknown as {
  onmessage: ((e: MessageEvent) => void) | null;
  postMessage: (v: unknown) => void;
};

let activeGeneration = 0;
let stopped = false;
let timer: ReturnType<typeof setTimeout> | undefined;
let activeSession: MujocoModelSession | undefined;
let activeExecutor: MujocoBoundedExecutor | undefined;
let activeRun: { controller: AbortController } | undefined;

function cleanupSession(): void {
  activeRun?.controller.abort();
  activeRun = undefined;
  clearTimeout(timer);
  timer = undefined;
  try {
    activeSession?.dispose();
  } catch {}
  activeSession = undefined;
  activeExecutor = undefined;
}

worker.onmessage = async ({ data: m }) => {
  if (!m || m.protocol !== CW_S02_WORKER_PROTOCOL) return;
  if (m.type === 'stop') {
    if (!m.generation || m.generation === activeGeneration) {
      stopped = true;
      activeExecutor?.stop(typeof m.reason === 'string' ? m.reason : 'Stopped by operator');
      const summary = activeExecutor?.getSummary();
      cleanupSession();
      worker.postMessage({
        protocol: CW_S02_WORKER_PROTOCOL,
        type: 'stopped',
        generation: activeGeneration,
        reason: typeof m.reason === 'string' ? m.reason : 'Stopped by operator',
        ...(summary ? { summary } : {}),
      });
    }
    return;
  }
  if (m.type === 'hidden') {
    if (!m.generation || m.generation === activeGeneration) {
      activeExecutor?.notifyVisibilityHidden();
      if (!activeExecutor) {
        cleanupSession();
        worker.postMessage({ protocol: CW_S02_WORKER_PROTOCOL, type: 'error', generation: activeGeneration,
          code: 'TAB_HIDDEN_FENCED', error: 'TAB_HIDDEN_FENCED: hidden during worker startup' });
      }
    }
    return;
  }
  if (m.type === 'revoke') {
    if (!m.generation || m.generation === activeGeneration) {
      activeExecutor?.revoke(typeof m.reason === 'string' ? m.reason : 'Revoked by operator');
      if (!activeExecutor) {
        cleanupSession();
        worker.postMessage({ protocol: CW_S02_WORKER_PROTOCOL, type: 'error', generation: activeGeneration,
          code: 'AUTHORITY_FENCED', error: 'AUTHORITY_FENCED: revoked during worker startup' });
      }
    }
    return;
  }
  if (m.type !== 'run') return;

  const generation = Number(m.generation);
  if (!Number.isSafeInteger(generation) || generation <= activeGeneration) return;
  cleanupSession();
  const run = { controller: new AbortController() };
  activeRun = run;
  const isCurrent = () => activeRun === run;
  const startupTimeout = setTimeout(() => run.controller.abort(), 10000);
  activeGeneration = generation;
  stopped = false;

  const send = (type: string, extra: Record<string, unknown> = {}) => {
    worker.postMessage({
      protocol: CW_S02_WORKER_PROTOCOL,
      type,
      generation,
      ...extra,
    });
  };

  try {
    if (!Number.isInteger(generation) || generation < 1 || !m.model || !m.binding) {
      throw new CwS02Error('AUTHORITY_FENCED', 'Invalid CW-S02 worker run envelope');
    }
    const model = m.model as CompiledMjcf;
    const binding = m.binding as {
      revisionDigest: string;
      assemblyDigest: string;
      catalogDigest: string;
      drcDigest: string;
      modelDigest: string;
      authorityEpoch: number;
    };
    const totalSubsteps = Number.isInteger(m.totalSubsteps) ? Number(m.totalSubsteps) : 60;
    const policyDecimation = Number.isInteger(m.policyDecimation) ? Number(m.policyDecimation) : 10;

    const wasmBytes = await readPinnedMujocoWasm(
      await fetch('/mujoco.wasm', { signal: run.controller.signal }),
      __MUJOCO_WASM_BYTES__,
      __MUJOCO_WASM_SHA256__,
    );
    if (!isCurrent()) return;

    const mujoco = await loadVerifiedMujocoModule(
      wasmBytes,
      __MUJOCO_WASM_BYTES__,
      __MUJOCO_WASM_SHA256__,
    );
    if (!isCurrent()) return;
    if (run.controller.signal.aborted) throw new CwS02Error('WASM_FETCH_FAILED', 'MuJoCo worker startup timed out');
    clearTimeout(startupTimeout);

    const session = createMujocoModelSession(mujoco, model, binding);
    activeSession = session;
    const inspection = session.inspectModel();
    const restAngles = model.manifest.joints.map(j => j.restAngleRad);
    const mode = model.manifest.options.actuatorMode;

    const startedMonotonicMs = performance.now();
    const attempt: CwS02AttemptBinding = {
      ...binding,
      generation,
      startedMonotonicMs,
      deadlineMonotonicMs: startedMonotonicMs + 5000,
    };

    const executor = new MujocoBoundedExecutor(session, {
      policyDecimation,
      totalSubsteps,
      maxSubstepsPerBatch: 8,
      maxStallMs: 250,
      maxCaptureSamples: totalSubsteps,
      readMonotonicMs: () => performance.now(),
      attempt,
    });
    activeExecutor = executor;
    const environment = { crossOriginIsolated: globalThis.crossOriginIsolated === true,
      sharedArrayBufferAvailable: typeof SharedArrayBuffer !== 'undefined' };
    send('ready', { inspection, environment, summary: executor.getSummary() });

    const advance = () => {
      if (stopped || !isCurrent()) return;
      try {
        const now = performance.now();
        const due = executor.dueSubsteps(now);
        if (due > 0) {
          executor.stepBatch(now, due, policyStep =>
            buildDeterministicRehearsalProposal(
              attempt,
              session.actuatorCtrlRanges,
              restAngles,
              mode,
              policyStep,
              now,
              150,
            ),
          );
          send('progress', { summary: executor.getSummary() });
        }
        const summary = executor.getSummary();
        if (summary.status === 'completed') {
          const samples = executor.getSamples();
          cleanupSession();
          send('complete', { inspection, environment, summary, samples });
        } else if (summary.status === 'running') {
          timer = setTimeout(advance, 4);
        }
      } catch (error) {
        const summary = activeExecutor?.getSummary();
        cleanupSession();
        send('error', {
          error: error instanceof Error ? error.message : String(error),
          code: error instanceof CwS02Error ? error.code : 'ENGINE_COMPILE_FAILED',
          vetoReason: error instanceof CwS02Error ? (error.vetoReason ?? null) : null,
          ...(summary ? { summary } : {}),
        });
      }
    };
    timer = setTimeout(advance, 4);
  } catch (error) {
    if (!isCurrent()) return;
    const summary = activeExecutor?.getSummary();
    cleanupSession();
    send('error', {
      error: error instanceof Error ? error.message : String(error),
      code: error instanceof CwS02Error ? error.code : 'ENGINE_COMPILE_FAILED',
      vetoReason: error instanceof CwS02Error ? (error.vetoReason ?? null) : null,
      ...(summary ? { summary } : {}),
    });
  } finally { clearTimeout(startupTimeout); }
};
