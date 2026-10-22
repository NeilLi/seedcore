/// <reference types="@webgpu/types" />
import {FRAME_PROTOCOL, sharedFrames, acquireLatestFrame, releaseFrame, frameFloats, validateLabConfig, percentile} from '@seedcore/wasm-sim-bridge/visual';
import {fkShader,renderShader} from './shaders.js';
const worker=globalThis as unknown as {onmessage:((e:MessageEvent)=>void)|null;postMessage:(v:unknown)=>void;requestAnimationFrame:(f:(t:number)=>void)=>number;cancelAnimationFrame:(id:number)=>void};
let initialized=false,stopped=false,frame=0,device:GPUDevice|undefined,port:MessagePort|undefined;
let pending:{buffer:ArrayBuffer;id:number;sequence:number;tick:number}|undefined;
const buffers:GPUBuffer[]=[];
function stop() {stopped=true;worker.cancelAnimationFrame?.(frame);port?.close();for(const b of buffers)b.destroy();device?.destroy();}
worker.onmessage=async ({data:m})=>{
  if(m?.type==='stop') {stop();return;}
  if(initialized)return;initialized=true;
  try {
    if(m?.protocol!==FRAME_PROTOCOL||m.type!=='init'||!Number.isInteger(m.generation)||m.generation<1||!(m.canvas instanceof OffscreenCanvas)||!(m.port instanceof MessagePort)) throw new Error('Invalid render initialization');
    const config=validateLabConfig(m.config),generation=m.generation,canvas:OffscreenCanvas=m.canvas;port=m.port;
    if(config.mode!=='transfer'&&!(m.shared instanceof SharedArrayBuffer))throw new Error('Shared visual transport missing');
    const frames=config.mode==='transfer'?undefined:sharedFrames(config,m.shared);
    const send=(type:string,extra:object={})=>worker.postMessage({protocol:FRAME_PROTOCOL,type,generation,...extra});
    const fault=(error:unknown)=>{if(stopped)return;send('error',{error:String(error)});stop();};
    const adapter=await navigator.gpu?.requestAdapter();if(!adapter)throw new Error('WebGPU adapter unavailable. The assembly editor remains available.');
    device=await adapter.requestDevice();if(stopped){device.destroy();return;}
    const gpu=device,context=canvas.getContext('webgpu');if(!context)throw new Error('Offscreen WebGPU context unavailable');
    const format=navigator.gpu.getPreferredCanvasFormat();context.configure({device:gpu,format,alphaMode:'opaque'});
    gpu.addEventListener('uncapturederror',e=>fault(e.error.message));void gpu.lost.then(info=>{if(!stopped)fault(`WebGPU device lost: ${info.reason}`);});
    const make=(size:number,usage:number)=>{const b=gpu.createBuffer({size,usage});buffers.push(b);return b;};
    const transforms=make(config.chains*3*64,GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST);
    const angles=make(config.chains*16,GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST);
    const params=make(16,GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST);
    const vertices=make(32,GPUBufferUsage.VERTEX|GPUBufferUsage.COPY_DST);
    const indices=make(12,GPUBufferUsage.INDEX|GPUBufferUsage.COPY_DST);
    const indirect=make(20,GPUBufferUsage.INDIRECT|GPUBufferUsage.COPY_DST);
    gpu.queue.writeBuffer(vertices,0,new Float32Array([-.5,-.5,.5,-.5,.5,.5,-.5,.5]));
    gpu.queue.writeBuffer(indices,0,new Uint16Array([0,1,2,0,2,3]));
    gpu.queue.writeBuffer(indirect,0,new Uint32Array([6,config.chains*3,0,0,0]));
    const module=gpu.createShaderModule({code:renderShader});
    const render=await gpu.createRenderPipelineAsync({layout:'auto',vertex:{module,entryPoint:'vertex',buffers:[{arrayStride:8,attributes:[{shaderLocation:0,format:'float32x2',offset:0}]}]},fragment:{module,entryPoint:'fragment',targets:[{format}]},primitive:{topology:'triangle-list'}});
    const renderGroup=gpu.createBindGroup({layout:render.getBindGroupLayout(0),entries:[{binding:0,resource:{buffer:transforms}},{binding:1,resource:{buffer:params}}]});
    const compute=config.mode==='gpu'?await gpu.createComputePipelineAsync({layout:'auto',compute:{module:gpu.createShaderModule({code:fkShader}),entryPoint:'fk'}}):undefined;
    const computeGroup=compute?gpu.createBindGroup({layout:compute.getBindGroupLayout(0),entries:[{binding:0,resource:{buffer:angles}},{binding:1,resource:{buffer:transforms}},{binding:2,resource:{buffer:params}}]}):undefined;
    if(stopped)return;
    const resize=(width:number,height:number)=>{
      canvas.width=Math.max(1,Math.min(2048,Math.round(width)));canvas.height=Math.max(1,Math.min(1536,Math.round(height)));
      const cols=Math.ceil(Math.sqrt(config.chains*canvas.width/canvas.height));
      gpu.queue.writeBuffer(params,0,new Uint32Array([config.chains,cols,Math.ceil(config.chains/cols),0]));
    };resize(m.width,m.height);
    const recycle=(f:NonNullable<typeof pending>)=>port!.postMessage({protocol:FRAME_PROTOCOL,type:'recycle',generation,id:f.id,sequence:f.sequence,buffer:f.buffer},[f.buffer]);
    port!.onmessage=({data:r})=>{
      if(stopped)return;
      if(r?.protocol!==FRAME_PROTOCOL||r.generation!==generation||r.type!=='frame'||config.mode!=='transfer'||!Number.isInteger(r.sequence)||r.sequence<1||!Number.isInteger(r.tick)||r.tick<0||r.tick>config.hz*config.seconds||!Number.isInteger(r.id)||r.id<0||r.id>2||!(r.buffer instanceof ArrayBuffer)||r.buffer.byteLength!==frameFloats(config)*4) {fault('Invalid visual frame');return;}
      if(pending)recycle(pending);pending=r;
    };port!.start();
    let sequence=0,tick=0,draws=0,uploads=0,uploadBytes=0,uploadMs=0,submitMs=0,inFlight=0,gpuBackpressure=0;
    let previous=0,started=0,reportAt=0;const intervals:number[]=[];
    const metrics=()=>({draws,uploads,uploadBytes,uploadMs,submitMs,gpuBackpressure,tick,sequence,wallMs:performance.now()-started,frameP50Ms:percentile(intervals,.5),frameP95Ms:percentile(intervals,.95),renderer:'offscreen-webgpu',compute:config.mode==='gpu'?'wgsl-planar-fk':'cpu-planar-fk',adapter:{vendor:adapter.info.vendor,architecture:adapter.info.architecture,device:adapter.info.device,description:adapter.info.description},gpuTiming:'CPU submission only; no GPU timestamps',physicalAcceptance:false,executionAuthority:'none'});
    worker.onmessage=({data:c})=>{
      if(c?.protocol!==FRAME_PROTOCOL||c.generation!==generation)return;
      if(c.type==='stop')stop();
      else if(c.type==='resize'&&Number.isFinite(c.width)&&Number.isFinite(c.height))resize(c.width,c.height);
      else if(c.type==='report')send('metrics',{metrics:metrics()});
      else if(c.type==='start'&&!started) {started=performance.now();frame=worker.requestAnimationFrame(draw);}
    };
    const draw=(now:number)=>{
      if(stopped)return;
      try {
        frame=worker.requestAnimationFrame(draw);
        // Limit outstanding GPU work; never build an unbounded command queue.
        if(inFlight>=2) {gpuBackpressure++;return;}
        let changed=false;
        const upload=(view:Float32Array,seq:number,t:number)=>{
          const begin=performance.now();gpu.queue.writeBuffer(config.mode==='gpu'?angles:transforms,0,view.buffer,view.byteOffset,view.byteLength);
          uploadMs+=performance.now()-begin;uploadBytes+=view.byteLength;uploads++;sequence=seq;tick=t;changed=true;
        };
        if(frames) {
          const slot=acquireLatestFrame(frames,sequence);
          if(slot>=0)try {upload(frames.views[slot],Atomics.load(frames.header,slot*4+1),Atomics.load(frames.header,slot*4+2));}finally{releaseFrame(frames,slot);}
        } else if(pending) {const f=pending;pending=undefined;try {if(f.sequence>sequence)upload(new Float32Array(f.buffer),f.sequence,f.tick);}finally{recycle(f);}}
        if(!sequence)return;
        const begin=performance.now(),encoder=gpu.createCommandEncoder();
        if(changed&&compute&&computeGroup) {const pass=encoder.beginComputePass();pass.setPipeline(compute);pass.setBindGroup(0,computeGroup);pass.dispatchWorkgroups(Math.ceil(config.chains/64));pass.end();}
        const pass=encoder.beginRenderPass({colorAttachments:[{view:context.getCurrentTexture().createView(),clearValue:{r:.035,g:.065,b:.075,a:1},loadOp:'clear',storeOp:'store'}]});
        pass.setPipeline(render);pass.setBindGroup(0,renderGroup);pass.setVertexBuffer(0,vertices);pass.setIndexBuffer(indices,'uint16');pass.drawIndexedIndirect(indirect,0);pass.end();
        gpu.queue.submit([encoder.finish()]);submitMs+=performance.now()-begin;inFlight++;
        void gpu.queue.onSubmittedWorkDone().then(()=>{inFlight--;}).catch(fault);
        draws++;if(previous&&intervals.length<8192)intervals.push(now-previous);previous=now;
        if(now>=reportAt){send('metrics',{metrics:metrics()});reportAt=now+500;}
      }catch(error){fault(error);}
    };
    send('ready',{renderer:'offscreen-webgpu'});
  }catch(error){worker.postMessage({protocol:FRAME_PROTOCOL,type:'error',generation:m?.generation,error:String(error)});stop();}
};
