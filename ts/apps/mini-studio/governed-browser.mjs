// Actual local PDP, service signer, Rust verification and native MuJoCo. No mocked allows.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';
const root=fileURLToPath(new URL('../../../',import.meta.url)),out=path.join(root,'artifacts/robotics/cw-g01/native');await mkdir(out,{recursive:true});
const port=process.env.SEEDCORE_G01_TEST_PORT||'8771',base=`http://127.0.0.1:${port}`;
const python=process.env.SEEDCORE_TEST_PYTHON||path.join(root,'.venv/bin/python');
const server=spawn(python,['tools/robotics/serve-cw-g01-test.py','--port',port,'--source','artifacts/robotics/cw-g01/endpoint-source.json'],{cwd:root,stdio:['ignore','pipe','pipe']});
let log='',browser;server.stdout.on('data',d=>{log+=d});server.stderr.on('data',d=>{log+=d});
const report={scope:'local_simulation_only',physicalAcceptance:false,fixtureContext:true,checks:[],errors:[]};
const passed=name=>{report.checks.push(name);console.log(`PASS ${name}`)};
try{
  for(let i=0;i<120;i++){if(server.exitCode!==null)throw Error(log);try{if((await fetch(`${base}/api/cw-g01/profile`)).ok)break;}catch{}if(i===119)throw Error(log);await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,channel:process.env.SEEDCORE_BROWSER_CHANNEL||'chrome'});
  const page=await browser.newPage({viewport:{width:1440,height:1100},acceptDownloads:true});
  page.on('pageerror',e=>report.errors.push(e.message));
  await page.goto(base);await page.waitForFunction(()=>document.querySelector('#viewport')?.dataset.meshState==='verified');
  assert.equal(await page.locator('#gov-admit').isDisabled(),true);
  await page.locator('#simulation-tab').click();await page.locator('#simulation-reference').click();
  await page.waitForFunction(()=>document.querySelector('#sim-status')?.dataset.state==='compiled');
  await page.locator('#sim-mode').selectOption('position');await page.locator('#sim-rehearsal-preset').click();
  await page.waitForFunction(()=>document.querySelector('#sim-status')?.dataset.state==='compiled');
  const example=async()=>{await page.locator('#moments-tab').click();await page.locator('#moment-example').click();await page.locator('#moment-compile').click();await page.waitForFunction(()=>document.querySelector('#moment-status')?.dataset.state==='compiled');};
  await example();await page.waitForFunction(()=>!document.querySelector('#gov-admit')?.disabled);
  const assembly=await page.locator('#content-digest').textContent(), revision=await page.locator('#revision').textContent();
  const draft=await page.locator('#moment-json').inputValue();
  await page.locator('#moment-json').fill(draft.replace('Synthetic tabletop tilt and return','Unregistered behavior'));
  await page.locator('#moment-compile').click();await page.waitForFunction(()=>document.querySelector('#moment-status')?.dataset.state==='compiled');
  await page.locator('#gov-admit').click();await page.waitForFunction(()=>document.querySelector('#gov-status')?.dataset.state==='denied');
  assert.equal(await page.locator('#gov-start').isDisabled(),true);assert.equal(await page.locator('#gov-export').isDisabled(),true);
  passed('unregistered gesture cannot obtain admission or dispatch controls');
  await example();await page.locator('#gov-admit').click();await page.waitForFunction(()=>document.querySelector('#gov-status')?.dataset.state==='admitted');
  assert.equal(await page.locator('#gov-start').isDisabled(),false);
  await page.locator('#gov-start').click();await page.waitForFunction(()=>document.querySelector('#gov-status')?.dataset.state==='completed');
  await page.waitForFunction(()=>!document.querySelector('#gov-export')?.disabled);
  assert.equal(await page.locator('#viewport').getAttribute('data-pose-state'),'captured');
  assert.match(await page.locator('#view-mode').textContent(),/CAPTURED SIMULATION POSE/);
  const download=page.waitForEvent('download');await page.locator('#gov-export').click();const file=await download;
  await file.saveAs(path.join(out,'browser-capture.json'));const capture=JSON.parse(await readFile(path.join(out,'browser-capture.json'),'utf8'));
  assert.equal(capture.summary.executedSubsteps,120);assert.equal(capture.summary.tokenVerification,'rust_signature_and_constraints');
  assert.equal(capture.signed,false);assert.equal(capture.physicalAcceptance,false);
  passed('actual configured local PDP/signature/Rust gate completes 120 native MuJoCo substeps');
  let requests=0;const observe=()=>requests++;page.on('request',observe);
  await page.locator('#gov-tick').fill('60');await page.locator('#gov-tick').dispatchEvent('input');
  assert.match(await page.locator('#gov-frame').textContent(),/tick 61/);
  assert.equal(requests,0);page.off('request',observe);
  assert.equal(await page.locator('#content-digest').textContent(),assembly);assert.equal(await page.locator('#revision').textContent(),revision);
  assert.equal(await page.locator('#viewport').getAttribute('data-pose-state'),'captured');
  await page.screenshot({path:path.join(out,'governed-inspector.png'),fullPage:true});
  passed('read-only 3D capture scrub neither requests controls nor mutates authoring content');
  await page.locator('#gov-admit').click();await page.waitForFunction(()=>document.querySelector('#gov-status')?.dataset.state==='admitted');
  // Stop at the first real progress update, while the next substeps are still bounded.
  await page.evaluate(()=>{
    const n=document.querySelector('#gov-status');const observer=new MutationObserver(()=>{
      if(n.dataset.state==='running'&&/Running · [1-9][0-9]*\/120/.test(n.textContent)){observer.disconnect();document.querySelector('#gov-stop').click();}
    });observer.observe(n,{childList:true,attributes:true,subtree:true});
  });
  await page.locator('#gov-start').click();await page.waitForFunction(()=>document.querySelector('#gov-status')?.dataset.state==='stopped');
  assert.equal(await page.locator('#gov-start').isDisabled(),true);
  passed('operator stop latches the actual native attempt without a completed outcome');
  // Delay a response after the service has admitted it; a local edit must cancel
  // the reserved request and discard its late signed token, without starting it.
  let release,heldResolve;const held=new Promise(r=>heldResolve=r),gate=new Promise(r=>release=r);let delayedId;
  const hold=async route=>{const response=await route.fetch();const body=await response.json();delayedId=body.id;heldResolve();await gate;try{await route.fulfill({response});}catch{}};
  await page.route('**/api/cw-g01/admit',hold);
  try{
    await page.locator('#gov-admit').click();await held;
    await page.locator('#moment-json').fill(draft+' ');release();await page.unroute('**/api/cw-g01/admit',hold);
    await page.waitForTimeout(150);
    assert.equal(await page.locator('#gov-start').isDisabled(),true);assert.equal(await page.locator('#gov-export').isDisabled(),true);
    const stopped=await (await fetch(`${base}/api/cw-g01/${delayedId}/status`)).json();
    assert.equal(stopped.state,'stopped');assert.equal(stopped.executedSubsteps,0);
    assert.equal(await page.locator('#viewport').getAttribute('data-pose-state'),'rest');
  }finally{release?.();await page.unroute('**/api/cw-g01/admit',hold);}
  passed('edit during delayed admission cannot restore a token, start, capture or stale 3D pose');
  assert.deepEqual(report.errors,[]);report.status='checks_passed';report.browser=browser.version();
}catch(error){report.status='checks_failed';report.failure=String(error.stack||error);process.exitCode=1;console.error(report.failure);}
finally{await browser?.close();server.kill('SIGTERM');await writeFile(path.join(out,'browser-verification.json'),JSON.stringify(report,null,2)+'\n');await writeFile(path.join(out,'server.log'),log);}
