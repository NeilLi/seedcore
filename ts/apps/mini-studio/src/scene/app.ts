import {sharedFrames,FRAME_PROTOCOL} from '@seedcore/wasm-sim-bridge/visual';
const PROTOCOL='seedcore.scene-lab.v1';
const el=<T extends HTMLElement>(id:string)=>document.getElementById(id) as T;
let generation=0,physics:Worker|undefined,render:Worker|undefined,observer:ResizeObserver|undefined,timer:ReturnType<typeof setTimeout>|undefined;
let running=false,physicsState='idle',metrics:Record<string,any>={},physicsMetrics:Record<string,any>={},view={distance:5,yaw:-.8,pitch:.9,sse:16};
const status=(text:string,state:string)=>{el('scene-status').textContent=text;el('scene-status').dataset.state=state;};
const report=()=>({schema:'seedcore.static-scene-measurement.v1',scope:'synthetic_visual_streaming',physicalAcceptance:false,executionAuthority:'none',browser:navigator.userAgent,generation,physicsState,metrics,physicsMetrics});
function show(){
  el('visible').textContent=String(metrics.visibleTiles??'—');el('triangles').textContent=String(metrics.visibleTriangles??'—');el('resident').textContent=metrics.residentTiles===undefined?'—':`${metrics.residentTiles} / ${metrics.cacheTiles}`;el('physics-tick').textContent=String(metrics.tick??0);el('scene-json').textContent=JSON.stringify(report(),null,2);
  el('scene-detail').textContent=metrics.staticStatus?`${metrics.staticStatus} · ${(metrics.downloadBytes/1024).toFixed(1)} KiB tile data · ${(metrics.residentGeometryBytes/1024).toFixed(1)} KiB resident geometry · ${metrics.evictions} evictions · ${metrics.failures} load failures.${metrics.cacheConstrained?' Cache full; retaining coarse coverage.':''}${metrics.coarseFallbackLatched?' Detail disabled until a new rehearsal.':''} ${metrics.lastError??''}`:'';
}
function stop(reason:string){running=false;clearTimeout(timer);observer?.disconnect();physics?.terminate();render?.terminate();physics=render=undefined;el<HTMLButtonElement>('scene-start').disabled=false;el<HTMLButtonElement>('scene-stop').disabled=true;el<HTMLFieldSetElement>('scene-settings').disabled=false;physicsState='interrupted';show();status(reason,'interrupted');}
function sendView(){render?.postMessage({protocol:PROTOCOL,type:'view',generation,...view});}
el<HTMLButtonElement>('scene-start').onclick=()=>{
  stop('Preparing a new scene…');metrics={};physicsMetrics={};physicsState='initializing';show();
  const id=++generation;
  try {
    if(!isSecureContext||!crossOriginIsolated||typeof SharedArrayBuffer==='undefined'||!HTMLCanvasElement.prototype.transferControlToOffscreen)throw Error('This lab requires localhost isolation, SharedArrayBuffer and OffscreenCanvas. Assembly authoring remains available.');
    const seconds=Number(el<HTMLSelectElement>('scene-seconds').value),cacheTiles=Number(el<HTMLSelectElement>('scene-cache').value);
    const config={mode:'shared' as const,chains:1,hz:500 as const,seconds},shared=sharedFrames(config).buffer,channel=new MessageChannel();
    const canvas=document.createElement('canvas');canvas.setAttribute('aria-label','Streamed static workbench and separate synthetic active robot. Use view controls to navigate.');el('scene-view').replaceChildren(canvas);
    physics=new Worker('/lab-physics.js',{type:'module',name:'seedcore-scene-physics'});render=new Worker('/scene-worker.js',{type:'module',name:'seedcore-static-render'});running=true;
    el<HTMLButtonElement>('scene-start').disabled=true;el<HTMLButtonElement>('scene-stop').disabled=false;el<HTMLFieldSetElement>('scene-settings').disabled=true;
    const ready=new Set<string>();
    const receive=(source:'physics'|'scene')=>({data:m}:MessageEvent)=>{
      if(!running||id!==generation||m?.generation!==id||m?.protocol!==(source==='physics'?FRAME_PROTOCOL:PROTOCOL))return;
      if(m.type==='error'){stop(`${source}: ${m.error}`);status(`${source}: ${m.error}`,'failed');return;}
      if(m.type==='ready'){ready.add(source);if(ready.size===2&&physicsState==='initializing'){clearTimeout(timer);sendView();physics!.postMessage({protocol:FRAME_PROTOCOL,type:'start',generation:id});render!.postMessage({protocol:PROTOCOL,type:'start',generation:id});physicsState='running';status('Static tiles stream independently of the synthetic 500 Hz robot.','running');}return;}
      if(m.metrics){if(source==='physics')physicsMetrics=m.metrics;else metrics=m.metrics;show();}
      if(m.type==='complete'&&source==='physics'){physicsState='complete';physics?.terminate();physics=undefined;status('Physics rehearsal complete. Explore the static scene or start a fresh rehearsal.','complete');show();}
    };
    physics.onmessage=receive('physics');render.onmessage=receive('scene');
    for(const [name,worker] of [['Physics',physics],['Scene',render]] as const)worker.onerror=e=>{e.preventDefault();stop(`${name} worker failed; restart required.`);status(`${name} worker failed; restart required.`,'failed');};
    const rect=canvas.getBoundingClientRect(),offscreen=canvas.transferControlToOffscreen();
    physics.postMessage({protocol:FRAME_PROTOCOL,type:'init',generation:id,config,shared,port:channel.port1},[channel.port1]);
    render.postMessage({protocol:PROTOCOL,type:'init',generation:id,shared,seconds,cacheTiles,canvas:offscreen,width:rect.width*devicePixelRatio,height:rect.height*devicePixelRatio},[offscreen]);channel.port2.close();
    observer=new ResizeObserver(entries=>{const r=entries[0].contentRect;render?.postMessage({protocol:PROTOCOL,type:'resize',generation:id,width:r.width*devicePixelRatio,height:r.height*devicePixelRatio});});observer.observe(canvas);
    let pointer:{id:number;x:number;y:number}|undefined;
    canvas.onpointerdown=e=>{pointer={id:e.pointerId,x:e.clientX,y:e.clientY};canvas.setPointerCapture(e.pointerId);};
    canvas.onpointermove=e=>{if(!pointer||pointer.id!==e.pointerId)return;view.yaw=Math.max(-Math.PI,Math.min(Math.PI,view.yaw+(e.clientX-pointer.x)*.008));view.pitch=Math.max(.2,Math.min(1.4,view.pitch+(e.clientY-pointer.y)*.006));pointer.x=e.clientX;pointer.y=e.clientY;sendView();};
    canvas.onpointerup=canvas.onpointercancel=()=>{pointer=undefined;};
    timer=setTimeout(()=>{if(physicsState==='initializing'){stop('Initialization timed out.');status('Initialization timed out.','failed');}},15000);status('Checking pinned manifest, decoder and tile sources…','initializing');
  }catch(e){stop(String(e));status(String(e),'failed');}
};
el<HTMLButtonElement>('scene-stop').onclick=()=>stop('Stopped. Start a new rehearsal to continue.');
el<HTMLSelectElement>('scene-distance').onchange=()=>{view.distance=Number(el<HTMLSelectElement>('scene-distance').value);sendView();};
el<HTMLInputElement>('scene-sse').oninput=()=>{view.sse=Number(el<HTMLInputElement>('scene-sse').value);el('sse-value').textContent=String(view.sse);sendView();};
el<HTMLButtonElement>('scene-reset-view').onclick=()=>{view={distance:5,yaw:-.8,pitch:.9,sse:16};el<HTMLSelectElement>('scene-distance').value='5';el<HTMLInputElement>('scene-sse').value='16';el('sse-value').textContent='16';sendView();};
el<HTMLButtonElement>('scene-export').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(report(),null,2)+'\n'],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='seedcore-static-scene.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
document.addEventListener('visibilitychange',()=>{if(document.hidden&&running)stop('Page hidden. Rehearsal interrupted; restart required.');});
window.addEventListener('pagehide',()=>stop('Page closed.'),{once:true});show();
