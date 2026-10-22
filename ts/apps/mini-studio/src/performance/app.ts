import {FRAME_PROTOCOL, LAB_PROFILE, sharedFrames, validateLabConfig, type LabConfig} from '@seedcore/wasm-sim-bridge/visual';
const el=<T extends HTMLElement>(id:string)=>document.getElementById(id) as T;
const start=el<HTMLButtonElement>('run'),compare=el<HTMLButtonElement>('compare'),stopButton=el<HTMLButtonElement>('stop'),exportButton=el<HTMLButtonElement>('export-report');
const records:Record<string,unknown>[]=[];
let generation=0,active=false,abort:((reason:string)=>void)|undefined;
let latestPhysics:Record<string,any>={},latestRender:Record<string,any>={};
const capabilities={secureContext:isSecureContext,crossOriginIsolated,sharedMemory:typeof SharedArrayBuffer!=='undefined',offscreen:typeof HTMLCanvasElement.prototype.transferControlToOffscreen==='function',webgpu:'gpu' in navigator};
const sharedAvailable=capabilities.secureContext&&capabilities.crossOriginIsolated&&capabilities.sharedMemory;
el('capabilities').textContent=`WebGPU ${capabilities.webgpu?'exposed':'unavailable'} · OffscreenCanvas ${capabilities.offscreen?'available':'unavailable'} · shared memory ${sharedAvailable?'available':'unavailable'}`;
for(const option of el<HTMLSelectElement>('mode').options)if(option.value!=='transfer'&&!sharedAvailable)option.disabled=true;
compare.title=sharedAvailable?'Run the three pipelines in sequence.':'Comparing all three requires shared memory. Run transferable matrices on this browser.';
function status(text:string,state:string) {el('status').textContent=text;el('status').dataset.state=state;}
function controls(busy:boolean) {active=busy;start.disabled=busy;compare.disabled=busy||!sharedAvailable;stopButton.disabled=!busy;el<HTMLFieldSetElement>('settings').disabled=busy;exportButton.disabled=busy||!records.length;}
function config():LabConfig {return validateLabConfig({mode:el<HTMLSelectElement>('mode').value,chains:Number(el<HTMLSelectElement>('chains').value),hz:Number(el<HTMLSelectElement>('hz').value),seconds:Number(el<HTMLSelectElement>('seconds').value)});}
function format(n:unknown,digits=1) {return typeof n==='number'&&Number.isFinite(n)?n.toFixed(digits):'—';}
function display() {
  el('physics-rate').textContent=latestPhysics.wallMs?`${format(latestPhysics.tick*1000/latestPhysics.wallMs,0)} ticks/s`:'—';
  el('render-rate').textContent=latestRender.frameP50Ms?`${format(1000/latestRender.frameP50Ms,0)} FPS`:'—';
  el('frame-p95').textContent=`${format(latestRender.frameP95Ms)} ms`;
  el('upload').textContent=`${format((latestRender.uploadBytes??0)/1024,0)} KiB`;
}
function report() {
  return {schema:'seedcore.browser-performance-report.v1',scope:'synthetic_simulation_measurement',profile:LAB_PROFILE,physicalAcceptance:false,executionAuthority:'none',browser:navigator.userAgent,logicalProcessors:navigator.hardwareConcurrency,capabilities,records};
}
function updateRecords() {
  el('report-json').textContent=JSON.stringify(report(),null,2);
  el('results').replaceChildren(...records.map(record=>{
    const c=record.config as LabConfig,p=record.physics as typeof latestPhysics,r=record.render as typeof latestRender;
    const row=document.createElement('tr');row.dataset.mode=c.mode;
    for(const value of [c.mode,`${c.chains*3}`,`${c.hz}`,record.outcome,format(p.wallMs?1000*p.tick/p.wallMs:undefined,0),format(r.frameP95Ms),format(r.uploadBytes? r.uploadBytes/1024:0,0),format(p.packMs,2),format(r.uploadMs,2)]) {const td=document.createElement('td');td.textContent=String(value);row.append(td);}
    return row;
  }));
}
async function run(c:LabConfig):Promise<boolean> {
  const id=++generation;latestPhysics={};latestRender={};display();
  let physics:Worker|undefined,renderer:Worker|undefined,observer:ResizeObserver|undefined;
  let timeout:ReturnType<typeof setTimeout>|undefined,finishTimer:ReturnType<typeof setTimeout>|undefined;
  const startedAt=new Date().toISOString();
  return new Promise(resolve=>{
    let ended=false,stateSha256:string|undefined;const ready=new Set<string>();
    const finish=(outcome:string,error?:string)=>{
      if(ended)return;ended=true;clearTimeout(timeout);clearTimeout(finishTimer);observer?.disconnect();
      physics?.terminate();renderer?.terminate();abort=undefined;
      records.push({config:c,generation:id,startedAt,outcome,...(error?{error}:{}),physics:{...latestPhysics},render:{...latestRender},...(stateSha256?{stateSha256}:{})});
      if(records.length>24)records.shift();updateRecords();
      status(error??`${c.mode} measurement complete. Results describe this synthetic planar workload.`,outcome);resolve(outcome==='complete');
    };
    abort=reason=>finish('interrupted',reason);
    try {
      if(!capabilities.secureContext||!capabilities.offscreen||!capabilities.webgpu)throw new Error('This lab needs a secure context, OffscreenCanvas and a WebGPU adapter. Return to Mini Studio for authoring.');
      if(c.mode!=='transfer'&&(!capabilities.sharedMemory||!capabilities.crossOriginIsolated))throw new Error('Shared modes require cross-origin isolation. Choose transferable mode or use the localhost server.');
      const canvas=document.createElement('canvas');canvas.id='lab-canvas';canvas.setAttribute('aria-label','Synthetic planar three-link robots; simulation only.');
      el('view').replaceChildren(canvas);
      const rect=canvas.getBoundingClientRect(),channel=new MessageChannel();
      const shared=c.mode==='transfer'?undefined:sharedFrames(c).buffer;
      physics=new Worker('/lab-physics.js',{type:'module',name:'seedcore-lab-physics'});
      renderer=new Worker('/lab-render.js',{type:'module',name:'seedcore-lab-render'});
      const message=(source:'physics'|'render')=>({data:m}:MessageEvent)=>{
        if(ended||m?.protocol!==FRAME_PROTOCOL||m.generation!==id)return;
        if(m.type==='error') {finish('failed',`${source}: ${m.error}`);return;}
        if(m.type==='ready') {
          if(ready.has(source))return;ready.add(source);
          if(ready.size===2) {clearTimeout(timeout);status(`Running ${c.mode} · ${c.chains*3} links · ${c.hz} Hz target.`, 'running');
            physics!.postMessage({protocol:FRAME_PROTOCOL,type:'start',generation:id});renderer!.postMessage({protocol:FRAME_PROTOCOL,type:'start',generation:id});
            timeout=setTimeout(()=>finish('failed','Run exceeded its bounded wall-time budget.'),(c.seconds+2)*1000);
          }return;
        }
        if(m.metrics) {if(source==='physics')latestPhysics=m.metrics;else latestRender=m.metrics;display();
          if(stateSha256&&source==='render'&&latestRender.tick===latestPhysics.tick)finish('complete');
        }
        if(m.type==='complete') {
          stateSha256=m.stateSha256;
          // Allow the final visual snapshot to arrive, then request current metrics.
          finishTimer=setTimeout(()=>finish('failed','Final visual snapshot was not acknowledged within one second.'),1000);
          renderer!.postMessage({protocol:FRAME_PROTOCOL,type:'report',generation:id});
        }
      };
      physics.onmessage=message('physics');renderer.onmessage=message('render');
      physics.onerror=event=>{event.preventDefault();finish('failed',`Physics worker: ${event.message||'startup or execution failed. Restart the measurement.'}`);};renderer.onerror=event=>{event.preventDefault();finish('failed',`Render worker: ${event.message||'startup or execution failed. Restart the measurement.'}`);};
      const offscreen=canvas.transferControlToOffscreen();
      physics.postMessage({protocol:FRAME_PROTOCOL,type:'init',generation:id,config:c,shared,port:channel.port1},[channel.port1]);
      renderer.postMessage({protocol:FRAME_PROTOCOL,type:'init',generation:id,config:c,shared,port:channel.port2,canvas:offscreen,width:rect.width*devicePixelRatio,height:rect.height*devicePixelRatio},[channel.port2,offscreen]);
      observer=new ResizeObserver(entries=>{const rect=entries[0].contentRect;renderer?.postMessage({protocol:FRAME_PROTOCOL,type:'resize',generation:id,width:rect.width*devicePixelRatio,height:rect.height*devicePixelRatio});});observer.observe(canvas);
      timeout=setTimeout(()=>finish('failed','Worker initialization timed out.'),15000);status('Checking pinned Wasm and initializing WebGPU workers…','initializing');
    }catch(error){finish('failed',String(error));}
  });
}
start.onclick=async()=>{controls(true);try{await run(config());}finally{controls(false);}};
compare.onclick=async()=>{
  if(!sharedAvailable)return;
  controls(true);
  try {const c=config();for(const mode of ['transfer','shared','gpu'] as const)if(!await run({...c,mode}))break;}
  finally{controls(false);}
};
stopButton.onclick=()=>abort?.('Stopped by the operator. Start a new measurement to continue.');
document.addEventListener('visibilitychange',()=>{if(document.hidden&&active)abort?.('Measurement interrupted because the page became hidden.');});
window.addEventListener('pagehide',()=>abort?.('Page closed.'),{once:true});
exportButton.onclick=()=>{
  const url=URL.createObjectURL(new Blob([JSON.stringify(report(),null,2)+'\n'],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='seedcore-browser-performance.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
controls(false);updateRecords();
if(!sharedAvailable)status('Shared memory is unavailable here. Run transferable matrices or return to assembly authoring.','idle');
