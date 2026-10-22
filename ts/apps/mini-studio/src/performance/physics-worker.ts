import {FRAME_PROTOCOL, TransferFramePool, sharedFrames, publishFrame, validateLabConfig, FixedTickClock, PlanarLab, percentile, readPinnedPhysics, type LabConfig} from '@seedcore/wasm-sim-bridge/visual';
declare const __LAB_PHYSICS_SHA256__: string;
declare const __LAB_PHYSICS_BYTES__: number;
const worker=globalThis as unknown as {onmessage:((e:MessageEvent)=>void)|null;postMessage:(v:unknown)=>void};
let initialized=false, stopped=false, timer:ReturnType<typeof setTimeout>|undefined;
worker.onmessage=async ({data:m})=>{
  if(m?.type==='stop') {stopped=true;clearTimeout(timer);return;}
  if(initialized) return;
  initialized=true;
  let port:MessagePort|undefined;
  try {
    if(m?.protocol!==FRAME_PROTOCOL||m.type!=='init'||!Number.isInteger(m.generation)||m.generation<1||!(m.port instanceof MessagePort)) throw new Error('Invalid physics initialization');
    const config:LabConfig=validateLabConfig(m.config),generation=m.generation;port=m.port;
    if(config.mode!=='transfer'&&!(m.shared instanceof SharedArrayBuffer)) throw new Error('Shared visual transport missing');
    const frames=config.mode==='transfer'?undefined:sharedFrames(config,m.shared);
    const pool=config.mode==='transfer'?new TransferFramePool(config):undefined;
    const bytes=await readPinnedPhysics(await fetch('/lab-physics.wasm'),__LAB_PHYSICS_BYTES__,__LAB_PHYSICS_SHA256__);
    const digest=__LAB_PHYSICS_SHA256__;
    if(stopped) return;
    const physics=new PlanarLab(bytes,config.chains,config.hz);
    let tick=0,sequence=0,published=0,dropped=0,packMs=0,physicsMs=0,batches=0,lateBatches=0;
    const batchTimes:number[]=[];let started=0,nextPublish=0,nextReport=0;
    const send=(type:string,extra:object={})=>worker.postMessage({protocol:FRAME_PROTOCOL,type,generation,...extra});
    const metrics=()=>({tick,simulatedMs:tick*1000/config.hz,wallMs:performance.now()-started,physicsMs,packMs,published,dropped,batches,lateBatches,batchP50Ms:percentile(batchTimes,.5),batchP95Ms:percentile(batchTimes,.95),buildSha256:digest,backend:'cpp-wasm-tree-scalar',physicalAcceptance:false,executionAuthority:'none'});
    port!.onmessage=({data:r})=>{
      if(stopped) return;
      try {if(r?.protocol!==FRAME_PROTOCOL||r.generation!==generation||r.type!=='recycle'||!pool) throw new Error('Invalid frame return envelope');pool.recycle(r.id,r.sequence,r.buffer);}
      catch(error) {fault(error);}
    };
    function fault(error:unknown) {stopped=true;clearTimeout(timer);send('error',{error:String(error)});port?.close();}
    function publish() {
      const begin=performance.now();sequence++;
      let ok=false;
      if(frames) ok=publishFrame(frames,sequence,tick,view=>physics.pack(view,config.mode==='gpu'));
      else {
        const slot=pool!.take(sequence);
        if(slot) {physics.pack(new Float32Array(slot.buffer),false);port!.postMessage({protocol:FRAME_PROTOCOL,type:'frame',generation,sequence,tick,...slot},[slot.buffer]);ok=true;}
      }
      packMs+=performance.now()-begin;if(ok) published++;else dropped++;
    }
    // Both workers are ready before the main thread starts the measured clock.
    port!.start();send('ready',{buildSha256:digest});
    worker.onmessage=({data:command})=>{
      if(command?.protocol!==FRAME_PROTOCOL||command.generation!==generation) return;
      if(command.type==='stop') {stopped=true;clearTimeout(timer);port?.close();return;}
      if(command.type!=='start'||started||stopped) return;
      started=performance.now();nextPublish=started;nextReport=started;
      const clock=new FixedTickClock(config.hz,config.seconds,started);
      const advance=()=>{
        if(stopped) return;
        try {
          const begin=performance.now(),due=clock.due(begin,tick);
          if(due) {
            for(let k=0;k<due;k++) {physics.step(tick);tick++;}
            const elapsed=performance.now()-begin;physicsMs+=elapsed;batches++;
            if(elapsed>due*1000/config.hz) lateBatches++;
            if(batchTimes.length<8192) batchTimes.push(elapsed);
          }
          const now=performance.now();
          if(now>=nextPublish||tick===clock.total) {publish();nextPublish=now+1000/120;}
          if(now>=nextReport) {send('metrics',{metrics:metrics()});nextReport=now+500;}
          if(tick===clock.total) {
            stopped=true;
            void crypto.subtle.digest('SHA-256',physics.state.buffer as ArrayBuffer).then(hash=>send('complete',{metrics:metrics(),stateSha256:Array.from(new Uint8Array(hash),v=>v.toString(16).padStart(2,'0')).join('')})).catch(fault);
          } else timer=setTimeout(advance,4);
        } catch(error) {fault(error);}
      };advance();
    };
  } catch(error) {stopped=true;worker.postMessage({protocol:FRAME_PROTOCOL,type:'error',generation:m?.generation,error:String(error)});port?.close();}
};
