import { canonicalAssemblyString, type RobotAssembly } from '@seedcore/contracts';
import { sha256Hex, type DrcReport } from '@seedcore/drc-solver';
import { AssemblyStore, type ProxyScene } from '@seedcore/robot-canvas';
import { createBuildPack, type RawCompilerCatalog } from '@seedcore/wasm-sim-bridge';

export interface BuildPackBinding {
  revisionDigest: string;
  assemblyDigest: string;
  catalogDigest: string;
  authorityEpoch: number;
}

/** An undo back to identical content still needs a fresh DRC acceptance. */
export function assertBuildPackCurrent(retained: BuildPackBinding, current: BuildPackBinding | null): void {
  if (!current) throw new Error('Recheck DRC for the current build before exporting.');
  for (const key of ['revisionDigest', 'assemblyDigest', 'catalogDigest', 'authorityEpoch'] as const) {
    if (retained[key] !== current[key]) throw new Error(`Draft pack is stale (${key}). Recheck DRC.`);
  }
}

/** Read-only draft export. No token, admission, actuator or evidence API is called. */
export function setupBuildPack(store: AssemblyStore<ProxyScene>) {
  const button = document.getElementById('build-pack-download') as HTMLButtonElement;
  const status = document.getElementById('build-pack-status') as HTMLElement;
  const details = document.getElementById('build-pack-details') as HTMLElement;
  let disposed = false;
  let generation = 0;
  let retained: { binding: BuildPackBinding; report: DrcReport; catalog: RawCompilerCatalog } | undefined;
  const live = (): BuildPackBinding | null => {
    const state = store.getState(), current = state.current;
    if (disposed || state.loading || !current) return null;
    return { revisionDigest: current.revisionDigest, assemblyDigest: current.assemblyDigest,
      catalogDigest: current.scene.catalogDigest, authorityEpoch: state.authorityEpoch };
  };
  const setStatus = (message: string, state: string) => {
    status.textContent = message;
    status.dataset.state = state;
  };
  const invalidate = (reason = 'Waiting for current DRC. Draft export is unavailable until checks finish.') => {
    ++generation;
    retained = undefined;
    button.disabled = true;
    details.textContent = '';
    setStatus(reason, 'unavailable');
  };
  const unsubscribe = store.subscribe(() => {
    if (!retained) return;
    try { assertBuildPackCurrent(retained.binding, live()); }
    catch { invalidate(); }
  });
  const onSettings = () => invalidate('Simulation settings changed. Recheck DRC before exporting a fresh draft pack.');
  const settings = ['sim-mode', 'sim-dt', 'sim-kp'].map(id => document.getElementById(id)!);
  for (const element of settings) {
    element.addEventListener('input', onSettings);
    element.addEventListener('change', onSettings);
  }
  const preset = document.getElementById('sim-rehearsal-preset')!;
  preset.addEventListener('click', onSettings);
  button.onclick = () => {
    try {
      if (!retained) throw new Error('Recheck DRC before exporting a draft pack.');
      const accepted = retained;
      assertBuildPackCurrent(accepted.binding, live());
      const current = store.getState().current!;
      const assembly = structuredClone(current.assembly) as RobotAssembly;
      if (sha256Hex(canonicalAssemblyString(assembly)) !== accepted.binding.assemblyDigest) {
        throw new Error('Current assembly content does not match accepted DRC.');
      }
      const result = createBuildPack({ assembly, catalog: accepted.catalog, drcReport: accepted.report,
        options: { actuatorMode: 'position', positionGain: 1, timestepSeconds: 0.002 } });
      assertBuildPackCurrent(accepted.binding, live());
      if (retained !== accepted) throw new Error('Draft pack was invalidated before download.');
      // A fresh ArrayBuffer-backed copy satisfies Blob's browser contract.
      const bytes = new Uint8Array(result.bytes.length); bytes.set(result.bytes);
      const url = URL.createObjectURL(new Blob([bytes], { type: 'application/zip' }));
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `draft-build-${accepted.binding.assemblyDigest.slice(0, 12)}.zip`;
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      const manifest = result.manifest;
      details.textContent = JSON.stringify(manifest, null, 2);
      setStatus(`Draft design ZIP downloaded · ${result.bytes.length} bytes · ${manifest.bom.unpricedPartCount} unpriced part instance(s) · ${manifest.wiring.unresolvedNetCount} unresolved net(s). ` +
        (manifest.model.included ? 'Offline simulation model included. ' : `Model omitted: ${manifest.model.reason} `) +
        'Hardware qualification remains open; no execution authority.', 'downloaded');
    } catch (error) {
      invalidate(error instanceof Error ? error.message : 'Draft pack export failed. Recheck DRC.');
      status.dataset.state = 'refused';
    }
  };
  invalidate();
  return {
    begin(): number { invalidate(); return generation; },
    accept(result: { report: DrcReport; revisionDigest: string; authorityEpoch: number }, catalog: RawCompilerCatalog, ticket: number): void {
      if (disposed || ticket !== generation) return;
      const binding = { revisionDigest: result.revisionDigest, authorityEpoch: result.authorityEpoch,
        assemblyDigest: result.report.assemblyDigest, catalogDigest: result.report.catalogDigest };
      try { assertBuildPackCurrent(binding, live()); }
      catch { invalidate(); return; }
      retained = { binding, report: structuredClone(result.report), catalog: structuredClone(catalog) };
      button.disabled = false;
      details.textContent = '';
      setStatus(`Draft pack ready · ${result.report.bom.unpricedPartCount} unpriced part instance(s). ` +
        'Includes unresolved design nets; physical qualification and printable assets remain unavailable.', 'ready');
    },
    invalidate,
    dispose(): void {
      disposed = true; unsubscribe(); invalidate('Draft pack exporter closed.'); button.onclick = null;
      for (const element of settings) {
        element.removeEventListener('input', onSettings);
        element.removeEventListener('change', onSettings);
      }
      preset.removeEventListener('click', onSettings);
    },
  };
}
