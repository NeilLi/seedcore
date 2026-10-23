import { canonicalAssemblyString, type RobotAssembly } from '@seedcore/contracts';
import { sha256Hex, type DrcReport } from '@seedcore/drc-solver';
import { AssemblyStore, fetchAssemblyText, type ProxyScene } from '@seedcore/robot-canvas';
import {
  assessSimulationReadiness, assertCompiledModelCurrent, compileAssemblyToMjcf,
  type CompiledMjcf, type CompilerOptions, type RawCompilerCatalog,
} from '@seedcore/wasm-sim-bridge';

export interface StudioModelBinding {
  revisionDigest: string; assemblyDigest: string; catalogDigest: string;
  drcDigest: string; authorityEpoch: number;
}

/** Revision identity/epoch are local freshness fences, never model content or authority. */
export function assertStudioModelCurrent(model: CompiledMjcf, retained: StudioModelBinding & { modelDigest: string }, live: StudioModelBinding): void {
  for (const key of ['revisionDigest', 'assemblyDigest', 'catalogDigest', 'drcDigest', 'authorityEpoch'] as const) {
    if (retained[key] !== live[key]) throw new Error(`Stale simulation handoff: ${key}`);
  }
  assertCompiledModelCurrent(model, { ...live, modelDigest: retained.modelDigest });
}

/** Offline inspector; nothing here executes MJCF or admits motion. */
export function setupSimulation(store: AssemblyStore<ProxyScene>) {
  const el = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
  const actions = ['sim-download-xml', 'sim-copy-xml', 'sim-download-bundle', 'sim-copy-bundle'];
  let accepted: { binding: StudioModelBinding; report: DrcReport; catalog: RawCompilerCatalog } | undefined;
  let compiled: { model: CompiledMjcf; binding: StudioModelBinding & { modelDigest: string } } | undefined;
  let lastKey = '';
  let disposed = false;
  const status = (message: string, state: string) => {
    el('sim-status').textContent = message;
    el('sim-status').dataset.state = state;
  };
  const invalidate = () => {
    compiled = undefined;
    for (const id of actions) el<HTMLButtonElement>(id).disabled = true;
    el('sim-model-digest').textContent = '—';
    el('sim-manifest').textContent = '';
    el<HTMLTextAreaElement>('sim-xml').value = '';
    el('sim-binding').textContent = '—';
    el('sim-provenance').textContent = 'Awaiting pinned sources · physicalAcceptance: false · authority: none';
    el('sim-readiness').textContent = 'BLOCKED · Awaiting current checks';
    el('sim-readiness').dataset.disposition = 'blocked';
    el('sim-blocking').replaceChildren();
    el('sim-deferred').replaceChildren();
    status('Waiting for current assembly and full DRC checks.', 'pending');
  };
  const options = (): CompilerOptions => {
    const actuatorMode = el<HTMLSelectElement>('sim-mode').value as 'position' | 'torque';
    return { actuatorMode, timestepSeconds: Number(el<HTMLInputElement>('sim-dt').value),
      ...(actuatorMode === 'position' ? { positionGain: Number(el<HTMLInputElement>('sim-kp').value) } : {}) };
  };
  const liveBinding = (): StudioModelBinding => {
    const state = store.getState(), current = state.current;
    if (disposed || state.loading || !current || !accepted) throw new Error('Current checks unavailable');
    return { revisionDigest: current.revisionDigest, assemblyDigest: current.assemblyDigest,
      catalogDigest: current.scene.catalogDigest, drcDigest: sha256Hex(canonicalAssemblyString(accepted.report)), authorityEpoch: state.authorityEpoch };
  };
  const currentModel = () => {
    if (!compiled) throw new Error('Compile a current simulation model first');
    assertStudioModelCurrent(compiled.model, compiled.binding, liveBinding());
    return compiled.model;
  };
  const render = () => {
    invalidate();
    if (!accepted) return;
    try {
      const live = liveBinding();
      const state = store.getState();
      const input = { assembly: structuredClone(state.current!.assembly) as RobotAssembly,
        catalog: accepted.catalog, drcReport: accepted.report, options: options() };
      // Check every binding before using a retained DRC result, including undo/redo ABA.
      for (const key of Object.keys(live) as (keyof StudioModelBinding)[]) {
        if (accepted.binding[key] !== live[key]) throw new Error('Waiting for current DRC');
      }
      const readiness = assessSimulationReadiness(input);
      el('sim-readiness').textContent = readiness.ready ? 'READY (Offline Simulation Only)' : 'BLOCKED';
      el('sim-readiness').dataset.disposition = readiness.ready ? 'pass' : 'blocked';
      el('sim-provenance').textContent = `${accepted.catalog.provenance} · physicalAcceptance: false · authority: none`;
      for (const [id, ids] of [['sim-deferred', readiness.deferredPhysicalFindings], ['sim-blocking', readiness.blockingFindings]] as const) {
        el(id).replaceChildren(...ids.map(findingId => {
          const f = accepted!.report.findings.find(f => f.id === findingId)!;
          const row = document.createElement('li'); row.dataset.code = f.code;
          row.textContent = `${f.code}: ${f.message}`; return row;
        }));
      }
      if (!readiness.ready) { status('Resolve simulation-blocking findings before compilation.', 'blocked'); return; }
      const model = compileAssemblyToMjcf(input);
      const retained = { ...accepted.binding, modelDigest: model.modelDigest };
      assertStudioModelCurrent(model, retained, liveBinding());
      compiled = { model, binding: retained };
      el('sim-model-digest').textContent = model.modelDigest;
      el('sim-binding').textContent = canonicalAssemblyString(live);
      el('sim-manifest').textContent = JSON.stringify(model.manifest, null, 2);
      el<HTMLTextAreaElement>('sim-xml').value = model.xml;
      for (const id of actions) el<HTMLButtonElement>(id).disabled = false;
      status('Compiled seedcore.cw-s01.model.v1 · offline handoff ready. Browser runtime qualification is CW-S02.', 'compiled');
    } catch (error) {
      compiled = undefined;
      el('sim-readiness').textContent = 'BLOCKED';
      el('sim-readiness').dataset.disposition = 'blocked';
      status(error instanceof Error ? error.message : 'Compilation rejected', 'blocked');
    }
  };
  const unsubscribe = store.subscribe(state => {
    const key = `${state.current?.revisionDigest}:${state.authorityEpoch}:${state.loading}`;
    if (key !== lastKey) { lastKey = key; accepted = undefined; invalidate(); }
  });
  for (const id of ['sim-mode', 'sim-dt', 'sim-kp']) {
    el(id).oninput = () => {
      el<HTMLInputElement>('sim-kp').disabled = el<HTMLSelectElement>('sim-mode').value === 'torque';
      render();
    };
  }
  el<HTMLButtonElement>('simulation-reference').onclick = () => {
    void store.loadFrom(async signal => {
      const profile = JSON.parse(await fetchAssemblyText('/api/simulation-reference', signal));
      if (profile.schemaVersion !== 'seedcore.cw-s01.reference.v1' || profile.provenance !== 'synthetic_fixture'
        || profile.scope !== 'offline_simulation_only' || profile.physicalAcceptance !== false || profile.executionAuthority !== 'none') {
        throw new Error('Offline reference scope mismatch');
      }
      return canonicalAssemblyString(profile.assembly);
    });
  };
  for (const id of actions) el<HTMLButtonElement>(id).onclick = async () => {
    try {
      const model = currentModel();
      const xml = id.endsWith('xml');
      const bytes = xml ? model.xml : canonicalAssemblyString(model) + '\n';
      if (id.includes('copy')) {
        await navigator.clipboard.writeText(bytes);
        // A delayed clipboard completion cannot restore a stale ready state.
        if (compiled?.model === model) { currentModel(); status('Copied current offline simulation artifact.', 'compiled'); }
      } else {
        const url = URL.createObjectURL(new Blob([bytes], { type: xml ? 'application/xml' : 'application/json' }));
        const link = document.createElement('a'); link.href = url;
        link.download = xml ? 'assembly.mjcf.xml' : 'assembly.cw-s01.model.json';
        link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch (error) { status(error instanceof Error ? error.message : 'Export failed', 'blocked'); }
  };
  return {
    invalidate,
    accept(result: { report: DrcReport; revisionDigest: string; authorityEpoch: number }, catalog: RawCompilerCatalog) {
      accepted = { report: result.report, catalog, binding: { revisionDigest: result.revisionDigest,
        authorityEpoch: result.authorityEpoch, assemblyDigest: result.report.assemblyDigest,
        catalogDigest: result.report.catalogDigest, drcDigest: sha256Hex(canonicalAssemblyString(result.report)) } };
      render();
    },
    dispose() { disposed = true; accepted = undefined; invalidate(); unsubscribe(); },
  };
}
