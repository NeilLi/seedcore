// Real WebGPU/worker qualification. No fallback renderer or timing thresholds.
import {chromium} from 'playwright';
import {build} from 'esbuild';
import {spawn} from 'node:child_process';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';
const root=fileURLToPath(new URL('../../../',import.meta.url)),out=path.join(root,'artifacts/robotics/browser-performance');await mkdir(out,{recursive:true});
const report={scope:'synthetic_simulation_measurement',physicalAcceptance:false,executionAuthority:'none',checks:[],errors:[]};
const port=process.env.SEEDCORE_PERFORMANCE_TEST_PORT||'8769',base=`http://127.0.0.1:${port}`;
const server=spawn(process.env.SEEDCORE_TEST_PYTHON||path.join(root,'.venv/bin/python'),['scripts/robotics/serve_mini_studio.py','--port',port],{cwd:root,stdio:['ignore','pipe','pipe']});
let log='',browser;server.stdout.on('data',d=>log+=d);server.stderr.on('data',d=>log+=d);
const passed=name=>{report.checks.push(name);console.log(`PASS ${name}`);};
const result=async page=>JSON.parse(await page.locator('#report-json').textContent());
try {
  for(let i=0;i<100;i++){if(server.exitCode!==null)throw Error(log);try{if(log.includes('Uvicorn running on')&&(await fetch(base+'/api/starter')).ok)break;}catch{}if(i===99)throw Error('Server readiness timeout');await new Promise(r=>setTimeout(r,100));}
  const channel=process.env.SEEDCORE_BROWSER_CHANNEL||'chrome';browser=await chromium.launch({headless:true,...(channel==='bundled'?{}:{channel})});report.browser=browser.version();
  const context=await browser.newContext({viewport:{width:1280,height:1000},acceptDownloads:true}),page=await context.newPage();
  page.on('pageerror',e=>report.errors.push(e.message));page.on('console',m=>{if(m.type()==='error'&&!m.text().includes('Failed to load resource'))report.errors.push(m.text());});
  await page.goto(base+'/performance.html');await page.waitForSelector('#capabilities');
  assert.equal(await page.evaluate(()=>crossOriginIsolated),true);
  assert.ok(await page.evaluate(async()=>Boolean(await navigator.gpu?.requestAdapter())),'Real WebGPU adapter required. This browser check must not silently pass without GPU.');
  passed('localhost isolation, strict CSP, OffscreenCanvas and real WebGPU adapter');
  // Diagnostic readback exists only in this test, never in the display loop.
  const built=await build({entryPoints:[path.join(root,'ts/apps/mini-studio/src/performance/shaders.ts')],bundle:true,format:'esm',write:false});
  const {fkShader}=await import('data:text/javascript;base64,'+Buffer.from(built.outputFiles[0].text).toString('base64'));
  const qs=[[0,0,0],[.5,-.8,1.2],[-2,.7,-1.3],[Math.PI,-Math.PI/2,.01]];
  const matrices=await page.evaluate(async({code,qs})=>{
    const adapter=await navigator.gpu.requestAdapter(),d=await adapter.requestDevice();
    const input=d.createBuffer({size:qs.length*16,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST}),output=d.createBuffer({size:qs.length*3*64,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_SRC}),params=d.createBuffer({size:16,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST}),read=d.createBuffer({size:qs.length*3*64,usage:GPUBufferUsage.MAP_READ|GPUBufferUsage.COPY_DST});
    d.queue.writeBuffer(input,0,new Float32Array(qs.flatMap(q=>[...q,0])));d.queue.writeBuffer(params,0,new Uint32Array([qs.length,1,1,0]));
    const p=await d.createComputePipelineAsync({layout:'auto',compute:{module:d.createShaderModule({code}),entryPoint:'fk'}}),g=d.createBindGroup({layout:p.getBindGroupLayout(0),entries:[{binding:0,resource:{buffer:input}},{binding:1,resource:{buffer:output}},{binding:2,resource:{buffer:params}}]});
    const e=d.createCommandEncoder(),pass=e.beginComputePass();pass.setPipeline(p);pass.setBindGroup(0,g);pass.dispatchWorkgroups(1);pass.end();e.copyBufferToBuffer(output,0,read,0,qs.length*3*64);d.queue.submit([e.finish()]);await read.mapAsync(GPUMapMode.READ);const data=Array.from(new Float32Array(read.getMappedRange()));read.unmap();d.destroy();return data;
  },{code:fkShader,qs});
  let maxError=0;
  for(let i=0;i<qs.length;i++){let a=0,x=0,y=0;for(let j=0;j<3;j++){a+=Math.fround(qs[i][j]);const c=Math.cos(a),s=Math.sin(a),l=[.1,.08,.06][j],k=i*48+j*16;
    const expected=[c*l,s*l,0,0,-s*.014,c*.014,0,0,0,0,.014,0,x+c*l/2,y+s*l/2,0,1];for(let n=0;n<16;n++)maxError=Math.max(maxError,Math.abs(matrices[k+n]-expected[n]));x+=c*l;y+=s*l;}}
  assert.ok(maxError<1e-6,`GPU FK matrix max error ${maxError}`);report.gpuFkMaxAbsError=maxError;passed('WGSL FK matrices agree with independent CPU formula within 1e-6');
  await page.selectOption('#seconds','2');await page.click('#compare');
  await page.waitForFunction(()=>document.querySelectorAll('#results tr').length===3&&!document.querySelector('#run').disabled,null,{timeout:25000});
  const measurements=await result(page);report.measurements=measurements;
  assert.deepEqual(measurements.records.map(r=>r.outcome),['complete','complete','complete']);
  assert.equal(new Set(measurements.records.map(r=>r.stateSha256)).size,1);
  for(const r of measurements.records){assert.equal(r.physics.tick,1000);assert.equal(r.physics.backend,'cpp-wasm-tree-scalar');assert.ok(r.render.draws>0);assert.ok(r.render.uploadBytes>0);assert.equal(r.render.tick,1000);assert.equal(r.physics.physicalAcceptance,false);}
  assert.equal(measurements.records[2].render.compute,'wgsl-planar-fk');
  passed('all three real worker pipelines finish with identical Wasm state and final visual tick');
  await page.selectOption('#mode','gpu');await page.selectOption('#hz','1000');await page.click('#run');
  await page.waitForFunction(()=>document.querySelectorAll('#results tr').length===4&&!document.querySelector('#run').disabled,null,{timeout:10000});
  const highRate=(await result(page)).records.at(-1);assert.equal(highRate.outcome,'complete');assert.equal(highRate.physics.tick,2000);assert.equal(highRate.render.tick,2000);report.highRateMeasurement=highRate;passed('1000 Hz fixed-step target finishes on the named 16-chain synthetic workload');
  await page.selectOption('#mode','transfer');await page.selectOption('#hz','500');
  await page.screenshot({path:path.join(out,'desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true});await page.setViewportSize({width:1280,height:1000});passed('responsive comparison table and preview');
  const download=page.waitForEvent('download');await page.click('#export-report');const file=await download;await file.saveAs(path.join(out,'measurement.json'));assert.equal(JSON.parse(await readFile(path.join(out,'measurement.json'),'utf8')).executionAuthority,'none');passed('scoped JSON measurement export');
  // A long UI task must not own or step physics; independent workers keep running.
  await page.click('#run');await page.waitForFunction(()=>document.querySelector('#status').dataset.state==='running');
  await page.evaluate(()=>{const until=performance.now()+100;while(performance.now()<until){/* synthetic UI stall */}});
  await page.click('#stop');assert.equal((await result(page)).records.at(-1).outcome,'interrupted');
  await page.waitForTimeout(150);assert.equal(await page.locator('#status').getAttribute('data-state'),'interrupted');passed('operator interruption terminates workers and fences late messages');
  await page.route('**/lab-physics.wasm',async route=>{const bytes=await readFile(path.join(root,'ts/apps/mini-studio/dist/lab-physics.wasm'));bytes[bytes.length-1]^=1;await route.fulfill({status:200,contentType:'application/wasm',body:bytes});});
  await page.click('#run');await page.waitForFunction(()=>document.querySelector('#status').dataset.state==='failed');assert.match((await result(page)).records.at(-1).error,/SHA-256 mismatch/);await page.unroute('**/lab-physics.wasm');passed('corrupt Wasm rejected before simulation');
  await page.route('**/lab-render.js',route=>route.fulfill({status:200,contentType:'application/javascript',body:'throw new Error("synthetic renderer startup failure");'}));
  await page.click('#run');await page.waitForFunction(()=>document.querySelector('#status').dataset.state==='failed');assert.match((await result(page)).records.at(-1).error,/Render worker:/);assert.doesNotMatch((await result(page)).records.at(-1).error,/undefined/);await page.unroute('**/lab-render.js');passed('renderer crash fails the run and preserves recovery');
  await page.click('#run');await page.waitForFunction(()=>document.querySelector('#status').dataset.state==='running');
  await page.evaluate(()=>{Object.defineProperty(document,'hidden',{value:true,configurable:true});document.dispatchEvent(new Event('visibilitychange'));});
  assert.equal((await result(page)).records.at(-1).outcome,'interrupted');await page.evaluate(()=>{delete document.hidden;});passed('hidden-page event fences the simulation measurement');
  const unsupported=await context.newPage();await unsupported.addInitScript(()=>Object.defineProperty(HTMLCanvasElement.prototype,'transferControlToOffscreen',{value:undefined}));await unsupported.goto(base+'/performance.html');await unsupported.click('#run');await unsupported.waitForFunction(()=>document.querySelector('#status').dataset.state==='failed');assert.match(await unsupported.locator('#status').textContent(),/OffscreenCanvas/);await unsupported.goto(base);await unsupported.waitForFunction(()=>document.querySelector('#content-digest').textContent.length===64);passed('unavailable capability fails explicitly; authoring still loads');
  assert.deepEqual(report.errors,[]);report.status='checks_passed';
}catch(error){report.status='checks_failed';report.failure=String(error.stack||error);console.error(report.failure);process.exitCode=1;}
finally{await browser?.close();server.kill('SIGTERM');await writeFile(path.join(out,'browser-verification.json'),JSON.stringify(report,null,2)+'\n');await writeFile(path.join(out,'server.log'),log);}
