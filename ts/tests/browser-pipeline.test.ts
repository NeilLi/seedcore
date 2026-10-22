import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {Worker} from 'node:worker_threads';
import {createRequire} from 'node:module';
import {setImmediate} from 'node:timers/promises';
import {createHash} from 'node:crypto';
import {sharedFrames,publishFrame,acquireLatestFrame,releaseFrame,TransferFramePool,validateLabConfig,frameFloats,type LabConfig} from '../packages/wasm-sim-bridge/src/frameTransport.js';
import {FixedTickClock} from '../packages/wasm-sim-bridge/src/labTiming.js';
import {PlanarLab,writePlanarMatrices,LINK_LENGTHS} from '../packages/wasm-sim-bridge/src/planarLab.js';
import {readPinnedPhysics} from '../packages/wasm-sim-bridge/src/physicsAsset.js';
const config:LabConfig={mode:'shared',chains:2,hz:500,seconds:2};
const bytes=readFileSync(new URL('../../apps/mini-robot-simulator/mini-physics.wasm',import.meta.url));
test('pinned physics: streaming size bounds and build SHA precede Wasm compilation',async()=>{
  const pin=createHash('sha256').update(new Uint8Array([1,2,3])).digest('hex');
  assert.deepEqual(await readPinnedPhysics(new Response(new Uint8Array([1,2,3])),3,pin),new Uint8Array([1,2,3]));
  await assert.rejects(readPinnedPhysics(new Response(new Uint8Array([1,2,3,4])),3,pin),/exceeds pin/);
  await assert.rejects(readPinnedPhysics(new Response(new Uint8Array([1])),3,pin),/count mismatch/);
  await assert.rejects(readPinnedPhysics(new Response(new Uint8Array([1,2,4])),3,pin),/SHA-256 mismatch/);
  await assert.rejects(readPinnedPhysics(new Response('',{status:503}),3,pin),/fetch failed/);
  await assert.rejects(readPinnedPhysics(new Response(''),2**30,pin),/Invalid physics build pin/);
});
test('visual transport: strict resource bounds and exact shared layout',()=>{
  for(const bad of [{...config,chains:257},{...config,chains:1.5},{...config,hz:120},{...config,seconds:31},{...config,mode:'hardware'},{...config,token:{}}])assert.throws(()=>validateLabConfig(bad));
  assert.equal(frameFloats({...config,mode:'gpu'}),8);
  assert.throws(()=>sharedFrames(config,new SharedArrayBuffer(4)));
});
test('visual transport: renderer-owned slots never get overwritten, even under saturation',()=>{
  const f=sharedFrames(config),held:number[]=[];
  for(let sequence=1;sequence<=3;sequence++){assert.equal(publishFrame(f,sequence,sequence,v=>v.fill(sequence)),true);held.push(acquireLatestFrame(f,sequence-1));}
  assert.equal(publishFrame(f,4,4,v=>v.fill(4)),false);
  for(let i=0;i<held.length;i++)assert.equal(f.views[held[i]].every(v=>v===i+1),true);
  releaseFrame(f,held[1]);assert.equal(publishFrame(f,5,5,v=>v.fill(5)),true);
  assert.equal(f.views[held[0]][0],1);assert.equal(f.views[held[2]][0],3);
  assert.throws(()=>releaseFrame(f,held[1]));
});
test('visual transport: publication errors release ownership; visual drops are bounded',()=>{
  const f=sharedFrames(config);assert.throws(()=>publishFrame(f,1,0,()=>{throw Error('pack failure');}));
  for(let i=1;i<100;i++)publishFrame(f,i,i,v=>v.fill(i));
  const slot=acquireLatestFrame(f,0);assert.equal(f.views[slot][0],99);releaseFrame(f,slot);
  assert.equal(acquireLatestFrame(f,99),-1);assert.throws(()=>publishFrame(f,2**31,0,()=>{}));
});
test('visual transport: real producer worker stress never exposes a torn snapshot',{timeout:10000},async()=>{
  const f=sharedFrames({...config,chains:128});
  const url=new URL('../packages/wasm-sim-bridge/dist/frameTransport.js',import.meta.url).href;
  const worker=new Worker(`const {parentPort,workerData}=require('node:worker_threads');(async()=>{const {sharedFrames,publishFrame}=await import(workerData.url);const f=sharedFrames(workerData.config,workerData.buffer);for(let seq=1;seq<=12000;seq++)publishFrame(f,seq,seq,v=>{for(let i=0;i<v.length;i++)v[i]=seq;});parentPort.postMessage('done');})().catch(e=>{throw e;});`,{eval:true,workerData:{url,config:{...config,chains:128},buffer:f.buffer}});
  let done=false,error:unknown;worker.on('message',()=>{done=true;});worker.on('error',e=>{error=e;done=true;});let last=0,count=0;
  try {
    while(!done||last<12000) {
      if(error)throw error;const slot=acquireLatestFrame(f,last);
      if(slot>=0){const seq=Atomics.load(f.header,slot*4+1);assert.equal(f.views[slot].every(v=>v===seq),true);last=seq;count++;releaseFrame(f,slot);}
      await setImmediate();
    }
    assert.ok(count>0);assert.equal(last,12000);
  }finally{await worker.terminate();}
});
test('visual transport: transferable loans detach, recycle and reject stale/duplicate returns',()=>{
  const pool=new TransferFramePool({...config,mode:'transfer'}),loans=[pool.take(1)!,pool.take(2)!,pool.take(3)!];assert.equal(pool.take(4),undefined);
  const sent=structuredClone(loans[0],{transfer:[loans[0].buffer]});assert.equal(loans[0].buffer.byteLength,0);
  assert.throws(()=>pool.recycle(sent.id,99,sent.buffer));assert.throws(()=>pool.recycle(sent.id,1,new ArrayBuffer(4)));
  pool.recycle(sent.id,1,sent.buffer);assert.throws(()=>pool.recycle(sent.id,1,sent.buffer));assert.equal(pool.take(4)!.buffer.byteLength,frameFloats(config)*4);
});
test('fixed clock: integer simulation time, bounded catch-up and explicit stall fencing',()=>{
  const clock=new FixedTickClock(1000,2,10);assert.equal(clock.due(14,0),4);assert.equal(clock.due(30,4),8);
  assert.equal(clock.due(30,12),8);assert.equal(clock.due(30,20),0);
  assert.throws(()=>clock.due(29,20));assert.throws(()=>clock.due(400,20));
  const lag=new FixedTickClock(500,2,0);assert.equal(lag.due(200,0),8);assert.throws(()=>lag.due(267,8));
});
test('planar fixture: transport mode leaves identical fixed-tick Wasm state',()=>{
  const a=new PlanarLab(bytes,2,500),b=new PlanarLab(bytes,2,500),m=new Float32Array(96),q=new Float32Array(8);
  for(let tick=0;tick<1000;tick++){a.step(tick);b.step(tick);if(tick%3===0)a.pack(m,false);if(tick%7===0)b.pack(q,true);}
  assert.deepEqual(a.state,b.state);assert.ok(a.state.every(Number.isFinite));assert.throws(()=>a.pack(new Float32Array(1),true));
});
test('display FK: matrices match independent Wasm ABI2 FK endpoints',()=>{
  const require=createRequire(import.meta.url),api=require('../../apps/mini-robot-simulator/tree-physics-wasm.js').create(bytes,{});
  const model={numLinks:3,gravity:9.81,links:LINK_LENGTHS.map(length=>({length,mass:.05,com:length/2,inertia:.05*length*length/12,damping:.02}))};
  for(const q of [[0,0,0],[.5,-.8,1.2],[-2,.7,-1.3]]) {
    const out=new Float32Array(48);writePlanarMatrices(q,0,out);const fk=api.forward(model,q);
    for(let j=0;j<3;j++) {assert.ok(Math.abs(out[j*16+12]+out[j*16]/2-fk.joints[j].x)<2e-8);assert.ok(Math.abs(out[j*16+13]+out[j*16+1]/2-fk.joints[j].y)<2e-8);}
  }
});
