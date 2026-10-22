import * as THREE from 'three';
import {TilesRenderer} from '3d-tiles-renderer/three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {DRACOLoader} from 'three/addons/loaders/DRACOLoader.js';
import {STATIC_LIMITS,parseStaticManifest,validateStaticTileset,inspectStaticGlb,readSceneAsset,sceneAssetUrl,screenSpaceError,assertStaticContentBounds,type ScenePin} from '@seedcore/robot-canvas/static';
import {sharedFrames,acquireLatestFrame,releaseFrame,FRAME_PROTOCOL} from '@seedcore/wasm-sim-bridge/visual';
declare const __STATIC_MANIFEST_PIN__:ScenePin;
declare const __STATIC_DECODER_PINS__:ScenePin[];
const PROTOCOL='seedcore.scene-lab.v1';
const w=globalThis as unknown as {onmessage:((e:MessageEvent)=>void)|null;postMessage:(v:unknown)=>void;requestAnimationFrame:(cb:(t:number)=>void)=>number;cancelAnimationFrame:(n:number)=>void};

/** Pinned 0.5.3 compatibility override: upstream uses window.location in this
 * virtual method. Only absolute, prevalidated local URLs enter the worker. No
 * window/document shim, source monkey-patch or control-boundary modification. */
class WorkerTilesRenderer extends TilesRenderer {
  preprocessTileset(json:any,url:string,parent:any=null):void {
    if(json.asset.version!=='1.1')throw Error('Unsupported static tile version');
    (this as any).preprocessNode(json.root,new URL('.',url).href.replace(/\/$/,''),parent);
  }
}
let initialized=false,ended=false,frame=0,renderer:THREE.WebGLRenderer|undefined,tiles:WorkerTilesRenderer|undefined,draco:DRACOLoader|undefined;
const abort=new AbortController(),blobs:string[]=[];
let scene:THREE.Scene|undefined;
function dispose() {
  if(ended)return;ended=true;abort.abort();w.cancelAnimationFrame(frame);tiles?.dispose();draco?.dispose();
  scene?.traverse(o=>{if(o instanceof THREE.Mesh){o.geometry.dispose();for(const m of Array.isArray(o.material)?o.material:[o.material])m.dispose();}});
  renderer?.dispose();for(const url of blobs)URL.revokeObjectURL(url);
}
w.onmessage=async({data:m})=>{
  if(m?.type==='stop'){dispose();return;}if(initialized)return;initialized=true;
  const generation=m?.generation,send=(type:string,extra:object={})=>w.postMessage({protocol:PROTOCOL,type,generation,...extra});
  const fault=(e:unknown)=>{if(!ended){send('error',{error:String(e)});dispose();}};
  try {
    if(m?.protocol!==PROTOCOL||m.type!=='init'||!Number.isInteger(generation)||generation<1||!(m.canvas instanceof OffscreenCanvas)||![3,6].includes(m.cacheTiles)||!Number.isInteger(m.seconds)||m.seconds<2||m.seconds>30)throw Error('Invalid scene worker initialization');
    const config={mode:'shared' as const,chains:1,hz:500 as const,seconds:m.seconds};
    if(!(m.shared instanceof SharedArrayBuffer))throw Error('Shared physics preview missing');
    const frames=sharedFrames(config,m.shared),canvas:OffscreenCanvas=m.canvas;
    const raw=await readSceneAsset(await fetch('/scene-assets/scene.json',{signal:abort.signal,redirect:'error'}),__STATIC_MANIFEST_PIN__);
    const manifest=parseStaticManifest(new TextDecoder('utf-8',{fatal:true}).decode(raw)),base=new URL('/scene-assets/',location.href).href;
    if(ended)return;
    renderer=new THREE.WebGLRenderer({canvas:canvas as unknown as HTMLCanvasElement,antialias:true});renderer.setClearColor('#0c1c20');
    canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();fault('Render context lost; restart required');});
    scene=new THREE.Scene();scene.add(new THREE.HemisphereLight(0xe7fff6,0x25393d,3));const light=new THREE.DirectionalLight(0xffffff,3);light.position.set(2,-3,4);scene.add(light);
    const camera=new THREE.PerspectiveCamera(45,1,.01,30);camera.up.set(0,0,1);
    const active=new THREE.Group();active.name='synthetic-active-actor';
    const actor=new THREE.InstancedMesh(new THREE.BoxGeometry(1,1,1),new THREE.MeshStandardMaterial({color:0xf6b34e,roughness:.4}),3);actor.frustumCulled=false;active.add(actor);scene.add(active);
    const baseMesh=new THREE.Mesh(new THREE.CylinderGeometry(.027,.035,.018,16),new THREE.MeshStandardMaterial({color:0x6baeca}));baseMesh.rotation.x=Math.PI/2;baseMesh.position.z=-.009;active.add(baseMesh);
    tiles=new WorkerTilesRenderer(sceneAssetUrl(manifest.tileset.uri,base,manifest));scene.add(tiles.group);tiles.group.name='visual-only-static-world';
    tiles.errorTarget=16;tiles.maxDepth=STATIC_LIMITS.maxDepth;tiles.maxTilesProcessed=32;tiles.loadSiblings=false;tiles.loadAncestors=true;
    tiles.lruCache.maxSize=m.cacheTiles;tiles.lruCache.minSize=1;tiles.lruCache.maxBytesSize=STATIC_LIMITS.maxResidentBytes;tiles.lruCache.minBytesSize=0;
    tiles.downloadQueue.maxJobsPerOrigin=STATIC_LIMITS.downloads;tiles.parseQueue.maxJobs=STATIC_LIMITS.decodes;tiles.processNodeQueue.maxJobs=8;
    const urls=new Map<string,string>();
    // Decoder bootstrap is pinned before executable wrapper text enters a blob.
    for(const pin of __STATIC_DECODER_PINS__){const data=await readSceneAsset(await fetch('/scene-decoders/'+pin.uri,{signal:abort.signal,redirect:'error'}),pin);if(ended)return;const url=URL.createObjectURL(new Blob([data],{type:pin.uri.endsWith('.wasm')?'application/wasm':'application/javascript'}));blobs.push(url);urls.set(new URL('/scene-decoders/'+pin.uri,location.href).href,url);}
    tiles.manager.setURLModifier(url=>{const allowed=urls.get(new URL(url,location.href).href);if(!allowed)throw Error('Decoder or nested resource outside pinned allowlist');return allowed;});
    draco=new DRACOLoader(tiles.manager).setDecoderPath('/scene-decoders/').setDecoderConfig({type:'wasm'}).setWorkerLimit(1);
    const gltf=new GLTFLoader(tiles.manager).setDRACOLoader(draco);tiles.manager.addHandler(/\.(glb|gltf)$/i,gltf);
    let distance=5,yaw=-.8,pitch=.9,sequence=0,tick=0,draws=0,downloadBytes=0,inFlight=0,peakDownloads=0,peakResidentTiles=0,evictions=0,failures=0,staticStatus='loading',lastError='';
    const loaded=new Map<any,{uri:string;bytes:number;triangles:number}>(),events:object[]=[],tileBoxes=new Map<string,number[]>();
    const record=(event:object)=>{if(events.length<64)events.push(event);};
    tiles.registerPlugin({name:'seedcore-pinned-static-assets',priority:-100,
      fetchData:async(url:string,options:RequestInit={})=>{
        const canonical=sceneAssetUrl(url,base,manifest),name=new URL(canonical).pathname.split('/').at(-1)!,pin=name===manifest.tileset.uri?manifest.tileset:manifest.assets.find(a=>a.uri===name)!;
        const signal=AbortSignal.any([abort.signal,...(options.signal?[options.signal]:[]),AbortSignal.timeout(5000)]);
        inFlight++;peakDownloads=Math.max(peakDownloads,inFlight);
        try {
          const bytes=await readSceneAsset(await fetch(canonical,{signal,redirect:'error',credentials:'same-origin'}),pin);if(ended||signal.aborted)throw Error('Stale static load');downloadBytes+=bytes.length;
          if(name===manifest.tileset.uri){const doc=validateStaticTileset(new TextDecoder('utf-8',{fatal:true}).decode(bytes),manifest);const collect=(tile:any)=>{tileBoxes.set(tile.content.uri,tile.boundingVolume.box);for(const c of tile.children??[])collect(c);};collect(doc.root);return new Response(JSON.stringify(doc),{headers:{'Content-Type':'application/json'}});}
          const info=inspectStaticGlb(bytes,pin as any),box=tileBoxes.get(name);if(!box)throw Error('Static content missing tile bounds');assertStaticContentBounds(info.min,info.max,box);return new Response(bytes,{headers:{'Content-Type':'model/gltf-binary'}});
        }finally{inFlight--;}
      }
    });
    tiles.addEventListener('load-model',({scene:model,tile,url})=>{
      const pin=manifest.assets.find(a=>new URL(a.uri,base).href===url);let bytes=0,triangles=0,meshes=0;
      try {
        model.traverse(o=>{if(o instanceof THREE.Mesh){const geometry=o.geometry as THREE.BufferGeometry;meshes++;for(const a of Object.values(geometry.attributes))bytes+=a.array.byteLength;if(geometry.index){bytes+=geometry.index.array.byteLength;triangles+=geometry.index.count/3;}geometry.computeBoundingBox();if(!geometry.boundingBox||!pin)throw Error('Decoded static bounds missing');assertStaticContentBounds(geometry.boundingBox.min.toArray(),geometry.boundingBox.max.toArray(),tileBoxes.get(pin.uri)!);}});
      }catch(error){fault(error);return;}
      if(!pin||meshes!==1||bytes!==pin.decodedGeometryBytes||triangles!==pin.triangles){fault('Decoded geometry does not match reviewed fixture budget');return;}
      loaded.set(tile,{uri:pin.uri,bytes,triangles});peakResidentTiles=Math.max(peakResidentTiles,loaded.size);staticStatus=failures?'degraded':'ready';record({type:'loaded',uri:pin.uri});
    });
    tiles.addEventListener('dispose-model',({tile})=>{if(loaded.has(tile)){record({type:'evicted',uri:loaded.get(tile)!.uri});loaded.delete(tile);evictions++;}});
    tiles.addEventListener('load-error',({error,url})=>{
      failures++;lastError=String(error);staticStatus='degraded';
      // Upstream considers FAILED children "finished" for REPLACE traversal.
      // Latch the public depth cap at the reviewed root, preserving coarse
      // coverage after a failed refinement. Only a new rehearsal clears it.
      tiles!.maxDepth=1;
      record({type:'load-error',url:String(url),error:lastError});
    });
    tiles.setCamera(camera);
    const resize=(width:number,height:number)=>{if(!Number.isFinite(width)||!Number.isFinite(height))throw Error('Invalid viewport');renderer!.setSize(Math.max(1,Math.min(2048,Math.round(width))),Math.max(1,Math.min(1536,Math.round(height))),false);camera.aspect=canvas.width/canvas.height;camera.updateProjectionMatrix();tiles!.setResolutionFromRenderer(camera,renderer!);};resize(m.width,m.height);
    const view=(v:any)=>{if(![v.distance,v.yaw,v.pitch,v.sse].every(Number.isFinite)||v.distance<.5||v.distance>12||Math.abs(v.yaw)>Math.PI||v.pitch<.2||v.pitch>1.4||v.sse<1||v.sse>64)throw Error('Invalid view');distance=v.distance;yaw=v.yaw;pitch=v.pitch;tiles!.errorTarget=v.sse;};
    const matrix=new THREE.Matrix4();let reportAt=0,started=false;
    const metrics=()=>{
      const cameraLocal=camera.position.toArray(),bounds=[.6,.6,.04],center=[0,0,-.04],toBounds=Math.hypot(...cameraLocal.map((n,i)=>Math.max(0,Math.abs(n-center[i])-bounds[i])));
      const visible=[...tiles!.visibleTiles].map(t=>loaded.get(t)).filter((a):a is NonNullable<typeof a>=>Boolean(a));
      const rootSse=screenSpaceError(.06,canvas.height,toBounds,Math.PI/4),cacheConstrained=loaded.size>=m.cacheTiles&&rootSse>tiles!.errorTarget&&visible.some(a=>a.uri==='coarse.glb');
      return {scope:'synthetic_visual_streaming',physicalAcceptance:false,executionAuthority:'none',profile:'seedcore.static-scene.v1',renderer:'three-webgl2-offscreen',tilesRendererVersion:'0.5.3',staticStatus,lastError,failures,coarseFallbackLatched:failures>0,cacheConstrained,tick,sequence,draws,visibleTiles:visible.length,visibleUris:visible.map(a=>a.uri),visibleTriangles:visible.reduce((s,a)=>s+a.triangles,0),residentTiles:loaded.size,peakResidentTiles,residentGeometryBytes:[...loaded.values()].reduce((s,a)=>s+a.bytes,0),downloadBytes,peakDownloads,evictions,cacheTiles:m.cacheTiles,sseTarget:tiles!.errorTarget,rootSse,origin_m:manifest.origin_m,cameraLocal,events:[...events],activeActors:1,activeLinks:3};
    };
    w.onmessage=({data:c})=>{
      if(c?.protocol!==PROTOCOL||c.generation!==generation||ended)return;
      try {
        if(c.type==='stop')dispose();else if(c.type==='view')view(c);else if(c.type==='resize')resize(c.width,c.height);
        else if(c.type==='start'&&!started){started=true;frame=w.requestAnimationFrame(render);}
        else if(c.type==='report')send('metrics',{metrics:metrics()});
      }catch(error){fault(error);}
    };
    const render=(now:number)=>{
      if(ended)return;
      try {
        frame=w.requestAnimationFrame(render);
        // Subtract f64 global origin before any float32 GPU matrix conversion.
        const local=[distance*Math.cos(pitch)*Math.cos(yaw),distance*Math.cos(pitch)*Math.sin(yaw),distance*Math.sin(pitch)];
        camera.position.set(...local.map((n,i)=>(manifest.origin_m[i]+n)-manifest.origin_m[i]) as [number,number,number]);camera.lookAt(0,0,0);camera.updateMatrixWorld();
        const slot=acquireLatestFrame(frames,sequence);
        if(slot>=0)try{sequence=Atomics.load(frames.header,slot*4+1);tick=Atomics.load(frames.header,slot*4+2);for(let i=0;i<3;i++){matrix.fromArray(frames.views[slot],i*16);actor.setMatrixAt(i,matrix);}actor.instanceMatrix.needsUpdate=true;}finally{releaseFrame(frames,slot);}
        tiles!.update();renderer!.render(scene!,camera);draws++;
        if(now>=reportAt){send('metrics',{metrics:metrics()});reportAt=now+250;}
      }catch(error){fault(error);}
    };
    send('ready');
  }catch(error){fault(error);}
};
