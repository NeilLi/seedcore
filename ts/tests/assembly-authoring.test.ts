import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {canonicalAssemblyString, parseAssemblyText, parseStrictJson, type RobotAssembly} from '../packages/contracts/src/index.js';
import {AssemblyStore, sha256Text} from '../packages/robot-canvas/src/store.js';
import {decodeProxy,readBounded,prepareProxyScene} from '../packages/robot-canvas/src/assets.js';
const text = readFileSync(new URL('../../packages/component-registry/assemblies/tabletop-starter.sc-assembly.json',import.meta.url),'utf8');
const starter = () => parseAssemblyText(text);
const rename = (name:string) => {const data=starter();data.identity.name=name;return JSON.stringify(data);};
const ready = async (data:RobotAssembly) => ({name:data.identity.name});
const deferred = <T>()=>{let resolve!:(value:T)=>void, reject!:(error:Error)=>void;const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const tick = () => new Promise<void>(resolve=>setImmediate(resolve));

test('CW-ASM-02: raw v2 starter matches frozen Python/JS digest',async()=>{
  assert.equal(starter().identity.version,'0.2.0');
  assert.equal(await sha256Text(canonicalAssemblyString(starter())),'2550d184c44a064c6ad6a2245a08f430f257c40ca8f3627e73eeb3fedd452acb');
  assert.deepEqual(parseAssemblyText(canonicalAssemblyString(starter())),starter());
});
for(const raw of ['{"a":1,"a":2}','{"nested":{"node_id":1,"node\\u005fid":2}}','{"a":1,"\\u0061":2}','{"__proto__":0,"__proto__":1}']) test(`reject duplicate keys: ${raw}`,()=>assert.throws(()=>parseStrictJson(raw),/Duplicate JSON key/));
test('keys are local to objects; prototype keys cannot mutate prototypes',()=>{
  const data=parseStrictJson('{"a":{"key":1},"b":{"key":2},"__proto__":{"polluted":true}}') as any;
  assert.equal(Object.getPrototypeOf(data),null); assert.equal(({} as any).polluted,undefined);
  assert.equal(data.__proto__.polluted,true);
});
for(const raw of ['{"a":1,}','[1,]','01','+1','NaN','1e999','9007199254740992','{"a" 1}','true false','"\\x22"','"unclosed','\ufeff{}']) test(`reject malformed/non-profile JSON ${raw}`,()=>assert.throws(()=>parseStrictJson(raw)));
test('bounds and historical versions fail before admission',()=>{
  assert.throws(()=>parseStrictJson('['.repeat(34)+'0'+']'.repeat(34)),/bound/);
  assert.throws(()=>parseStrictJson('"'+'界'.repeat(90000)+'"'),/bytes/);
  assert.throws(()=>parseAssemblyText(text.replace('seedcore.assembly.v2','seedcore.assembly.v1')),/Historical/);
  assert.throws(()=>parseAssemblyText(text.replace('"schema_version":','"schema_version":"fake","schema_version":')),/Duplicate/);
});
test('input and returned revisions are deeply immutable; selections do not create revisions',async()=>{
  let input:RobotAssembly|undefined; const store=new AssemblyStore(async data=>{input=data; return ready(data);});
  assert.equal(await store.loadText(text),'committed');const before=store.getState();
  input!.identity.name='mutated'; assert.notEqual(store.getState().current!.assembly.identity.name,'mutated');
  assert.equal(Object.isFrozen(before.current!.assembly.identity),true);
  assert.equal(Reflect.set(before.current!.assembly.identity,'name','mutated'),false);
  store.select({kind:'node',id:'servo_0'});assert.equal(store.getState().current!.revisionDigest,before.current!.revisionDigest);
  assert.equal(store.getState().authorityEpoch,before.authorityEpoch);
  assert.throws(()=>store.select({kind:'edge',id:'missing'}),/Unknown/);
  assert.equal(store.getState().current!.selection!.id,'servo_0');
});
test('edits, undo/redo, branch truncation and authority invalidation are deterministic',async()=>{
  const store=new AssemblyStore(ready);await store.loadText(text);store.select({kind:'node',id:'servo_0'});
  const first=store.getState().current!;await store.edit(draft=>{draft.identity.name='changed';});
  const second=store.getState().current!;assert.equal(second.parentDigest,first.revisionDigest);assert.equal(second.selection!.id,'servo_0');
  store.undo();assert.equal(store.getState().current!.revisionDigest,first.revisionDigest);assert.equal(store.getState().authorityEpoch,3);
  store.redo();assert.equal(store.getState().current!.revisionDigest,second.revisionDigest);assert.equal(store.getState().authorityEpoch,4);
  store.undo();await store.edit(draft=>{draft.identity.name=first.assembly.identity.name;});
  assert.equal(store.getState().current!.assemblyDigest,first.assemblyDigest);assert.notEqual(store.getState().current!.revisionDigest,first.revisionDigest);
  assert.equal(store.getState().current!.sequence,3);assert.equal(store.getState().canRedo,false);assert.equal(store.getState().admission,null);
  const again=new AssemblyStore(ready);await again.loadText(text);await again.edit(draft=>{draft.identity.name='changed';});assert.equal(again.getState().current!.revisionDigest,second.revisionDigest);
});
test('invalid graph edit is atomic and does not advance authority or history',async()=>{
  const store=new AssemblyStore(ready);await store.loadText(text);const before=store.getState();
  assert.equal(await store.edit(draft=>{draft.nodes[0].node_id='wrong';}),'rejected');
  assert.equal(store.getState().current,before.current);assert.equal(store.getState().authorityEpoch,before.authorityEpoch);assert.equal(store.getState().canUndo,false);
});
test('late success from an abort-ignoring loader cannot overwrite a newer revision',async()=>{
  const slow=deferred<string>(),store=new AssemblyStore(ready);await store.loadText(text);
  const pending=store.loadFrom(()=>slow.promise);await tick();assert.equal(store.getState().loading,true);
  await store.loadText(rename('newer'));const accepted=store.getState().current;
  assert.equal(await pending,'stale');slow.resolve(rename('older'));await tick();
  assert.equal(store.getState().current,accepted);assert.equal(store.getState().error,null);
});
test('late failures do not overwrite newer success; newest invalid intent fences old success',async()=>{
  const slow=deferred<string>(),store=new AssemblyStore(ready);await store.loadText(text);
  const pending=store.loadFrom(()=>slow.promise);await store.loadText(rename('latest'));slow.reject(new Error('late failure'));assert.equal(await pending,'stale');await tick();assert.equal(store.getState().error,null);
  const slow2=deferred<string>();const pending2=store.loadFrom(()=>slow2.promise);
  assert.equal(await store.loadText('{"a":1,"a":2}'),'rejected');const error=store.getState().error;
  slow2.resolve(rename('must not win'));await pending2;await tick();assert.equal(store.getState().error,error);assert.equal(store.getState().current!.assembly.identity.name,'latest');
});
test('late asset preparation, undo and disposal fence stale commits',async()=>{
  const slow=deferred<{name:string}>();const store=new AssemblyStore(async data=>data.identity.name==='slow'?slow.promise:ready(data));
  await store.loadText(text);await store.loadText(rename('new'));const pending=store.loadText(rename('slow'));await tick();store.undo();slow.resolve({name:'old scene'});
  assert.equal(await pending,'stale');assert.equal(store.getState().current!.assembly.identity.name,starter().identity.name);
  const load=deferred<string>();const after=store.loadFrom(()=>load.promise);store.dispose();load.resolve(rename('disposed'));assert.equal(await after,'stale');
});
test('asset failure and timeout retain the previous scene and revision',async()=>{
  const store=new AssemblyStore(async data=>{if(data.identity.name==='bad') throw new Error('mesh failed');if(data.identity.name==='hang') return new Promise(()=>{});return ready(data);},{timeoutMs:15});
  await store.loadText(text);const before=store.getState().current;
  assert.equal(await store.loadText(rename('bad')),'rejected');assert.equal(store.getState().current,before);assert.match(store.getState().error!,/mesh failed/);
  assert.equal(await store.loadText(rename('hang')),'rejected');assert.equal(store.getState().current,before);assert.match(store.getState().error!,/timed out/);
});
test('history is bounded and subscribers cannot turn accepted revisions into failures',async()=>{
  const store=new AssemblyStore(ready,{historyLimit:2});store.subscribe(()=>{});await store.loadText(text);
  store.subscribe(()=>{if(store.getState().current!.sequence>1) throw new Error('view failed');});
  await store.loadText(rename('two'));await store.loadText(rename('three'));store.undo();assert.equal(store.getState().current!.sequence,2);assert.equal(store.getState().canUndo,false);
  const bounded=new AssemblyStore(ready,{byteLimit:100});assert.equal(await bounded.loadText(text),'rejected');assert.equal(bounded.getState().current,null);
});
test('unknown token and hardware fields cannot enter persisted assembly',async()=>{
  const data=starter() as any;data.execution_token={allow:true};const store=new AssemblyStore(ready);
  assert.equal(await store.loadText(JSON.stringify(data)),'rejected');assert.equal(store.getState().admission,null);
});
test('bounded response reader and GLB parser reject oversized/truncated assets',async()=>{
  await assert.rejects(()=>readBounded(new Response('12345'),4),/bound/);
  assert.throws(()=>decodeProxy(new Uint8Array(20)),/Truncated/);
  const raw=readFileSync(new URL('../../packages/component-registry/assets/feetech-sts3215-draft.glb',import.meta.url));
  const geometry=decodeProxy(new Uint8Array(raw));assert.equal(geometry.positions.length,24);assert.equal(geometry.indices.length,36);
  const damaged=new Uint8Array(raw);damaged[0]=0;assert.throws(()=>decodeProxy(damaged),/header/);
});

test('ABA undo/redo returning to the same content still fences pending results',async()=>{
  const slow=deferred<{name:string}>();
  const store=new AssemblyStore(async data=>data.identity.name==='pending'?slow.promise:ready(data));
  await store.loadText(text);await store.loadText(rename('second'));const second=store.getState().current!.revisionDigest;
  const pending=store.loadText(rename('pending'));await tick();store.undo();store.redo();
  assert.equal(store.getState().current!.revisionDigest,second);slow.resolve({name:'obsolete'});assert.equal(await pending,'stale');
  assert.equal(store.getState().current!.revisionDigest,second);
});
test('non-JSON scene objects cannot enter immutable history',async()=>{
  const store=new AssemblyStore(async()=>new Map([['mutable','value']]));
  assert.equal(await store.loadText(text),'rejected');assert.equal(store.getState().current,null);
  assert.match(store.getState().error!,/plain JSON/);
  assert.throws(()=>new AssemblyStore(ready,{historyLimit:0}),/bounds/);
});


test('non-2xx response bodies retain bounded reading without reconstructing a Response',async()=>{
  await assert.rejects(()=>readBounded(new Response('denied',{status:422}),4096),/422/);
  assert.equal(new TextDecoder().decode(await readBounded(new Response('denied',{status:422}),4096,{allowErrorStatus:true})),'denied');
  await assert.rejects(()=>readBounded(new Response('x'.repeat(4097),{status:503}),4096,{allowErrorStatus:true}),/byte bound/);
});
test('catalog rejection reports status and handles empty or oversized error bodies',async()=>{
  const original=globalThis.fetch;
  try {
    for(const [body,expected] of [['denied',/HTTP 422.*denied/],[null,/HTTP 422/],['x'.repeat(4097),/byte bound/]] as const) {
      globalThis.fetch=async()=>new Response(body,{status:422});
      await assert.rejects(()=>prepareProxyScene(starter(),new AbortController().signal),expected);
    }
  } finally {globalThis.fetch=original;}
});
