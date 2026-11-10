import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {mkdir} from 'node:fs/promises';
import assert from 'node:assert/strict';
const root=fileURLToPath(new URL('../../../',import.meta.url)),base='http://127.0.0.1:8790';
const server=spawn(`${root}/.venv/bin/python`,['scripts/robotics/serve_mini_studio.py','--port','8790'],{cwd:root,stdio:['ignore','pipe','pipe']});
let log='',browser;server.stdout.on('data',d=>log+=d);server.stderr.on('data',d=>log+=d);
try {
  for(let i=0;i<100;i++){if(server.exitCode!==null)throw Error(log);try{if(log.includes('Uvicorn running on')&&(await fetch(base+'/api/starter')).ok)break;}catch{}if(i===99)throw Error(log);await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({channel:'chrome',headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1050}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base);await page.waitForFunction(()=>document.querySelector('#demo-viewport')?.dataset.meshState==='verified');
  assert.equal(await page.locator('body').getAttribute('data-studio-view'),'demo');
  assert.equal(await page.locator('#demo-viewport').getAttribute('data-joint-count'),'14');
  assert.ok(Number(await page.locator('#demo-viewport').getAttribute('data-visual-count'))>38);
  assert.equal(await page.locator('#export').isDisabled(),true);
  await page.locator('#demo-yaw').fill('35');await page.locator('#demo-yaw').dispatchEvent('input');
  assert.equal(await page.locator('#demo-yaw-value').textContent(),'35°');
  assert.equal(await page.locator('#demo-viewport').getAttribute('data-pose-state'),'posed');
  await page.locator('#demo-reset').click();assert.equal(await page.locator('#demo-yaw').inputValue(),'0');
  const license=await page.request.get(base+'/microduck-LICENSE.txt');assert.equal(license.status(),200);assert.match(await license.text(),/Apache License/);
  await mkdir(`${root}/artifacts/robotics/microduck-preview`,{recursive:true});
  await page.screenshot({path:`${root}/artifacts/robotics/microduck-preview/desktop.png`,fullPage:true});
  await page.setViewportSize({width:390,height:844});await page.waitForTimeout(100);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.screenshot({path:`${root}/artifacts/robotics/microduck-preview/mobile.png`,fullPage:true});
  await page.locator('#lesson-start').click();await page.waitForFunction(()=>document.body.dataset.studioView==='project');
  assert.equal(await page.locator('#demo-viewport').isVisible(),false);
  const saved=await page.locator('#content-digest').textContent();
  await page.locator('#show-demo').click();await page.waitForFunction(()=>document.querySelector('#demo-viewport')?.dataset.meshState==='verified');
  await page.locator('#resume-project').click();await page.waitForFunction(()=>document.body.dataset.studioView==='project');
  assert.equal(await page.locator('#content-digest').textContent(),saved);
  await page.reload();await page.waitForFunction(()=>document.body.dataset.studioView==='project');
  assert.equal(await page.locator('#content-digest').textContent(),saved);
  // A model that does not match the pinned build fails explicitly.
  await page.route('**/microduck.glb',route=>route.fulfill({status:200,body:'corrupt model'}));
  await page.locator('#show-demo').click();await page.waitForFunction(()=>document.querySelector('#demo-viewport')?.dataset.meshState==='failed');
  assert.match(await page.locator('#demo-status').textContent(),/integrity/);
  await page.locator('#lesson-start').click();await page.waitForFunction(()=>document.body.dataset.studioView==='project');
  assert.deepEqual(errors,[]);
  console.log('PASS full pinned Microduck, 14 joints, pose/reset, license, mobile, project switching/restoration and corrupt asset refusal');
} finally {await browser?.close();server.kill('SIGTERM');}
