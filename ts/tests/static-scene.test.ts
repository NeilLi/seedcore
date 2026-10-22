import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {STATIC_LIMITS,parseStaticManifest,validateStaticTileset,inspectStaticGlb,readSceneAsset,sceneAssetUrl,cameraRelative,screenSpaceError,assertStaticContentBounds} from '../packages/robot-canvas/src/staticScene.js';
const root=new URL('../../packages/scene-fixtures/mini-workbench/',import.meta.url),raw=readFileSync(new URL('scene.json',root),'utf8'),manifest=parseStaticManifest(raw),tilesetRaw=readFileSync(new URL('tileset.json',root),'utf8');
const assetBytes=(uri:string)=>Uint8Array.from(readFileSync(new URL(uri,root)));
function rebuildGlb(bytes:Uint8Array<ArrayBuffer>,edit:(doc:any)=>void):Uint8Array<ArrayBuffer>{
  const v=new DataView(bytes.buffer),n=v.getUint32(12,true),doc=JSON.parse(new TextDecoder().decode(bytes.subarray(20,20+n)));edit(doc);
  const text=new TextEncoder().encode(JSON.stringify(doc)),json=new Uint8Array(Math.ceil(text.length/4)*4);json.fill(32);json.set(text);
  const binary=bytes.subarray(20+n),out=new Uint8Array(20+json.length+binary.length),h=new DataView(out.buffer);out.set(bytes.subarray(0,20));h.setUint32(8,out.length,true);h.setUint32(12,json.length,true);out.set(json,20);out.set(binary,20+json.length);return out;
}
test('static scene: exact, non-authoritative pins and explicit bounded hierarchy',()=>{
  const before=JSON.stringify(manifest),t=validateStaticTileset(tilesetRaw,manifest);assert.equal(t.asset.version,'1.1');assert.equal(t.root.children.length,4);assert.equal(manifest.scope,'visual_only');assert.equal(manifest.physicalAcceptance,false);assert.equal(manifest.executionAuthority,'none');
  for(const a of [manifest.tileset,...manifest.assets]){const b=readFileSync(new URL(a.uri,root));assert.equal(b.length,a.bytes);assert.equal(createHash('sha256').update(b).digest('hex'),a.sha256);}
  const runtime=JSON.parse(readFileSync(new URL('../decoder-runtime.json',root),'utf8'));assert.equal(runtime.threeVersion,'0.181.1');
  for(const pin of runtime.assets){const b=readFileSync(new URL('../node_modules/three/examples/jsm/libs/draco/gltf/'+pin.uri,import.meta.url));assert.equal(b.length,pin.bytes);assert.equal(createHash('sha256').update(b).digest('hex'),pin.sha256);}
  assert.equal(JSON.stringify(manifest),before);
});
test('static scene: malformed scope, absolute/traversal assets, duplicates and budgets fail',()=>{
  for(const edit of [(d:any)=>d.physicalAcceptance=true,(d:any)=>d.executionAuthority='motor',(d:any)=>d.assets[0].uri='../coarse.glb',(d:any)=>d.assets[0].uri='https://outside.test/coarse.glb',(d:any)=>d.assets.push(d.assets[0]),(d:any)=>d.assets[0].bytes=2**30,(d:any)=>d.assets[0].decodedGeometryBytes=2**30,(d:any)=>d.origin_m[0]=1e12,(d:any)=>d.token={allow:true}]){const d=JSON.parse(raw);edit(d);assert.throws(()=>parseStaticManifest(JSON.stringify(d)));}
});
test('static scene: reject external/implicit/additive/transformed/oversized tile graphs',()=>{
  for(const edit of [(d:any)=>d.root.refine='ADD',(d:any)=>d.root.content.uri='outside.json',(d:any)=>d.root.implicitTiling={},(d:any)=>d.root.transform=Array(16).fill(0),(d:any)=>d.root.children[0].boundingVolume.box[0]=9,(d:any)=>d.root.children[0].geometricError=.1,(d:any)=>d.root.children.push(d.root.children[0]),(d:any)=>d.root.children[0].children=Array(9).fill(d.root.children[1]),(d:any)=>d.extensionsRequired=['unknown']]){const d=JSON.parse(tilesetRaw);edit(d);assert.throws(()=>validateStaticTileset(JSON.stringify(d),manifest));}
});
test('static scene: exact URL allowlist rejects alternate origins, queries and traversal',()=>{
  const base='http://127.0.0.1:8767/scene-assets/';assert.equal(sceneAssetUrl('coarse.glb',base,manifest),base+'coarse.glb');assert.equal(sceneAssetUrl(base+'coarse.glb',base,manifest),base+'coarse.glb');
  for(const uri of ['../scene-assets/coarse.glb','./coarse.glb','coarse.glb?token=x','coarse.glb#fragment','https://outside.test/coarse.glb','//outside.test/coarse.glb','unlisted.glb','data:application/octet-stream,abc'])assert.throws(()=>sceneAssetUrl(uri,base,manifest));
});
test('static scene: corrupt, oversized and truncated bytes fail before a loader sees them',async()=>{
  const pin=manifest.assets[0],bytes=assetBytes(pin.uri);assert.deepEqual(await readSceneAsset(new Response(bytes),pin),bytes);
  const corrupt=bytes.slice();corrupt[corrupt.length-1]^=1;await assert.rejects(readSceneAsset(new Response(corrupt),pin),/SHA-256/);
  await assert.rejects(readSceneAsset(new Response(new Uint8Array(bytes.length+1)),pin),/exceeds/);await assert.rejects(readSceneAsset(new Response(bytes.subarray(0,2)),pin),/truncated/);await assert.rejects(readSceneAsset(new Response('',{status:404}),pin));
});
test('static scene: compression is mandatory; decoded geometry and external resource bounds remain mandatory',()=>{
  const pin=manifest.assets[1],bytes=assetBytes(pin.uri),found=inspectStaticGlb(bytes,pin);assert.equal(found.triangles,780);assert.equal(found.decodedGeometryBytes,46800);
  for(const edit of [(d:any)=>d.buffers[0].uri='https://outside.test/mesh.bin',(d:any)=>d.images=[{uri:'image.png'}],(d:any)=>d.skins=[{}],(d:any)=>d.animations=[{}],(d:any)=>d.nodes[0].translation=[0,0,1],(d:any)=>d.accessors[0].count=1e8,(d:any)=>d.accessors[2].count=1e8,(d:any)=>d.extensionsRequired=[] ,(d:any)=>d.meshes[0].primitives[0].extensions.KHR_draco_mesh_compression.bufferView=999,(d:any)=>d.materials[0].pbrMetallicRoughness.baseColorTexture={index:0}])assert.throws(()=>inspectStaticGlb(rebuildGlb(bytes,edit),pin));
  assert.throws(()=>inspectStaticGlb(bytes,{...pin,triangles:1}));assert.throws(()=>inspectStaticGlb(new TextEncoder().encode('solid raw STL'),pin));
});
test('static scene: Y-up geometry must fit its Z-up tile volume before and after decode',()=>{
  const tiles=validateStaticTileset(tilesetRaw,manifest),boxes=new Map<string,number[]>();const visit=(t:any)=>{boxes.set(t.content.uri,t.boundingVolume.box);for(const c of t.children??[])visit(c);};visit(tiles.root);
  for(const pin of manifest.assets){const info=inspectStaticGlb(assetBytes(pin.uri),pin);assert.doesNotThrow(()=>assertStaticContentBounds(info.min,info.max,boxes.get(pin.uri)!));}
  const box=[0,0,0,.1,0,0,0,.2,0,0,0,.3];assert.doesNotThrow(()=>assertStaticContentBounds([-.1,-.3,-.2],[.1,.3,.2],box));
  assert.throws(()=>assertStaticContentBounds([-.1,-.3,-.3],[.1,.3,.3],box));assert.throws(()=>assertStaticContentBounds([0,0,0],[Infinity,0,0],box));
});
test('static scene: native Draco decode independently confirms reviewed vertex/triangle/position budgets',async()=>{
  const req=createRequire(new URL('../apps/mini-studio/package.json',import.meta.url)),d=await req('draco3d').createDecoderModule({});
  for(const pin of manifest.assets){const bytes=assetBytes(pin.uri),info=inspectStaticGlb(bytes,pin),doc=info.document,n=new DataView(bytes.buffer).getUint32(12,true),payload=bytes.subarray(28+n,28+n+doc.bufferViews[0].byteLength),buffer=new d.DecoderBuffer(),decoder=new d.Decoder(),mesh=new d.Mesh();
    try{buffer.Init(payload,payload.length);const status=decoder.DecodeBufferToMesh(buffer,mesh);assert.ok(status.ok());assert.equal(mesh.num_points(),doc.accessors[0].count);assert.equal(mesh.num_faces(),pin.triangles);const a=decoder.GetAttributeByUniqueId(mesh,doc.meshes[0].primitives[0].extensions.KHR_draco_mesh_compression.attributes.POSITION),out=new d.DracoFloat32Array();
      try{assert.ok(decoder.GetAttributeFloatForAllPoints(mesh,a,out));for(let i=0;i<out.size();i++){const axis=i%3,value=out.GetValue(i);assert.ok(value>=info.min[axis]-2e-5&&value<=info.max[axis]+2e-5);}}finally{d.destroy(out);}
    }finally{d.destroy(mesh);d.destroy(decoder);d.destroy(buffer);}
  }
});
test('static scene: SSE changes with distance, viewport, field-of-view and geometric error',()=>{
  assert.ok(Math.abs(screenSpaceError(.1,1000,10,Math.PI/2)-5)<1e-12);assert.equal(screenSpaceError(0,1000,0,1),0);assert.equal(screenSpaceError(.1,1000,0,1),Infinity);
  assert.equal(screenSpaceError(.1,1000,10,1)*2,screenSpaceError(.1,2000,10,1));assert.ok(screenSpaceError(.1,1000,1,1)>screenSpaceError(.1,1000,10,1));
  for(const args of [[-1,100,1,1],[1,0,1,1],[1,100,-1,1],[1,100,1,0],[1,100,1,Math.PI],[Infinity,100,1,1]])assert.throws(()=>screenSpaceError(...args as [number,number,number,number]));
});
test('static scene: RTC preserves millimeter offsets at planetary-scale origins',()=>{
  const origin=[6371000,1000000,-2000000],camera=origin.map(n=>n+.001),rtc=cameraRelative(origin,camera);
  assert.ok(rtc.every(v=>Math.abs(v+.001)<1e-8));assert.equal(Math.fround(origin[0]+.001)-Math.fround(origin[0]),0);
  const shifted=cameraRelative(origin.map(n=>n+1e7),camera.map(n=>n+1e7));assert.ok(shifted.every((v,i)=>Math.abs(v-rtc[i])<2e-9));assert.throws(()=>cameraRelative([Infinity,0,0],camera));
  assert.equal(STATIC_LIMITS.decodes,1);assert.equal(STATIC_LIMITS.downloads,2);
});
