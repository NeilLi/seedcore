import assert from 'node:assert/strict';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {canonicalAssemblyString} from '@seedcore/contracts';

export async function exerciseMoments(page,root,passed) {
  const out=path.join(root,'artifacts/robotics/cw-s04');await mkdir(out,{recursive:true});
  const compiled=()=>page.waitForFunction(()=>document.querySelector('#sim-status')?.dataset.state==='compiled');
  const gestureCompiled=()=>page.waitForFunction(()=>document.querySelector('#moment-status')?.dataset.state==='compiled');
  const example=async()=>{await page.locator('#moments-tab').click();await page.locator('#moment-example').click();await page.locator('#moment-compile').click();await gestureCompiled();};
  await page.locator('#starter').click();await page.waitForFunction(()=>document.querySelectorAll('#sim-blocking li').length===9);
  assert.equal(await page.locator('#moment-example').isDisabled(),true);assert.equal(await page.locator('#moment-run').isDisabled(),true);
  await page.locator('#simulation-tab').focus();await page.keyboard.press('End');
  assert.equal(await page.locator('#moments-tab').getAttribute('aria-selected'),'true');
  await page.locator('#simulation-tab').click();
  passed('CW-S04 actual starter remains blocked; gesture entry grants no readiness exception');
  await page.locator('#simulation-reference').click();await compiled();await page.locator('#sim-mode').selectOption('position');
  await page.locator('#sim-rehearsal-preset').click();await compiled();await example();
  const raw=await page.locator('#moment-json').inputValue(),draft=JSON.parse(raw),digest=await page.locator('#moment-digest').textContent();
  assert.equal(draft.scope,'offline_simulation_only');assert.equal(draft.physicalAcceptance,false);assert.equal(draft.executionAuthority,'none');
  assert.equal(draft.tracks.length,2);assert.match(digest,/^[a-f0-9]{64}$/);
  const bad=structuredClone(draft);bad.tracks[0].maxVelocityRadS=0.001;
  await page.locator('#moment-json').fill(JSON.stringify(bad));await page.locator('#moment-compile').click();
  await page.waitForFunction(()=>document.querySelector('#moment-status')?.dataset.state==='rejected');
  assert.match(await page.locator('#moment-status').textContent(),/GESTURE_BOUNDS/);assert.equal(await page.locator('#moment-run').isDisabled(),true);
  await page.locator('#moment-json').fill(raw.replace('"schemaVersion":','"schemaVersion":0,"schemaVersion":'));
  await page.locator('#moment-compile').click();assert.match(await page.locator('#moment-status').textContent(),/Duplicate JSON key/);
  await page.locator('#moment-json').fill(raw);await page.locator('#moment-compile').click();await gestureCompiled();
  passed('CW-S04 strict JSON and interior derivative rejection; corrected draft recovers deterministically');

  // Bad declarative input is rejected inside the actual worker before engine fetch.
  const invalidWorker=await page.evaluate(async draft=>{
    const model={schemaVersion:'seedcore.cw-s01.model.v1',scope:'offline_simulation_only',physicalAcceptance:false,executionAuthority:'none',
      xml:document.querySelector('#sim-xml').value,manifest:JSON.parse(document.querySelector('#sim-manifest').textContent),modelDigest:document.querySelector('#sim-model-digest').textContent};
    const binding={...JSON.parse(document.querySelector('#sim-binding').textContent),modelDigest:model.modelDigest};
    const worker=new Worker('/cw-s02-worker.js',{type:'module'});
    try{return await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(Error('Invalid gesture worker timeout')),3000);
      worker.onmessage=({data:m})=>{if(m.type==='error'){clearTimeout(timer);resolve(m);}};
      worker.postMessage({protocol:'seedcore.cw-s02.worker.v1',type:'run',generation:1,model,binding,gesture:{...draft,network:true},gestureDigest:'0'.repeat(64)});
    });}finally{worker.terminate();}
  },draft);
  assert.equal(invalidWorker.code,'GESTURE_INVALID');assert.equal(invalidWorker.summary,undefined);
  passed('CW-S04 worker independently rejects undeclared network effects without deterministic-controller fallback');

  await page.locator('#moment-run').click();
  await page.waitForFunction(()=>document.querySelector('#moment-status')?.dataset.state==='completed');
  assert.match(await page.locator('#moment-result').textContent(),/completed_simulation_capture.*120\/120/);
  const downloadPromise=page.waitForEvent('download');await page.locator('#moment-export').click();const download=await downloadPromise;
  assert.equal(download.suggestedFilename(),'gesture.cw-s04.replay.json');await download.saveAs(path.join(out,'browser-replay.json'));
  const replayRaw=await readFile(path.join(out,'browser-replay.json'),'utf8'),replay=JSON.parse(replayRaw);
  const nodeCases=JSON.parse(await readFile(path.join(out,'models/cases.json'),'utf8'));
  const expected=nodeCases.cases.find(c=>c.name==='studio-reference').replay;
  assert.equal(replay.summary.traceDigest,expected.summary.traceDigest);
  assert.equal(replay.samples.length,120);assert.equal(replay.summary.policyDecimation,1);
  assert.equal(replay.physicalAcceptance,false);assert.equal(replay.executionAuthority,'none');
  passed('CW-S04 Chrome worker runs 120 per-substep gesture controls with the same physics trace as Node Wasm');

  let fetches=0;const observe=()=>{fetches++;};page.on('request',observe);
  await page.locator('#moment-tick').fill('59');await page.locator('#moment-tick').dispatchEvent('input');
  assert.match(await page.locator('#moment-frame').textContent(),/tick 60/);assert.match(await page.locator('#moment-led').textContent(),/#d19b42/);
  await page.locator('#moment-tick').fill('119');await page.locator('#moment-tick').dispatchEvent('input');
  assert.match(await page.locator('#moment-frame').textContent(),/tick 120/);assert.equal(fetches,0);page.off('request',observe);
  assert.equal(await page.locator('#moment-status').getAttribute('data-state'),'completed');
  passed('CW-S04 read-only scrub exposes target versus observed joints and virtual LED without requests or resimulation');
  await page.screenshot({path:path.join(out,'moments-inspector.png'),fullPage:true});

  await page.locator('#moments details').last().locator('summary').click();
  await page.locator('#moment-replay-json').fill(replayRaw);await page.locator('#moment-inspect-replay').click();
  assert.equal(await page.locator('#moment-status').getAttribute('data-state'),'replayed');
  const corrupted=structuredClone(replay);corrupted.samples[4].qpos[0]+=0.1;
  await page.locator('#moment-replay-json').fill(JSON.stringify(corrupted));await page.locator('#moment-inspect-replay').click();
  assert.match(await page.locator('#moment-status').textContent(),/Replay rejected/);assert.equal(await page.locator('#moment-export').isDisabled(),true);
  // Recompute every embedded digest: only the independent original-capture pin
  // can detect a self-consistent rewrite of intermediate observed state.
  const hash=value=>createHash('sha256').update(canonicalAssemblyString(value)).digest('hex');
  corrupted.summary.traceDigest=hash({modelDigest:corrupted.summary.attempt.modelDigest,timestepSeconds:corrupted.summary.timestepSeconds,
    policyDecimation:corrupted.summary.policyDecimation,samples:corrupted.samples.map(({monotonicMs:_wall,...physics})=>physics)});
  const {replayDigest:_old,...payload}=corrupted;corrupted.replayDigest=hash(payload);
  await page.locator('#moment-replay-json').fill(JSON.stringify(corrupted));await page.locator('#moment-inspect-replay').click();
  assert.match(await page.locator('#moment-status').textContent(),/independently retained original attempt/);
  assert.equal(await page.locator('#moment-export').isDisabled(),true);
  await page.locator('#moment-replay-json').fill(replayRaw);await page.locator('#moment-inspect-replay').click();
  assert.equal(await page.locator('#moment-status').getAttribute('data-state'),'replayed');
  passed('CW-S04 independently retained capture pin rejects rewritten observations despite recalculated trace and replay hashes');
  await page.locator('#moment-json').fill(raw.replace(draft.name,'Edited gesture'));
  assert.equal(await page.locator('#moment-digest').textContent(),'—');assert.equal(await page.locator('#moment-tick').isDisabled(),true);
  await page.locator('#moment-compile').click();await gestureCompiled();assert.notEqual(await page.locator('#moment-digest').textContent(),digest);
  passed('CW-S04 imports require current independent attempt identity; tampering rejects and edits clear compilation/replay');

  // Stop after real captured progress, not merely during Wasm startup.
  await page.evaluate(()=>{
    const node=document.querySelector('#moment-status');
    const observer=new MutationObserver(()=>{
      if(node.dataset.state==='running' && /(?:[1-9][0-9]+)\/120/.test(node.textContent)){
        observer.disconnect();document.querySelector('#moment-stop').click();
      }
    });observer.observe(node,{childList:true,attributes:true,subtree:true});
  });
  await page.locator('#moment-run').click();
  await page.waitForFunction(()=>document.querySelector('#moment-status')?.dataset.state==='interrupted');
  assert.match(await page.locator('#moment-result').textContent(),/interrupted_simulation_capture/);
  assert.equal(await page.locator('#moment-export').isDisabled(),false);
  passed('CW-S04 operator stop retains partial capture and cannot display completed outcome');

  for(const action of ['gesture','parameters','draft','undo','redo','hidden']){
    await page.locator('#simulation-tab').click();await page.locator('#sim-rehearsal-preset').click();await compiled();await example();
    let release,heldResolve;const held=new Promise(r=>heldResolve=r),gate=new Promise(r=>release=r);
    const hold=async route=>{heldResolve();await gate;try{await route.continue();}catch{}};
    await page.route('**/mujoco.wasm',hold);
    try{
      await page.locator('#moment-run').click();await held;
      if(action==='gesture')await page.locator('#moment-json').fill(raw);
      else if(action==='parameters'){await page.locator('#simulation-tab').click();await page.locator('#sim-kp').fill('2');await page.locator('#moments-tab').click();}
      else if(action==='draft'){
        await page.locator('#inspect-tab').click();await page.locator('#name').fill('CW-S04 edited draft');await page.locator('#rename').click();await page.locator('#moments-tab').click();
      } else if(action==='undo'||action==='redo')await page.locator('#'+action).click();
      else await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));delete document.hidden;});
      release();await page.unroute('**/mujoco.wasm',hold);await page.waitForTimeout(100);
      assert.notEqual(await page.locator('#moment-status').getAttribute('data-state'),'completed');
      assert.equal(await page.locator('#moment-export').isDisabled(),true);
    }finally{release();await page.unroute('**/mujoco.wasm',hold);}
  }
  passed('CW-S04 gesture/model/draft/undo/redo/hidden startup races cannot restore stale replay or resume motion');
  await page.locator('#simulation-tab').click();await page.locator('#sim-rehearsal-preset').click();await compiled();await example();
  await writeFile(path.join(out,'browser-verification.json'),JSON.stringify({scope:'offline_simulation_only',physicalAcceptance:false,executionAuthority:'none',
    status:'checks_passed',physicsTraceDigest:replay.summary.traceDigest,checks:9},null,2)+'\n');
}
