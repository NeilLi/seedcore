import { canonicalAssemblyString, parseAssemblyText, validateAssemblyStructure, type RobotAssembly } from '@seedcore/contracts';

export type Frozen<T> = T extends object ? { readonly [K in keyof T]: Frozen<T[K]> } : T;
export type Selection = { kind: 'node' | 'edge'; id: string } | null;
export interface Revision<S> {
  sequence: number; revisionDigest: string; parentDigest: string | null;
  assemblyDigest: string; assembly: RobotAssembly; scene: S; selection: Selection;
}
export interface StoreState<S> {
  current: Revision<S> | null; loading: boolean; error: string | null;
  canUndo: boolean; canRedo: boolean; authorityEpoch: number; admission: null;
}
export type LoadResult = 'committed' | 'rejected' | 'stale';
export const sha256Text = async (text: string): Promise<string> => {
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('');
};
function freeze<T>(value: T): Frozen<T> {
  if (value && typeof value === 'object') {
    if (!Array.isArray(value) && Object.getPrototypeOf(value) !== Object.prototype && Object.getPrototypeOf(value) !== null) throw new Error('Revision scene must contain plain JSON objects');
    Object.values(value).forEach(freeze); Object.freeze(value);
  }
  return value as Frozen<T>;
}
function validSelection(assembly: RobotAssembly, selection: Selection): boolean {
  return !selection || (selection.kind === 'node' ? assembly.nodes.some(n => n.node_id === selection.id) : assembly.mechanical_tree.some(e => e.edge_id === selection.id));
}
/** Offline revisions only. No execution authority is accepted, retained or minted here. */
export class AssemblyStore<S> {
  private history: Revision<S>[] = [];
  private cursor = -1;
  private sequence = 0;
  private generation = 0;
  private epoch = 0;
  private controller?: AbortController;
  private listeners = new Set<(state: Frozen<StoreState<S>>) => void>();
  private disposed = false;
  private loading = false;
  private error: string | null = null;
  constructor(private prepare: (assembly: RobotAssembly, signal: AbortSignal) => Promise<S>, private options: { timeoutMs?: number; historyLimit?: number; byteLimit?: number } = {}) {
    if ((options.historyLimit !== undefined && (!Number.isSafeInteger(options.historyLimit) || options.historyLimit < 1)) || (options.byteLimit !== undefined && options.byteLimit < 1) || (options.timeoutMs !== undefined && options.timeoutMs < 1)) throw new Error("Invalid store bounds");
  }
  getState(): Frozen<StoreState<S>> {
    return freeze({current: this.history[this.cursor] ?? null, loading: this.loading, error: this.error,
      canUndo: this.cursor > 0, canRedo: this.cursor >= 0 && this.cursor < this.history.length - 1,
      authorityEpoch: this.epoch, admission: null});
  }
  subscribe(listener: (state: Frozen<StoreState<S>>) => void): () => void {
    this.listeners.add(listener); listener(this.getState()); return () => this.listeners.delete(listener);
  }
  private publish(): void { const state = this.getState(); for (const listener of this.listeners) { try { listener(state); } catch { /* A view cannot roll back a committed revision. */ } } }
  private invalidate(): number { ++this.generation; this.controller?.abort(); this.controller = undefined; return this.generation; }
  cancelLoad(): void { this.invalidate(); this.loading = false; this.error = null; if (!this.disposed) this.publish(); }
  dispose(): void { this.disposed = true; this.invalidate(); this.listeners.clear(); }
  select(selection: Selection): void {
    if (this.disposed) return;
    const current = this.history[this.cursor];
    if (!current || !validSelection(current.assembly, selection)) throw new Error('Unknown selection');
    this.history[this.cursor] = freeze({...current, selection: structuredClone(selection)}) as Revision<S>;
    this.publish();
  }
  undo(): void { this.travel(-1); }
  redo(): void { this.travel(1); }
  private travel(delta: number): void {
    if (this.disposed) return;
    this.invalidate(); this.loading = false; this.error = null;
    const next = this.cursor + delta;
    if (next >= 0 && next < this.history.length) { this.cursor = next; ++this.epoch; }
    this.publish();
  }
  loadText(text: string): Promise<LoadResult> { return this.transact(async () => parseAssemblyText(text), false); }
  loadFrom(load: (signal: AbortSignal) => Promise<string>): Promise<LoadResult> {
    return this.transact(async signal => parseAssemblyText(await load(signal)), false);
  }
  edit(change: (draft: RobotAssembly) => void): Promise<LoadResult> {
    const current = this.history[this.cursor];
    return this.transact(async () => {
      if (!current) throw new Error('Load a build before editing');
      const draft = structuredClone(current.assembly); change(draft); return validateAssemblyStructure(draft);
    }, true);
  }
  private async transact(load: (signal: AbortSignal) => Promise<RobotAssembly>, preserveSelection: boolean): Promise<LoadResult> {
    if (this.disposed) return 'stale';
    const ticket = this.invalidate(), controller = new AbortController(); this.controller = controller;
    this.loading = true; this.error = null; this.publish();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const work = async (): Promise<Revision<S>> => {
      const assembly = validateAssemblyStructure(await load(controller.signal));
      // Callers and preparation callbacks cannot mutate a candidate behind its digest.
      const scene = structuredClone(await this.prepare(structuredClone(assembly), controller.signal));
      const assemblyDigest = await sha256Text(canonicalAssemblyString(assembly));
      const parentDigest = this.history[this.cursor]?.revisionDigest ?? null;
      const sequence = this.sequence + 1;
      const revisionDigest = await sha256Text(JSON.stringify({schema: 'seedcore.studio.revision.v1', sequence, parentDigest, assemblyDigest}));
      const selection = preserveSelection ? this.history[this.cursor]?.selection ?? null : null;
      return {sequence, parentDigest, revisionDigest, assemblyDigest, assembly, scene, selection: validSelection(assembly, selection) ? selection : null};
    };
    const aborted = new Promise<never>((_, reject) => {
      controller.signal.addEventListener('abort', () => reject(new Error('Load cancelled or timed out')), {once: true});
      timer = setTimeout(() => controller.abort(), this.options.timeoutMs ?? 10000);
    });
    try {
      const revision = await Promise.race([work(), aborted]);
      if (ticket !== this.generation || this.disposed) return 'stale';
      const limit = this.options.byteLimit ?? 2 * 1024 * 1024;
      if (new TextEncoder().encode(JSON.stringify(revision)).length > limit) throw new Error('Revision exceeds history byte bound');
      const history = [...this.history.slice(0, this.cursor + 1), revision];
      while (history.length > (this.options.historyLimit ?? 32) || new TextEncoder().encode(JSON.stringify(history)).length > limit) history.shift();
      this.history = freeze(history) as unknown as Revision<S>[];
      // Keep the history container private and mutable; revisions themselves remain frozen.
      this.history = [...this.history]; this.cursor = this.history.length - 1;
      this.sequence = revision.sequence; ++this.epoch;
      this.loading = false; this.error = null; this.publish(); return 'committed';
    } catch (error) {
      if (ticket !== this.generation || this.disposed) return 'stale';
      this.loading = false; this.error = error instanceof Error ? error.message : 'Import failed'; this.publish(); return 'rejected';
    } finally { clearTimeout(timer); if (ticket === this.generation) this.controller = undefined; }
  }
}
