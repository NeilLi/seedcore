import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';
import { parseAssemblyText, canonicalAssemblyString } from '@seedcore/contracts';
import { GALLERY, forkGalleryAssembly, gallerySource } from '../apps/mini-studio/src/gallery.js';

const raw = readFileSync(new URL('../../packages/component-registry/assemblies/tabletop-starter.sc-assembly.json',import.meta.url),'utf8');
const entry = GALLERY[0];
const source = () => parseAssemblyText(raw);
test('gallery forks have fresh draft identity and persistent source/license ancestry', () => {
  const original=source(), a=forkGalleryAssembly(entry,original,'fork-'+'a'.repeat(32),'2026-11-06T13:00:00Z');
  const b=forkGalleryAssembly(entry,original,'fork-'+'b'.repeat(32),'2026-11-06T13:00:00Z');
  assert.notEqual(a.identity.assembly_id,b.identity.assembly_id);
  assert.equal(a.identity.status,'draft'); assert.equal(a.runtime_profile,'offline_proxy_no_actuation');
  assert.equal(original.identity.status,source().identity.status);
  const lineage=JSON.parse(a.metadata!.notes!);
  assert.equal(lineage.license,'Apache-2.0');assert.equal(lineage.source_sha256,entry.sha256);
  assert.equal(JSON.parse(parseAssemblyText(canonicalAssemblyString(a)).metadata!.notes!).source,lineage.source);
});
test('gallery refuses a changed source and an invalid identity',()=>{
  const altered=source(); altered.identity.name='Changed source';
  assert.throws(()=>forkGalleryAssembly(entry,altered,'fork-'+'a'.repeat(32),'2026-11-06T13:00:00Z'),/mismatch/);
  assert.throws(()=>forkGalleryAssembly(entry,source(),'../bad','2026-11-06T13:00:00Z'),/identity/);
});
test('pinned gallery source rejects changed or unavailable bytes',async()=>{
  const old=globalThis.fetch;
  try {
    globalThis.fetch=async()=>new Response(raw); assert.equal((await gallerySource(entry,new AbortController().signal)).identity.assembly_id,source().identity.assembly_id);
    globalThis.fetch=async()=>new Response(raw+' '); await assert.rejects(()=>gallerySource(entry,new AbortController().signal),/changed/);
    globalThis.fetch=async()=>new Response('',{status:404}); await assert.rejects(()=>gallerySource(entry,new AbortController().signal));
  } finally {globalThis.fetch=old;}
});
test('synthetic gallery verifies profile scope and canonical assembly before forking',async()=>{
  const rawProfile=readFileSync(new URL('../../packages/simulation-fixtures/cw-s01/reference.json',import.meta.url),'utf8');
  const old=globalThis.fetch;
  try {
    globalThis.fetch=async()=>new Response(rawProfile);
    const selected=await gallerySource(GALLERY[1],new AbortController().signal);
    const fork=forkGalleryAssembly(GALLERY[1],selected,'fork-'+'c'.repeat(32),'2026-11-06T13:00:00Z');
    const lineage=JSON.parse(fork.metadata!.notes!);assert.equal(lineage.entry,'synthetic-reference');assert.equal(lineage.source_digest_profile,'canonical_assembly');
    const profile=JSON.parse(rawProfile);profile.assembly.identity.name='Changed';
    globalThis.fetch=async()=>new Response(JSON.stringify(profile));await assert.rejects(()=>gallerySource(GALLERY[1],new AbortController().signal),/changed/);
    profile.physicalAcceptance=true;globalThis.fetch=async()=>new Response(JSON.stringify(profile));await assert.rejects(()=>gallerySource(GALLERY[1],new AbortController().signal),/scope/);
  } finally {globalThis.fetch=old;}
});
