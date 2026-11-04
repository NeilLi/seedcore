// Actual service-owned native attempts and independently configured fixture trust.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';
const root=fileURLToPath(new URL('../../../',import.meta.url)),out=path.join(root,'artifacts/robotics/cw-g02/studio');
await mkdir(out,{recursive:true});
const port=process.env.SEEDCORE_G02_TEST_PORT||'8772',base=`http://127.0.0.1:${port}`;
const python=process.env.SEEDCORE_TEST_PYTHON||path.join(root,'.venv/bin/python');
const server=spawn(python,['tools/robotics/serve-cw-g01-test.py','--port',port,'--source','artifacts/robotics/cw-g02/source/endpoint-source.json',
  '--evidence','--trust-out',path.join(out,'trust.json')],{cwd:root,stdio:['ignore','pipe','pipe']});
let log='',browser;server.stdout.on('data',d=>{log+=d});server.stderr.on('data',d=>{log+=d});
const report={scope:'local_simulation_only',physicalAcceptance:false,executionAuthority:'none',fixtureContext:true,checks:[],errors:[]};
const passed=name=>{report.checks.push(name);console.log(`PASS ${name}`)};
try{
  for(let i=0;i<120;i++){
    if(server.exitCode!==null)throw Error(log);
    try{if((await fetch(`${base}/api/cw-g01/profile`)).ok)break;}catch{}
    if(i===119)throw Error(log);await new Promise(r=>setTimeout(r,100));
  }
  browser=await chromium.launch({headless:true,channel:process.env.SEEDCORE_BROWSER_CHANNEL||'chrome'});
  const page=await browser.newPage({viewport:{width:1440,height:1100},acceptDownloads:true});
  page.on('pageerror',e=>report.errors.push(e.message));
  const admissions=new Map();let controlRequests=0,verificationRequests=0;
  page.on('request',r=>{
    if(r.method()==='POST'&&/\/api\/cw-g01\//.test(r.url()))controlRequests++;
    if(r.method()==='POST'&&/\/api\/cw-g02\/[^/]+\/verify$/.test(r.url()))verificationRequests++;
  });
  page.on('response',async r=>{if(r.url().endsWith('/api/cw-g01/admit')){
    const value=await r.json();if(value.state==='admitted')admissions.set(value.id,value.evidenceContext);
  }});
  await page.goto(base);await page.waitForFunction(()=>document.querySelector('#viewport')?.dataset.meshState==='verified');
  assert.equal(await page.locator('#gov-evidence-verify').isDisabled(),true);
  await page.locator('#simulation-tab').click();await page.locator('#simulation-reference').click();
  await page.waitForFunction(()=>document.querySelector('#sim-status')?.dataset.state==='compiled');
  await page.locator('#sim-rehearsal-preset').click();
  await page.waitForFunction(()=>document.querySelector('#sim-status')?.dataset.state==='compiled');
  await page.locator('#moments-tab').click();await page.locator('#moment-example').click();await page.locator('#moment-compile').click();
  await page.waitForFunction(()=>document.querySelector('#moment-status')?.dataset.state==='compiled');
  const originalAssembly=await page.locator('#content-digest').textContent(),originalRevision=await page.locator('#revision').textContent();
  const draft=await page.locator('#moment-json').inputValue();
  async function run(stopped=false){
    await page.locator('#gov-admit').click();await page.waitForFunction(()=>document.querySelector('#gov-status')?.dataset.state==='admitted');
    if(stopped)await page.evaluate(()=>{
      const n=document.querySelector('#gov-status');const observer=new MutationObserver(()=>{
        if(n.dataset.state==='running'&&/Running · [1-9][0-9]*\/120/.test(n.textContent)){observer.disconnect();document.querySelector('#gov-stop').click();}
      });observer.observe(n,{childList:true,attributes:true,subtree:true});
    });
    await page.locator('#gov-start').click();
    await page.waitForFunction(state=>document.querySelector('#gov-status')?.dataset.state===state,stopped?'stopped':'completed');
    await page.waitForFunction(()=>!document.querySelector('#gov-evidence-verify')?.disabled);
  }
  async function verify(disposition){
    await page.locator('#gov-evidence-verify').click();
    await page.waitForFunction(state=>document.querySelector('#gov-evidence-status')?.dataset.state===state,disposition);
    await page.waitForFunction(()=>!document.querySelector('#gov-evidence-bundle')?.disabled);
  }
  async function download(id,name){
    const pending=page.waitForEvent('download');await page.locator('#'+id).click();const file=await pending;
    await file.saveAs(path.join(out,name));return readFile(path.join(out,name));
  }
  async function retain(label){
    const raw=await download('gov-evidence-bundle',label+'.bundle.json');
    const context=JSON.parse(await download('gov-evidence-context',label+'.expected.json'));
    assert.deepEqual(context,admissions.get(context.requestId));
    await writeFile(path.join(out,label+'.admission-context.json'),JSON.stringify(admissions.get(context.requestId))+'\n');
    await download('gov-evidence-python',label+'.python.verification.json');
    await download('gov-evidence-rust',label+'.rust.verification.json');
    const retained=Buffer.from(await (await fetch(`${base}/api/cw-g02/${context.requestId}/evidence`)).arrayBuffer());
    assert.deepEqual(raw,retained);return raw;
  }
  await run();const before=controlRequests;
  await verify('verified_completed');const completed=await retain('completed');
  assert.match(await page.locator('#gov-evidence-details').textContent(),/physical acceptance: false/);
  assert.match(await page.locator('#gov-evidence-details').textContent(),/120\/120 captured substeps/);
  assert.equal(controlRequests,before);
  assert.equal(await page.locator('#content-digest').textContent(),originalAssembly);
  assert.equal(await page.locator('#revision').textContent(),originalRevision);
  passed('completed browser bundle and both reports preserve original bytes and pre-download admission context');

  await page.locator('#gov-evidence-import').setInputFiles({name:'roundtrip.json',mimeType:'application/json',buffer:completed});
  await page.waitForFunction(()=>document.querySelector('#gov-evidence-status')?.dataset.state==='verified_completed');
  assert.equal(controlRequests,before);
  assert.equal(await page.locator('#viewport').getAttribute('data-pose-state'),'captured');
  passed('same-attempt import verifies without control requests, authoring changes or solver-state injection');

  const unsafe=async route=>{const response=await route.fetch();const body=await response.json();body.reason='<img id="untrusted-evidence" src=x onerror="throw 1">';
    await route.fulfill({response,body:JSON.stringify(body),contentType:'application/json'});};
  await page.route('**/api/cw-g02/*/verify',unsafe);await verify('verified_completed');await page.unroute('**/api/cw-g02/*/verify',unsafe);
  assert.equal(await page.locator('#untrusted-evidence').count(),0);
  assert.match(await page.locator('#gov-evidence-status').textContent(),/<img/);
  passed('untrusted verifier text is displayed as text under strict CSP');
  // Restore an ordinary report before visual inspection.
  await verify('verified_completed');await page.locator('#gov-evidence-status').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(out,'evidence-inspector.png'),fullPage:true});

  const changed=JSON.parse(completed.toString());changed.artifacts.capture=Buffer.from('{}').toString('base64');
  const tampered=Buffer.from(JSON.stringify(changed));
  await page.locator('#gov-evidence-import').setInputFiles({name:'tampered.json',mimeType:'application/json',buffer:tampered});
  await page.waitForFunction(()=>document.querySelector('#gov-evidence-status')?.dataset.state==='quarantine');
  assert.deepEqual(await download('gov-evidence-bundle','tampered.bundle.json'),tampered);
  assert.equal(controlRequests,before);
  passed('tampered import is quarantined while the original imported bytes remain downloadable');

  const requestCount=verificationRequests;
  await page.locator('#gov-evidence-import').setInputFiles({name:'oversized.json',mimeType:'application/json',buffer:Buffer.alloc(2*1024*1024+1)});
  await page.waitForFunction(()=>document.querySelector('#gov-evidence-status')?.dataset.state==='unavailable');
  assert.match(await page.locator('#gov-evidence-status').textContent(),/2 MiB/);
  assert.equal(verificationRequests,requestCount);assert.equal(await page.locator('#gov-evidence-rust').isDisabled(),true);
  passed('oversized import is rejected before network verification and cannot retain a verified badge');

  await run(true);const stoppedControls=controlRequests;
  await verify('verified_interrupted');await retain('stopped');
  assert.equal(controlRequests,stoppedControls);
  passed('operator-stopped browser bundle retains an independently verifiable interrupted outcome');
  await page.locator('#gov-evidence-import').setInputFiles({name:'other-attempt.json',mimeType:'application/json',buffer:completed});
  await page.waitForFunction(()=>document.querySelector('#gov-evidence-status')?.dataset.state==='quarantine');
  passed('a different known attempt cannot supply the current attempt context or verified badge');
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>document.documentElement.clientWidth),false);
  await page.setViewportSize({width:1440,height:1100});
  passed('evidence controls and complete digest text stay contained on mobile and desktop');

  let release,resolveHeld;const gate=new Promise(r=>release=r),held=new Promise(r=>resolveHeld=r);
  const hold=async route=>{const response=await route.fetch();resolveHeld();await gate;try{await route.fulfill({response});}catch{}};
  await page.route('**/api/cw-g02/*/verify',hold);
  try{
    await page.locator('#gov-evidence-verify').click();await held;
    await page.locator('#moment-json').fill(draft+' ');release();await page.unroute('**/api/cw-g02/*/verify',hold);
    await page.waitForTimeout(150);
    assert.equal(await page.locator('#gov-evidence-status').getAttribute('data-state'),'unavailable');
    for(const id of ['gov-evidence-verify','gov-evidence-bundle','gov-evidence-python','gov-evidence-rust','gov-evidence-context'])
      assert.equal(await page.locator('#'+id).isDisabled(),true);
    assert.equal(await page.locator('#viewport').getAttribute('data-pose-state'),'rest');
  }finally{release?.();await page.unroute('**/api/cw-g02/*/verify',hold);}
  passed('edit during delayed verification cannot restore old reports, downloads or a verified badge');
  assert.deepEqual(report.errors,[]);report.status='checks_passed';report.browser=browser.version();
}catch(error){report.status='checks_failed';report.failure=String(error.stack||error);process.exitCode=1;console.error(report.failure);}
finally{await browser?.close();server.kill('SIGTERM');await writeFile(path.join(out,'browser-verification.json'),JSON.stringify(report,null,2)+'\n');await writeFile(path.join(out,'server.log'),log);}
