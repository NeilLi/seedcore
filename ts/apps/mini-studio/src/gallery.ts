import { canonicalAssemblyString, parseAssemblyText, parseStrictJson, type RobotAssembly } from '@seedcore/contracts';
import { sha256Hex } from '@seedcore/drc-solver';
import { AssemblyStore, fetchAssemblyText, sha256Text, type ProxyScene } from '@seedcore/robot-canvas';

/** Curated local source; pins are part of the shipped application, not the response. */
export const GALLERY = Object.freeze([Object.freeze({
  id: 'tabletop-starter', name: 'Tabletop starter', source: '/api/starter',
  sha256: '14a3a17d66b799ee14326f0815382744ea1153879a2277d2788444b82d7946c7',
  canonicalSha256: '2550d184c44a064c6ad6a2245a08f430f257c40ca8f3627e73eeb3fedd452acb', kind:'assembly',
  license: 'Apache-2.0', sourcePath: 'packages/component-registry/assemblies/tabletop-starter.sc-assembly.json',
  description: 'Five illustrative proxy parts. Electrical and physical qualification remain open.',
}), Object.freeze({
  id:'synthetic-reference', name:'Synthetic simulation reference', source:'/api/simulation-reference',
  sha256:'84f81bb519bedd7d9aacab6061767dd60d0b2fc2651eb6e21d3550dad2c3529d',
  canonicalSha256:'84f81bb519bedd7d9aacab6061767dd60d0b2fc2651eb6e21d3550dad2c3529d', kind:'profile',
  license:'Apache-2.0', sourcePath:'packages/simulation-fixtures/cw-s01/reference.json',
  description:'Synthetic mathematical fixture for bounded simulation; not hardware.',
})]);
type Entry = typeof GALLERY[number];

export async function gallerySource(entry: Entry, signal: AbortSignal): Promise<RobotAssembly> {
  if (!GALLERY.includes(entry)) throw new Error('Unknown gallery entry');
  const raw = await fetchAssemblyText(entry.source, signal);
  if (entry.kind === 'assembly') {
    if (await sha256Text(raw) !== entry.sha256) throw new Error('Gallery source changed or unavailable');
    return parseAssemblyText(raw);
  }
  const profile = parseStrictJson(raw) as any;
  if (profile?.schemaVersion !== 'seedcore.cw-s01.reference.v1' || profile.scope !== 'offline_simulation_only' ||
      profile.physicalAcceptance !== false || profile.executionAuthority !== 'none' || profile.provenance !== 'synthetic_fixture') throw new Error('Gallery fixture scope mismatch');
  const assembly = parseAssemblyText(canonicalAssemblyString(profile.assembly));
  if (sha256Hex(canonicalAssemblyString(assembly)) !== entry.canonicalSha256) throw new Error('Gallery source changed or unavailable');
  return assembly;
}

/** Provenance is stored in v2 metadata, so it travels with exports and build packs. */
export function forkGalleryAssembly(entry: Entry, source: RobotAssembly, id: string, createdAt: string): RobotAssembly {
  if (!GALLERY.includes(entry) || !/^fork-[a-f0-9]{32}$/.test(id)) throw new Error('Invalid curated fork identity');
  if (sha256Hex(canonicalAssemblyString(source)) !== entry.canonicalSha256) throw new Error('Curated source content mismatch');
  const fork = structuredClone(source);
  const lineage = JSON.stringify({schema:'seedcore.gallery-lineage.v1',entry:entry.id,source:entry.sourcePath,
    source_sha256:entry.sha256,source_digest_profile:entry.kind === 'assembly' ? 'raw_source_bytes' : 'canonical_assembly',license:entry.license,prior_notes:source.metadata?.notes ?? null,
    prior_generator:source.metadata?.generator ?? null});
  if (lineage.length > 512) throw new Error('Source lineage exceeds assembly metadata bound');
  fork.identity = {...fork.identity, assembly_id:id, version:'0.1.0', name:`${entry.name} — fork`, status:'draft', created_at:createdAt};
  fork.metadata = {notes:lineage,generator:'seedcore.gallery.fork.v1'};
  return parseAssemblyText(canonicalAssemblyString(fork));
}

export function setupGallery(store: AssemblyStore<ProxyScene>): () => void {
  const status = document.getElementById('gallery-status')!;
  const preview = document.getElementById('gallery-open') as HTMLButtonElement;
  const fork = document.getElementById('gallery-fork') as HTMLButtonElement;
  const synthetic = document.getElementById('gallery-synthetic') as HTMLButtonElement;
  let generation = 0, disposed = false;
  const run = async (entry: Entry, makeFork: boolean) => {
    const ticket = ++generation;
    status.textContent = 'Checking the curated source and its pinned dependencies…';
    const result = await store.loadFrom(async signal => {
      const source = await gallerySource(entry, signal);
      const assembly = makeFork ? forkGalleryAssembly(entry, source, `fork-${crypto.randomUUID().replaceAll('-', '')}`,
        new Date().toISOString().replace(/\.\d{3}Z$/, 'Z')) : source;
      return canonicalAssemblyString(assembly);
    });
    if (disposed || ticket !== generation) return;
    status.textContent = result === 'committed'
      ? makeFork ? 'New draft fork loaded. Its source and license are retained in the exported assembly.' : 'Curated source loaded for inspection.'
      : result === 'stale' ? 'Gallery load superseded by a newer action.' : `Gallery unavailable. ${store.getState().error ?? 'Source or dependency check failed.'}`;
  };
  preview.onclick = () => { void run(GALLERY[0], false); };
  fork.onclick = () => { void run(GALLERY[0], true); };
  synthetic.onclick = () => { void run(GALLERY[1], true); };
  return () => { disposed = true; ++generation; preview.onclick = null; fork.onclick = null; synthetic.onclick = null; };
}
