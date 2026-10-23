import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';

export async function exerciseCwS02WorkerBoundary(page, root, passed) {
  const out=path.join(root,'artifacts/robotics/cw-s02');
  const cases=JSON.parse(await readFile(path.join(out,'models/cases.json'),'utf8')).models;
  const browser=await page.evaluate(async models=>{
    const worker=new Worker('/cw-s02-worker.js',{type:'module'});
    const results=[],started=performance.now();
    try {
      for (const [index,model] of models.entries()) {
        const manifest=model.manifest;
        const result=await new Promise((resolve,reject)=>{
          const timeout=setTimeout(()=>reject(new Error('Worker parity run timed out')),15000);
          worker.onmessage=({data:m})=>{
            if(m.generation!==index+1)return;
            if(m.type==='complete'||m.type==='error') {clearTimeout(timeout);m.type==='complete'?resolve(m):reject(new Error(m.error));}
          };
          worker.onerror=e=>{clearTimeout(timeout);reject(new Error(e.message));};
          worker.postMessage({protocol:'seedcore.cw-s02.worker.v1',type:'run',generation:index+1,model,
            binding:{modelDigest:model.modelDigest,assemblyDigest:manifest.assemblyDigest,catalogDigest:manifest.catalogDigest,drcDigest:manifest.drcDigest,revisionDigest:manifest.assemblyDigest,authorityEpoch:1},totalSubsteps:120,policyDecimation:10});
        });
        results.push(result);
      }
      return {results,elapsedMs:performance.now()-started,userAgent:navigator.userAgent,platform:navigator.platform,hardwareConcurrency:navigator.hardwareConcurrency};
    }finally{worker.terminate();}
  },cases.map(c=>c.model));
  let maxError=0;
  const compare=(actual,expected)=>{
    assert.equal(actual.length,expected.length);
    for(let i=0;i<expected.length;i++) {
      assert.equal(Number.isFinite(actual[i]),true);
      const error=Math.abs(actual[i]-expected[i]);maxError=Math.max(maxError,error);assert.ok(error<=1e-12,`Browser/native-reference error ${error}`);
    }
  };
  for(const [index,c] of cases.entries()) {
    const actual=browser.results[index];
    assert.equal(actual.summary.status,'completed');assert.equal(actual.samples.length,120);
    assert.equal(actual.summary.traceDigest,c.rollout.summary.traceDigest);
    for(let k=0;k<120;k++) for(const field of ['qpos','qvel','qfrcActuator','xpos']) compare(actual.samples[k][field],c.rollout.samples[k][field]);
  }
  await writeFile(path.join(out,'browser-parity.json'),JSON.stringify({...browser,models:cases.map(c=>c.name),maxAbsoluteError:maxError,substepsPerModel:120,scope:'offline_simulation_only',physicalAcceptance:false},null,2)+'\n');
  passed('CW-S02 CSP static-invoker browser worker matches all 14 uninterrupted 120-step parity references');

  const model=cases.find(c=>c.name==='studio-reference-position').model;
  // Single-thread support must also run on a top-level page without COOP/COEP.
  const unisolated=await page.context().newPage();
  try {
    const base=new URL('/',page.url()).href;
    await unisolated.route(base,async route=>{
      const response=await route.fetch(),headers={...response.headers()};
      delete headers['cross-origin-opener-policy'];delete headers['cross-origin-embedder-policy'];
      await route.fulfill({response,headers});
    });
    await unisolated.goto(base);
    assert.equal(await unisolated.evaluate(()=>crossOriginIsolated),false);
    const result=await unisolated.evaluate(model=>new Promise((resolve,reject)=>{
      const worker=new Worker('/cw-s02-worker.js',{type:'module'}),m=model.manifest;
      const timeout=setTimeout(()=>{worker.terminate();reject(new Error('Single-thread fallback timed out'));},15000);
      worker.onmessage=({data:r})=>{if(r.type==='complete'||r.type==='error'){clearTimeout(timeout);worker.terminate();r.type==='complete'?resolve(r):reject(new Error(r.error));}};
      worker.onerror=e=>{clearTimeout(timeout);worker.terminate();reject(new Error(e.message));};
      worker.postMessage({protocol:'seedcore.cw-s02.worker.v1',type:'run',generation:1,model,binding:{modelDigest:model.modelDigest,assemblyDigest:m.assemblyDigest,catalogDigest:m.catalogDigest,drcDigest:m.drcDigest,revisionDigest:m.assemblyDigest,authorityEpoch:1},totalSubsteps:120,policyDecimation:10});
    }),model);
    assert.equal(result.environment.crossOriginIsolated,false);
    assert.equal(result.environment.sharedArrayBufferAvailable,false);
    assert.equal(result.summary.traceDigest,cases.find(c=>c.model.modelDigest===model.modelDigest).rollout.summary.traceDigest);
  }finally{await unisolated.close();}
  passed('CW-S02 explicit single-thread profile runs without cross-origin isolation or SharedArrayBuffer');

  let release,heldResolve;
  const held=new Promise(r=>{heldResolve=r;}),gate=new Promise(r=>{release=r;});let first=true;
  const handler=async route=>{
    if(first){first=false;heldResolve();await gate;try{await route.abort('failed');}catch{}}else await route.continue();
  };
  await page.route('**/mujoco.wasm',handler);
  const start=gen=>page.evaluate(({model,gen})=>{
    if(!window.__cwRaceWorker){window.__cwRaceWorker=new Worker('/cw-s02-worker.js',{type:'module'});window.__cwRaceMessages=[];window.__cwRaceWorker.onmessage=e=>window.__cwRaceMessages.push(e.data);}
    const m=model.manifest;
    window.__cwRaceWorker.postMessage({protocol:'seedcore.cw-s02.worker.v1',type:'run',generation:gen,model,binding:{modelDigest:model.modelDigest,assemblyDigest:m.assemblyDigest,catalogDigest:m.catalogDigest,drcDigest:m.drcDigest,revisionDigest:m.assemblyDigest,authorityEpoch:1},totalSubsteps:60,policyDecimation:10});
  },{model,gen});
  try {
    await start(1);await held;await start(2);await start(2);release();
    await page.waitForFunction(()=>window.__cwRaceMessages?.some(m=>m.generation===2&&m.type==='complete'),null,{timeout:15000});
    const messages=await page.evaluate(()=>window.__cwRaceMessages);
    assert.equal(messages.filter(m=>m.generation===2&&m.type==='ready').length,1);
    assert.equal(messages.filter(m=>m.generation===2&&m.type==='error').length,0);
    passed('CW-S02 stale startup failures and duplicate generation requests cannot clean up or restart a newer worker run');
  }finally{release();await page.unroute('**/mujoco.wasm',handler);await page.evaluate(()=>{window.__cwRaceWorker?.terminate();delete window.__cwRaceWorker;});}

  // Interrupt startup before MjModel/MjData exist, not only between physics steps.
  for (const type of ['hidden','revoke']) {
    let go,ready;
    const pending=new Promise(r=>{ready=r;}),wait=new Promise(r=>{go=r;});
    const hold=async route=>{ready();await wait;try{await route.continue();}catch{}};
    await page.route('**/mujoco.wasm',hold);
    try {
      await start(type==='hidden'?3:4);await pending;
      await page.evaluate(({type,generation})=>window.__cwRaceWorker.postMessage({protocol:'seedcore.cw-s02.worker.v1',type,generation}),{type,generation:type==='hidden'?3:4});
      await page.waitForFunction(gen=>window.__cwRaceMessages.some(m=>m.generation===gen&&m.type==='error'),type==='hidden'?3:4);
      go();await page.waitForTimeout(50);
      assert.equal(await page.evaluate(gen=>window.__cwRaceMessages.filter(m=>m.generation===gen&&['ready','complete'].includes(m.type)).length,type==='hidden'?3:4),0);
    }finally{go();await page.unroute('**/mujoco.wasm',hold);await page.evaluate(()=>{window.__cwRaceWorker?.terminate();delete window.__cwRaceWorker;});}
  }
  passed('CW-S02 hidden/revoked startup cannot resurrect a worker after asynchronous loading');
}
