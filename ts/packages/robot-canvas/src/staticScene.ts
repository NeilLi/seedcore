import {parseStrictJson} from '@seedcore/contracts';
export const STATIC_SCENE_PROFILE='seedcore.static-scene.v1';
export const STATIC_LIMITS=Object.freeze({manifestBytes:65536,tileBytes:1048576,maxTiles:21,maxDepth:3,maxVertices:4096,maxTriangles:4096,maxGeometryBytes:262144,maxResidentTiles:6,maxResidentBytes:2097152,downloads:2,decodes:1});
export interface ScenePin {uri:string;bytes:number;sha256:string}
export interface SceneAsset extends ScenePin {triangles:number;decodedGeometryBytes:number}
export interface StaticSceneManifest {schema:typeof STATIC_SCENE_PROFILE;scope:'visual_only';physicalAcceptance:false;executionAuthority:'none';origin_m:[number,number,number];tileset:ScenePin;assets:SceneAsset[]}
const fail=(message:string):never=>{throw new Error(`Static scene rejected: ${message}`);};
const keys=(v:any,names:string[])=>v!==null&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).every(k=>names.includes(k));
const int=(v:any,max:number)=>Number.isInteger(v)&&v>0&&v<=max;
const vec=(v:any,n:number)=>Array.isArray(v)&&v.length===n&&v.every((x:any)=>typeof x==='number'&&Number.isFinite(x));
export function validateScenePin(v:any,extension:string):void {
  if(!keys(v,['uri','bytes','sha256','triangles','decodedGeometryBytes'])||typeof v.uri!=='string'||!new RegExp(`^[a-z0-9][a-z0-9-]{0,63}\\.${extension}$`).test(v.uri)||!int(v.bytes,STATIC_LIMITS.tileBytes)||!/^[a-f0-9]{64}$/.test(v.sha256))fail('invalid local asset pin');
}
export function parseStaticManifest(raw:string):StaticSceneManifest {
  const m=parseStrictJson(raw) as any;
  if(new TextEncoder().encode(raw).length>STATIC_LIMITS.manifestBytes||!keys(m,['schema','scope','physicalAcceptance','executionAuthority','origin_m','tileset','assets'])||m.schema!==STATIC_SCENE_PROFILE||m.scope!=='visual_only'||m.physicalAcceptance!==false||m.executionAuthority!=='none'||!vec(m.origin_m,3)||m.origin_m.some((x:number)=>Math.abs(x)>1e9)||!Array.isArray(m.assets)||!m.assets.length||m.assets.length>STATIC_LIMITS.maxTiles)fail('manifest scope or bounds');
  validateScenePin(m.tileset,'json');if(m.tileset.bytes>STATIC_LIMITS.manifestBytes)fail('tileset byte cap');
  const seen=new Set<string>([m.tileset.uri]);
  for(const a of m.assets){validateScenePin(a,'glb');if(seen.has(a.uri)||!int(a.triangles,STATIC_LIMITS.maxTriangles)||!int(a.decodedGeometryBytes,STATIC_LIMITS.maxGeometryBytes))fail('duplicate asset or decoded geometry cap');seen.add(a.uri);}
  return structuredClone(m);
}
export async function readSceneAsset(response:Response,pin:ScenePin):Promise<Uint8Array<ArrayBuffer>> {
  if(!int(pin.bytes,STATIC_LIMITS.tileBytes)||!/^[a-f0-9]{64}$/.test(pin.sha256)||!response.ok||!response.body)fail('asset response or pin');
  const reader=response.body!.getReader(),out=new Uint8Array(pin.bytes);let offset=0;
  try{for(;;){const {done,value}=await reader.read();if(done)break;if(offset+value.length>pin.bytes)fail('asset exceeds pinned byte count');out.set(value!,offset);offset+=value!.length;}}catch(error){await reader.cancel();throw error;}finally{reader.releaseLock();}
  if(offset!==pin.bytes)fail('asset truncated');
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',out)),v=>v.toString(16).padStart(2,'0')).join('');if(hash!==pin.sha256)fail('asset SHA-256 mismatch');return out;
}
/** Explicit axis-aligned REPLACE subset; no implicit/external tilesets or URLs. */
export function validateStaticTileset(raw:string,manifest:StaticSceneManifest):any {
  const t=parseStrictJson(raw) as any;
  if(!keys(t,['asset','geometricError','root'])||!keys(t.asset,['version'])||t.asset.version!=='1.1'||!Number.isFinite(t.geometricError)||t.geometricError<0||t.geometricError>1)fail('unsupported tileset profile');
  const assets=new Map(manifest.assets.map(a=>[a.uri,a])),used=new Set<string>();let count=0;
  function visit(node:any,parent:any,depth:number) {
    if(++count>STATIC_LIMITS.maxTiles||depth>STATIC_LIMITS.maxDepth||!keys(node,['boundingVolume','geometricError','refine','content','children'])||!keys(node.boundingVolume,['box'])||!vec(node.boundingVolume.box,12)||node.refine!=='REPLACE'||!Number.isFinite(node.geometricError)||node.geometricError<0||node.geometricError>1||!keys(node.content,['uri'])||!assets.has(node.content.uri)||used.has(node.content.uri))fail('tile graph, content or refinement');
    const b=node.boundingVolume.box;
    if(b.some((n:number)=>Math.abs(n)>5)||[3,7,11].some(i=>b[i]<=0)||[4,5,6,8,9,10].some(i=>b[i]!==0))fail('only bounded axis-aligned boxes');
    if(parent){if(node.geometricError>parent.geometricError)fail('increasing child error');const p=parent.boundingVolume.box;for(let i=0;i<3;i++)if(Math.abs(b[i]-p[i])+b[3+i*4]>p[3+i*4]+1e-10)fail('child outside parent bounds');}
    used.add(node.content.uri);
    if(node.children!==undefined){if(!Array.isArray(node.children)||node.children.length<1||node.children.length>8)fail('invalid children');for(const child of node.children)visit(child,node,depth+1);}
    else if(node.geometricError!==0)fail('leaf must have zero error');
  }
  visit(t.root,null,0);if(used.size!==assets.size||t.geometricError<t.root.geometricError)fail('unreferenced assets or root error');return t;
}
/** Closed texture-free mesh subset; no arbitrary GLTFLoader extensions or URIs. */
export function inspectStaticGlb(bytes:Uint8Array<ArrayBuffer>,pin:SceneAsset):{document:any;decodedGeometryBytes:number;triangles:number;min:number[];max:number[]} {
  if(bytes.length<28||bytes.length>STATIC_LIMITS.tileBytes)fail('GLB byte bounds');
  const v=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength),jsonLength=v.getUint32(12,true),binHeader=20+jsonLength;
  if(v.getUint32(0,true)!==0x46546c67||v.getUint32(4,true)!==2||v.getUint32(8,true)!==bytes.length||jsonLength>65536||jsonLength%4||binHeader+8>bytes.length||v.getUint32(16,true)!==0x4e4f534a||v.getUint32(binHeader+4,true)!==0x004e4942||binHeader+8+v.getUint32(binHeader,true)!==bytes.length)fail('GLB header/chunks');
  const d=parseStrictJson(new TextDecoder('utf-8',{fatal:true}).decode(bytes.subarray(20,binHeader))) as any;
  if(!keys(d,['asset','extensionsUsed','extensionsRequired','scene','scenes','nodes','meshes','materials','buffers','bufferViews','accessors'])||!keys(d.asset,['version','generator'])||d.asset?.version!=='2.0'||typeof d.asset.generator!=='string'||d.asset.generator.length>160||d.scene!==0||d.nodes?.length!==1||JSON.stringify(d.nodes[0])!=='{"mesh":0}'||d.scenes?.length!==1||JSON.stringify(d.scenes[0])!=='{"nodes":[0]}'||d.meshes?.length!==1||!keys(d.meshes[0],['primitives'])||d.meshes[0].primitives?.length!==1||d.materials?.length!==1||d.buffers?.length!==1||Object.keys(d.buffers[0]).join(',')!=='byteLength'||d.bufferViews?.length!==1||d.accessors?.length!==3)fail('unsupported GLB structure; textures/animations/external resources not admitted');
  const p=d.meshes[0].primitives[0],ext=p.extensions?.KHR_draco_mesh_compression;
  if(JSON.stringify(d.extensionsUsed)!=='["KHR_draco_mesh_compression"]'||JSON.stringify(d.extensionsRequired)!=='["KHR_draco_mesh_compression"]'||p.mode!==4||p.indices!==2||p.material!==0||JSON.stringify(p.attributes)!=='{"POSITION":0,"NORMAL":1}'||!keys(p,['attributes','indices','material','mode','extensions'])||!keys(p.extensions,['KHR_draco_mesh_compression'])||!keys(ext,['bufferView','attributes'])||ext.bufferView!==0||!keys(ext.attributes,['POSITION','NORMAL'])||![ext.attributes.POSITION,ext.attributes.NORMAL].every(n=>Number.isInteger(n)&&n>=0&&n<16)||ext.attributes.POSITION===ext.attributes.NORMAL)fail('unsupported Draco primitive');
  const [pos,normal,indices]=d.accessors,view=d.bufferViews[0];
  if(!int(pos.count,STATIC_LIMITS.maxVertices)||normal.count!==pos.count||pos.type!=='VEC3'||normal.type!=='VEC3'||pos.componentType!==5126||normal.componentType!==5126||indices.type!=='SCALAR'||indices.componentType!==5125||!int(indices.count,STATIC_LIMITS.maxTriangles*3)||indices.count%3||[pos,normal,indices].some(a=>!keys(a,['componentType','count','type','min','max']))||!vec(pos.min,3)||!vec(pos.max,3)||pos.min.some((n:number,i:number)=>Math.abs(n)>5||n>pos.max[i]||Math.abs(pos.max[i])>5)||!keys(view,['buffer','byteOffset','byteLength'])||view.buffer!==0||view.byteOffset!==0||!int(view.byteLength,STATIC_LIMITS.tileBytes)||d.buffers[0].byteLength!==view.byteLength||view.byteLength>v.getUint32(binHeader,true))fail('decoded bounds or Draco buffer view');
  const mat=d.materials[0],pbr=mat.pbrMetallicRoughness;
  if(!keys(mat,['pbrMetallicRoughness','doubleSided'])||mat.doubleSided!==false||!keys(pbr,['baseColorFactor','metallicFactor','roughnessFactor'])||!vec(pbr.baseColorFactor,4)||pbr.baseColorFactor.some((n:number)=>n<0||n>1)||![pbr.metallicFactor,pbr.roughnessFactor].every(n=>Number.isFinite(n)&&n>=0&&n<=1))fail('material outside texture-free profile');
  const decodedGeometryBytes=pos.count*24+indices.count*4,triangles=indices.count/3;
  if(decodedGeometryBytes!==pin.decodedGeometryBytes||triangles!==pin.triangles||decodedGeometryBytes>STATIC_LIMITS.maxGeometryBytes)fail('declared decoded geometry budget mismatch');
  return {document:d,decodedGeometryBytes,triangles,min:pos.min,max:pos.max};
}
export function sceneAssetUrl(uri:string,base:string,manifest:StaticSceneManifest):string {
  const root=new URL(base),names=[manifest.tileset.uri,...manifest.assets.map(a=>a.uri)],allowed=names.map(name=>new URL(name,root).href),url=new URL(uri,root);
  if(!names.includes(uri)&&!allowed.includes(uri)||url.origin!==root.origin||url.search||url.hash||!allowed.includes(url.href))fail('asset URL outside pinned allowlist');return url.href;
}
/** glTF Y-up extrema -> tileset Z-up, with a small codec/float tolerance. */
export function assertStaticContentBounds(min:readonly number[],max:readonly number[],box:readonly number[]):void {
  if(!vec([...min],3)||!vec([...max],3)||!vec([...box],12)||min.some((n,i)=>n>max[i]))fail('invalid content bounds');
  const lo=[min[0],-max[2],min[1]],hi=[max[0],-min[2],max[1]];
  for(let i=0;i<3;i++)if(lo[i]<box[i]-box[3+i*4]-2e-5||hi[i]>box[i]+box[3+i*4]+2e-5)fail('decoded content outside tile bounds');
}
/** Subtract global f64 coordinates before converting small local offsets to f32. */
export function cameraRelative(origin:readonly number[],camera:readonly number[],local:readonly number[]=[0,0,0]):Float32Array {
  if(!vec([...origin],3)||!vec([...camera],3)||!vec([...local],3))fail('invalid RTC coordinates');return new Float32Array(origin.map((n,i)=>(n-camera[i])+local[i]));
}
export function screenSpaceError(error:number,height:number,distance:number,fovRadians:number):number {
  if(![error,height,distance,fovRadians].every(Number.isFinite)||error<0||height<=0||distance<0||fovRadians<=0||fovRadians>=Math.PI)fail('invalid SSE inputs');return error===0?0:distance===0?Infinity:error*height/(distance*2*Math.tan(fovRadians/2));
}
