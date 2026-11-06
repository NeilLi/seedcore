import assert from 'node:assert/strict';
import test from 'node:test';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { canonicalAssemblyString } from '@seedcore/contracts';
import { sha256Hex } from '@seedcore/drc-solver';
import { createBuildPack, buildPackCsvCell } from '@seedcore/wasm-sim-bridge';
import { realStarterInput, studioReferenceInput, refreshFixture, rewriteFixturePart } from './fixtures/cw-s01.js';

const text = (pack: ReturnType<typeof createBuildPack>, path: string) => new TextDecoder().decode(pack.files.find(f => f.path===path)!.bytes);
const fixture = () => { const input=studioReferenceInput();input.options.positionGain=1;return input; };

test('CW-E01 identical content is byte-identical and every payload has an independent hash', () => {
  const input=fixture(), before=canonicalAssemblyString(input), a=createBuildPack(input), b=createBuildPack(structuredClone(input));
  assert.deepEqual(a.bytes,b.bytes);assert.equal(canonicalAssemblyString(input),before);
  assert.equal(a.manifest.status,'draft');assert.equal(a.manifest.physicalAcceptance,false);assert.equal(a.manifest.executionAuthority,'none');
  assert.equal(a.manifest.model.included,true);assert.equal(a.manifest.inventoryScope,'all_payload_files_excluding_manifest');
  assert.equal(a.manifest.files.length,a.files.length-1);
  for(const entry of a.manifest.files){const bytes=a.files.find(f=>f.path===entry.path)!.bytes;assert.equal(bytes.length,entry.bytes);assert.equal(createHash('sha256').update(bytes).digest('hex'),entry.sha256);}
  assert.ok(!a.manifest.files.some(f=>f.path==='manifest.json'));
});
test('CW-E01 real blocked starter retains all DRC findings and unpriced counts without a model', () => {
  const input=realStarterInput(), pack=createBuildPack(input);
  assert.equal(pack.manifest.model.included,false);assert.match(pack.manifest.model.reason!,/DRC_NOT_READY/);
  assert.deepEqual(JSON.parse(text(pack,'drc-report.json')),input.drcReport);
  assert.equal(pack.manifest.bom.unpricedPartCount,input.drcReport.bom.unpricedPartCount);assert.ok(pack.manifest.bom.unpricedPartCount>0);
  assert.equal(pack.manifest.bom.completePricing,false);assert.ok(!pack.files.some(f=>f.path.startsWith('model.')));
  assert.match(text(pack,'README.txt'),/do not wire/);
  const rows=text(pack,'bom.csv');assert.ok(rows.includes('"unknown",""'));
});
test('CW-E01 preserves original catalog/part bytes through a generated path mapping', () => {
  const input=fixture(),pack=createBuildPack(input),mapping=JSON.parse(text(pack,'source/part-map.json'));
  assert.equal(text(pack,'source/catalog.json'),input.catalog.catalogRawJson);
  for(const entry of mapping){const doc=input.catalog.partDocuments.find(d=>d.part_id===entry.partId)!;assert.equal(text(pack,entry.path),doc.raw_json);assert.equal(entry.sha256,sha256Hex(doc.raw_json));assert.match(entry.path,/^source\/parts\/\d{4}\.sc-part\.json$/);}
});
for(const bad of ['=1+2','+SUM(A1)','-cmd','@x',' \t=HYPERLINK("x")','\r=1','\n@x','\tplain','\u0000=1']){
  test(`CW-E01 spreadsheet formula prefix is escaped: ${JSON.stringify(bad)}`,()=>assert.ok(buildPackCsvCell(bad).startsWith('"\'')));
}
test('CW-E01 CSV quotes delimiters and multiline data while keeping unknown cost blank',()=>{
  assert.equal(buildPackCsvCell('a,"b"\nc'),'"a,""b""\nc"');assert.equal(buildPackCsvCell(null),'""');assert.equal(buildPackCsvCell(0),'"0"');
  const input=fixture();rewriteFixturePart(input,input.assembly.nodes[0].part_id,part=>{part.identity.name=' =HYPERLINK("x")';});
  assert.ok(text(createBuildPack(input),'bom.csv').includes('"\' =HYPERLINK(""x"")"'));
});
test('CW-E01 SVG escapes text and never infers endpoint pins or reviewed status',()=>{
  const input=fixture();input.assembly.identity.name='<script>alert(1)</script>';
  // Valid schema IDs stay constrained; attacker-controlled labels remain outside executable SVG.
  refreshFixture(input);const pack=createBuildPack(input),svg=text(pack,'wiring.svg');
  assert.ok(!svg.includes('<script>'));assert.match(svg,/UNREVIEWED/);assert.equal(pack.manifest.wiring.unresolvedNetCount,input.assembly.electrical_nets.length);
  for(const net of input.assembly.electrical_nets)for(const ep of net.endpoints)assert.ok(svg.includes(ep.node_id));
});
for(const change of ['part','catalog','assembly','drc','drcOptions'] as const){
  test(`CW-E01 refuses changed ${change} bytes or stale reports`,()=>{
    const input=fixture();
    if(change==='part')input.catalog.partDocuments[0].raw_json+=' ';
    if(change==='catalog')input.catalog.catalogRawJson+=' ';
    if(change==='assembly')input.assembly.identity.name+=' edit';
    if(change==='drc')input.drcReport.bom.knownSubtotalUsd=0;
    if(change==='drcOptions')input.drcOptions={claimedLoadAssertions:{mcuCountedTimes:2}};
    assert.throws(()=>createBuildPack(input));
  });
}
test('CW-E01 refuses source part and visual asset traversal even when re-pinned',()=>{
  const input=fixture(),index=JSON.parse(input.catalog.catalogRawJson);index.parts[0].path='parts/../outside.sc-part.json';input.catalog.catalogRawJson=JSON.stringify(index);input.catalog.catalogSha256=sha256Hex(input.catalog.catalogRawJson);
  assert.throws(()=>createBuildPack(input),/Unsafe.*path/);
  const visual=fixture();rewriteFixturePart(visual,visual.assembly.nodes[0].part_id,p=>{p.mechanical.visual_mesh.uri='assets/../private.glb';});assert.throws(()=>createBuildPack(visual),/Unsafe|schema/);
});
test('CW-E01 rejects duplicated catalog paths and raw JSON keys',()=>{
  const input=fixture(),index=JSON.parse(input.catalog.catalogRawJson);index.parts[1].path=index.parts[0].path;input.catalog.catalogRawJson=JSON.stringify(index);input.catalog.catalogSha256=sha256Hex(input.catalog.catalogRawJson);
  assert.throws(()=>createBuildPack(input),/duplicate.*path/);
  const duplicate=fixture();duplicate.catalog.catalogRawJson='{"schema_version":"seedcore.component-catalog.v1","parts":[],"parts":[]}';duplicate.catalog.catalogSha256=sha256Hex(duplicate.catalog.catalogRawJson);assert.throws(()=>createBuildPack(duplicate),/Duplicate JSON/);
});
test('CW-E01 oversized source is refused before parsing or archive allocation',()=>{
  const input=fixture();input.catalog.partDocuments[0].raw_json=' '.repeat(2*1024*1024+1);assert.throws(()=>createBuildPack(input),/2 MiB/);
});
test('CW-E01 external assets are reference-only and declared licenses grant no print rights',()=>{
  const pack=createBuildPack(fixture()),references=JSON.parse(text(pack,'asset-references.json'));
  assert.equal(references.physicalAcceptance,false);assert.equal(references.executionAuthority,'none');
  assert.ok(references.parts.every((p:any)=>p.assetBytesIncluded===false&&p.assetBytesVerified===false&&p.printReady===false&&p.rightsReview==='not_established'));
  assert.ok(pack.files.every(f=>!(/\.(glb|stl|step|bin|pem)$/i.test(f.path))));
});
test('CW-E01 invalid timing cannot hide behind blocked model readiness',()=>{
  const input=realStarterInput();input.options.timestepSeconds=Infinity;assert.throws(()=>createBuildPack(input),/Invalid compiler options/);
});
test('CW-E01 independent Python ZIP reader extracts only bounded STORE files with CRC and SHA agreement',()=>{
  const pack=createBuildPack(fixture()),dir=mkdtempSync(join(tmpdir(),'cw-e01-'));
  try{const file=join(dir,'pack.zip');writeFileSync(file,pack.bytes);
    const r=spawnSync('python3',['-c',`import csv,hashlib,io,json,pathlib,sys,zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
 assert z.testzip() is None
 infos=z.infolist(); assert len(infos)==len(set(z.namelist()))
 assert all(i.compress_type==zipfile.ZIP_STORED and i.file_size==i.compress_size and i.date_time==(1980,1,1,0,0,0) for i in infos)
 assert all(not pathlib.PurePosixPath(i.filename).is_absolute() and '..' not in pathlib.PurePosixPath(i.filename).parts for i in infos)
 m=json.loads(z.read('manifest.json')); assert not m['physicalAcceptance'] and m['executionAuthority']=='none'
 assert len(m['files'])==len(infos)-1
 for f in m['files']:
  b=z.read(f['path']); assert len(b)==f['bytes'] and hashlib.sha256(b).hexdigest()==f['sha256']
 rows=list(csv.reader(io.StringIO(z.read('bom.csv').decode('utf-8')))); assert len(rows)>1
`,file],{encoding:'utf8'});assert.equal(r.status,0,r.stderr);
  }finally{rmSync(dir,{recursive:true,force:true});}
});
