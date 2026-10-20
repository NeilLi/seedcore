/**
 * CW-A04 bounded DRC worker protocol and epoch-fenced coordinator.
 * Late or tampered worker messages cannot overwrite a newer assembly revision.
 */
import { canonicalAssemblyString, type RobotAssembly } from '@seedcore/contracts';
import {
  evaluateAssemblyDrc,
  sha256Hex,
  type DrcCatalog,
  type DrcEvalOptions,
  type DrcReport,
} from './solver.js';

export const MAX_DRC_WORKER_BYTES = 2 * 1024 * 1024;

export interface DrcWorkerRequest {
  schemaVersion: 'seedcore.drc.worker-request.v1';
  requestId: number;
  revisionDigest: string;
  authorityEpoch: number;
  assembly: RobotAssembly;
  catalog: DrcCatalog;
  options?: DrcEvalOptions;
}

export type DrcWorkerResponse =
  | {
      schemaVersion: 'seedcore.drc.worker-response.v1';
      requestId: number;
      revisionDigest: string;
      authorityEpoch: number;
      ok: true;
      report: DrcReport;
    }
  | {
      schemaVersion: 'seedcore.drc.worker-response.v1';
      requestId: number;
      revisionDigest: string;
      authorityEpoch: number;
      ok: false;
      error: string;
    };

export type DrcWorkerTransport = (
  request: DrcWorkerRequest,
  signal: AbortSignal,
) => Promise<DrcWorkerResponse>;

/** Pure deterministic worker request handler with bounded payload enforcement. */
export function handleDrcWorkerMessage(raw: DrcWorkerRequest): DrcWorkerResponse {
  const requestId = typeof raw?.requestId === 'number' ? raw.requestId : -1;
  const revisionDigest = typeof raw?.revisionDigest === 'string' ? raw.revisionDigest : '';
  const authorityEpoch = typeof raw?.authorityEpoch === 'number' ? raw.authorityEpoch : -1;
  try {
    if (
      !raw ||
      raw.schemaVersion !== 'seedcore.drc.worker-request.v1' ||
      !Number.isSafeInteger(raw.requestId) ||
      raw.requestId < 1 ||
      !/^[a-f0-9]{64}$/.test(raw.revisionDigest) ||
      !Number.isSafeInteger(raw.authorityEpoch) ||
      raw.authorityEpoch < 0
    ) {
      throw new Error('Malformed DRC worker request envelope');
    }
    const serialized = JSON.stringify(raw);
    if (new TextEncoder().encode(serialized).length > MAX_DRC_WORKER_BYTES) {
      throw new Error('DRC worker request exceeds 2 MiB byte bound');
    }
    const report = evaluateAssemblyDrc(raw.assembly, raw.catalog, raw.options);
    return {
      schemaVersion: 'seedcore.drc.worker-response.v1',
      requestId: raw.requestId,
      revisionDigest: raw.revisionDigest,
      authorityEpoch: raw.authorityEpoch,
      ok: true,
      report,
    };
  } catch (error) {
    return {
      schemaVersion: 'seedcore.drc.worker-response.v1',
      requestId,
      revisionDigest,
      authorityEpoch,
      ok: false,
      error: error instanceof Error ? error.message.slice(0, 500) : 'DRC worker evaluation failed',
    };
  }
}

export type DrcRunOutcome =
  | { status: 'committed'; report: DrcReport; revisionDigest: string; authorityEpoch: number }
  | { status: 'stale' }
  | { status: 'rejected'; error: string };

export interface DrcLiveRevisionRef {
  revisionDigest: string;
  assemblyDigest: string;
  catalogDigest: string;
  authorityEpoch: number;
}

/**
 * Coordinates asynchronous DRC worker evaluations with generation tickets,
 * timeouts, and ABA authority-epoch fencing.
 */
export class DrcWorkerCoordinator {
  private generation = 0;
  private controller?: AbortController;
  private disposed = false;
  private latestCommitted?: {
    revisionDigest: string;
    authorityEpoch: number;
    report: DrcReport;
  };

  constructor(
    private getLiveRef: () => DrcLiveRevisionRef | null,
    private transport: DrcWorkerTransport = async req => handleDrcWorkerMessage(structuredClone(req)),
    private timeoutMs = 5000,
  ) {
    if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1) {
      throw new Error('Invalid DRC worker timeout');
    }
  }

  getLatest(): { revisionDigest: string; authorityEpoch: number; report: DrcReport } | null {
    return this.latestCommitted ? structuredClone(this.latestCommitted) : null;
  }

  cancel(): void {
    ++this.generation;
    this.controller?.abort();
    this.controller = undefined;
  }

  dispose(): void {
    this.disposed = true;
    this.cancel();
    this.latestCommitted = undefined;
  }

  async evaluate(
    input: {
      revisionDigest: string;
      authorityEpoch: number;
      assembly: RobotAssembly;
      catalog: DrcCatalog;
      options?: DrcEvalOptions;
    },
  ): Promise<DrcRunOutcome> {
    if (this.disposed) return { status: 'stale' };
    const ticket = ++this.generation;
    this.controller?.abort();
    const controller = new AbortController();
    this.controller = controller;

    const expectedAssemblyDigest = sha256Hex(canonicalAssemblyString(input.assembly));
    const request: DrcWorkerRequest = {
      schemaVersion: 'seedcore.drc.worker-request.v1',
      requestId: ticket,
      revisionDigest: input.revisionDigest,
      authorityEpoch: input.authorityEpoch,
      assembly: structuredClone(input.assembly),
      catalog: structuredClone(input.catalog),
      ...(input.options ? { options: structuredClone(input.options) } : {}),
    };

    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeoutPromise = new Promise<never>((_, reject) => {
      controller.signal.addEventListener(
        'abort',
        () => reject(new Error('DRC worker cancelled or timed out')),
        { once: true },
      );
      timer = setTimeout(() => controller.abort(), this.timeoutMs);
    });

    try {
      const response = await Promise.race([
        this.transport(request, controller.signal),
        timeoutPromise,
      ]);
      if (this.disposed || ticket !== this.generation) {
        return { status: 'stale' };
      }
      const live = this.getLiveRef();
      if (
        !live ||
        live.revisionDigest !== input.revisionDigest ||
        live.authorityEpoch !== input.authorityEpoch
      ) {
        return { status: 'stale' };
      }
      if (
        !response ||
        response.schemaVersion !== 'seedcore.drc.worker-response.v1' ||
        response.requestId !== ticket ||
        response.revisionDigest !== live.revisionDigest ||
        response.authorityEpoch !== live.authorityEpoch
      ) {
        return { status: 'rejected', error: 'DRC worker response envelope mismatch' };
      }
      if (!response.ok) {
        return { status: 'rejected', error: response.error };
      }
      const report = response.report;
      if (
        report.schemaVersion !== 'seedcore.drc.report.v1' ||
        report.scope !== 'offline_proxy_authoring' ||
        report.physicalAcceptance !== false ||
        report.executionAuthority !== 'none' ||
        report.assemblyDigest !== expectedAssemblyDigest ||
        report.assemblyDigest !== live.assemblyDigest ||
        report.catalogDigest !== input.catalog.catalogDigest ||
        report.catalogDigest !== live.catalogDigest
      ) {
        return { status: 'rejected', error: 'DRC worker report digest or authority scope mismatch' };
      }
      const frozenReport = structuredClone(report);
      this.latestCommitted = {
        revisionDigest: live.revisionDigest,
        authorityEpoch: live.authorityEpoch,
        report: frozenReport,
      };
      return {
        status: 'committed',
        report: structuredClone(frozenReport),
        revisionDigest: live.revisionDigest,
        authorityEpoch: live.authorityEpoch,
      };
    } catch (error) {
      if (this.disposed || ticket !== this.generation) {
        return { status: 'stale' };
      }
      const live = this.getLiveRef();
      if (!live || live.revisionDigest !== input.revisionDigest || live.authorityEpoch !== input.authorityEpoch) {
        return { status: 'stale' };
      }
      return {
        status: 'rejected',
        error: error instanceof Error ? error.message : 'DRC worker failed',
      };
    } finally {
      clearTimeout(timer);
      if (ticket === this.generation) this.controller = undefined;
    }
  }
}
