// Real-browser CW-ASM-02 / CW-SNAP-01 / CW-DRC-01..03 acceptance. Starts a temporary localhost service.
import {chromium} from 'playwright';
import {exerciseSnapping} from './snapping-browser.mjs';
import {exerciseDrc} from './drc-browser.mjs';
import {spawn} from 'node:child_process';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const output=path.join(root,'artifacts/robotics/cw-a04');await mkdir(output,{recursive:true});
const compatOutput=path.join(root,'artifacts/robotics/cw-a03');await mkdir(compatOutput,{recursive:true});
const report={scope:'offline_proxy_authoring',physical_acceptance:false,checks:[],errors:[]};
const port=process.env.SEEDCORE_STUDIO_TEST_PORT||'8768',base=`http://127.0.0.1:${port}`;
const python=process.env.SEEDCORE_TEST_PYTHON||path.join(root,'.venv/bin/python');
const server=spawn(python,['scripts/robotics/serve_mini_studio.py','--port',port],{cwd:root,stdio:['ignore','pipe','pipe']});
let log='';server.stdout.on('data',data=>{log+=data;});server.stderr.on('data',data=>{log+=data;});
let browser;
const passed=name=>{report.checks.push(name);console.log(`PASS ${name}`);};
try {
  for(let i=0;i<100;i++) {if(server.exitCode!==null) throw new Error(`Service exited before readiness: ${log}`);try{if(log.includes('Uvicorn running on') && (await fetch(`${base}/api/starter`)).ok) break;}catch{} if(i===99) throw new Error(`Service did not start: ${log}`);await new Promise(resolve=>setTimeout(resolve,100));}
  const channel=process.env.SEEDCORE_BROWSER_CHANNEL||'chrome';
  browser=await chromium.launch({headless:true,...(channel==='bundled'?{}:{channel})});report.browser=browser.version();
  const context=await browser.newContext({viewport:{width:1440,height:1050},acceptDownloads:true});const page=await context.newPage();
  page.on('pageerror',error=>report.errors.push(error.message));
  page.on('console',message=>{if(message.type()==='error'&&!message.text().includes('favicon')&&!message.text().includes('Failed to load resource')) report.errors.push(message.text());});
  await page.goto(base);await page.waitForFunction(()=>document.querySelector('#content-digest')?.textContent==='2550d184c44a064c6ad6a2245a08f430f257c40ca8f3627e73eeb3fedd452acb');
  await page.waitForFunction(()=>document.querySelector('canvas')?.dataset.meshState==='verified');
  assert.equal(await page.locator('#nodes button').count(),5);assert.equal(await page.locator('#edges button').count(),4);
  passed('v2 starter digest, five hashed proxy meshes and rest-pose canvas');
  await page.locator('#nodes button').nth(2).focus();await page.keyboard.press('Enter');assert.equal(await page.locator('#nodes button[aria-pressed=true]').count(),1);
  await page.locator('#edges button').nth(2).click();assert.equal(await page.locator('#edges button[aria-pressed=true]').count(),1);passed('keyboard node and edge selection');
  await page.locator('#name').fill('CW-A02 browser revision');await page.locator('#rename').click();await page.waitForFunction(()=>document.querySelector('#build-name')?.textContent==='CW-A02 browser revision');
  const edited=await page.locator('#content-digest').textContent();assert.notEqual(edited,'2550d184c44a064c6ad6a2245a08f430f257c40ca8f3627e73eeb3fedd452acb');
  await page.locator('#undo').click();assert.equal(await page.locator('#content-digest').textContent(),'2550d184c44a064c6ad6a2245a08f430f257c40ca8f3627e73eeb3fedd452acb');
  await page.locator('#redo').click();assert.equal(await page.locator('#content-digest').textContent(),edited);passed('new immutable edit revision, undo and redo');
  const download=page.waitForEvent('download');await page.locator('#export').click();const exported=await download;
  await exported.saveAs(path.join(output,'export.sc-assembly.json'));const raw=await readFile(path.join(output,'export.sc-assembly.json'),'utf8');assert.equal(JSON.parse(raw).identity.name,'CW-A02 browser revision');
  await page.reload();await page.waitForFunction(()=>document.querySelector('#build-name')?.textContent==='CW-A02 browser revision');passed('export and browser draft restoration through validation');
  await page.locator('.raw summary').click();
  for(const [name,input] of [['duplicate escaped key','{"schema_version":"seedcore.assembly.v2","schema\\u005fversion":"seedcore.assembly.v2"}'],['historical v1',raw.replace('seedcore.assembly.v2','seedcore.assembly.v1')],['bad part pin',raw.replace(/"part_sha256":"[0-9a-f]+"/,'"part_sha256":"'+'0'.repeat(64)+'"')]]) {
    await page.locator('#raw').fill(input);await page.locator('#import-text').click();await page.waitForFunction(()=>document.querySelector('#status')?.dataset.error==='true');assert.equal(await page.locator('#content-digest').textContent(),edited);passed(`${name} rejected atomically`);
  }
  // Hold the first asset response, accept a newer edit, then release the obsolete result.
  let release,heldResolve;const held=new Promise(resolve=>{heldResolve=resolve;}),gate=new Promise(resolve=>{release=resolve;});let first=true;
  await page.route('**/assets/*.glb',async route=>{if(first){first=false;heldResolve();await gate;}try{await route.continue();}catch{}});
  await page.locator('#starter').click();await held;
  assert.equal(await page.locator('#content-digest').textContent(),edited);
  await page.locator('#name').fill('Newer build wins');await page.locator('#rename').click();await page.waitForFunction(()=>document.querySelector('#build-name')?.textContent==='Newer build wins');
  const newer=await page.locator('#content-digest').textContent();release();await page.unroute('**/assets/*.glb');await page.waitForTimeout(150);
  assert.equal(await page.locator('#content-digest').textContent(),newer);passed('slow stale asset load cannot replace newer build');
  await page.route('**/assets/*.glb',route=>route.fulfill({status:503,body:'synthetic fixture failure'}));
  await page.locator('#starter').click();await page.waitForFunction(()=>document.querySelector('#status')?.dataset.error==='true');assert.equal(await page.locator('#content-digest').textContent(),newer);assert.equal(await page.locator('canvas').getAttribute('data-mesh-state'),'verified');await page.unroute('**/assets/*.glb');passed('asset failure preserves previous build and scene');
  await page.locator('#raw').fill(raw);await page.locator('#import-text').click();await page.waitForFunction(()=>document.querySelector('#build-name')?.textContent==='CW-A02 browser revision');passed('recovery by valid raw-text import');
  await page.locator('.raw summary').click();await exerciseSnapping(page,output,passed);await exerciseDrc(page,output,passed);await page.screenshot({path:path.join(output,'desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.waitForTimeout(250);await page.screenshot({path:path.join(output,'mobile.png')});
  await page.locator('.inspector').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'mobile-inspector.png')});passed('desktop and mobile layout; no horizontal overflow');
  assert.deepEqual(report.errors,[]);passed('strict CSP and no browser exceptions');report.status='checks_passed';
} catch(error) {report.status='checks_failed';report.failure=String(error.stack||error);process.exitCode=1;console.error(report.failure);}
finally {await browser?.close();server.kill('SIGTERM');for(const dir of [output,compatOutput]){await writeFile(path.join(dir,'browser-verification.json'),JSON.stringify(report,null,2)+'\n');await writeFile(path.join(dir,'server.log'),log);}}
