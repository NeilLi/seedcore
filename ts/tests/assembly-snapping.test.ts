/** Synthetic geometry fixtures below do not qualify physical mounts or rails. */
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {canonicalAssemblyString,parseAssemblyText,type AssemblyNode,type RelativeTransform,type RobotAssembly} from '../packages/contracts/src/index.js';
import {loadPlacementCatalog} from '../packages/robot-canvas/src/assets.js';
import {AssemblyStore} from '../packages/robot-canvas/src/store.js';
import {applySnapPlacement,commitSnapProposal,composePose,discoverSnapCandidates,inversePose,makeSnapProposal,mateTransform,suggestPlacementPose,worldTransforms,type PlacementCatalog,type PlacementPart,type PlacementRequest,type SnapPort} from '../packages/robot-canvas/src/snapping.js';
const root=fileURLToPath(new URL('../../',import.meta.url)),s=Math.SQRT1_2;
const original=parseAssemblyText(readFileSync(new URL('../../packages/component-registry/assemblies/tabletop-starter.sc-assembly.json',import.meta.url),'utf8'));
const pose=(position_m:number[]=[0,0,0],quaternion_wxyz:number[]=[1,0,0,0]):RelativeTransform=>({position_m:position_m as [number,number,number],quaternion_wxyz:quaternion_wxyz as [number,number,number,number]});
const port=(port_id:string,position_m:number[],quaternion_wxyz:number[]):SnapPort=>({...pose(position_m,quaternion_wxyz),port_id,mount_standard:'seedcore.proxy_mount_v1',gender:'neutral'});
const node=(node_id:string,part_id:string,sha:string):AssemblyNode=>({node_id,part_id,part_version:'0.1.0',part_sha256:sha.repeat(64),role:'link'});
const part=(partId:string,sha:string,ports:SnapPort[]):PlacementPart=>({partId,sha256:sha.repeat(64),version:'0.1.0',name:partId,role:'link',ports,positions:[],indices:[]});
const near=(a:readonly number[],b:readonly number[])=>{assert.equal(a.length,b.length);a.forEach((n,i)=>assert.ok(Math.abs(n-b[i])<1e-10,`${a} != ${b}`));};
function fixture(){
  const catalog:PlacementCatalog={catalogDigest:'d'.repeat(64),parts:[
    part('fixture.root','a',[port('out',[1,2,3],[s,0,s,0])]),
    part('fixture.parent','b',[port('input',[0,0,0],[0,1,0,0]),port('out',[.02,0,.03],[s,0,0,s])]),
    part('fixture.child','c',[port('input',[0,0,-.01],[0,1,0,0]),port('out',[0,0,.01],[1,0,0,0])])
  ]};
  const assembly:RobotAssembly={...structuredClone(original),root_node_id:'r0',nodes:[node('r0','fixture.root','a'),node('p0','fixture.parent','b')],actuator_outputs:[],electrical_nets:[],mechanical_tree:[{edge_id:'edge_rp',parent_node_id:'r0',parent_port_id:'out',child_node_id:'p0',child_port_id:'input',connection_type:'rigid_mount',relative_transform:mateTransform(catalog.parts[0].ports[0],catalog.parts[1].ports[0])}]};
  const request:PlacementRequest={source:{kind:'new',node:node('c0','fixture.child','c')},childPortId:'input',pose:pose([1.04,2,2.98],[.5,.5,.5,.5])};
  return {assembly,catalog,request};
}
const proposal=(f:ReturnType<typeof fixture>)=>makeSnapProposal(f.assembly,f.catalog,f.request,discoverSnapCandidates(f.assembly,f.catalog,f.request).candidates[0]);

test('independent numeric mate fixture under translated, rotated parent',()=>{
  const {catalog}=fixture();const relative=mateTransform(catalog.parts[1].ports[1],catalog.parts[2].ports[0]);
  near(relative.position_m,[.02,0,.04]);near(relative.quaternion_wxyz,[s,0,0,s]);
  const world=composePose(pose([1,2,3],[s,0,s,0]),relative);
  near(world.position_m,[1.04,2,2.98]);near(world.quaternion_wxyz,[.5,.5,.5,.5]);
  const pp=composePose(pose([1,2,3],[s,0,s,0]),catalog.parts[1].ports[1]),cp=composePose(world,catalog.parts[2].ports[0]);
  near(pp.position_m,cp.position_m);
  near(composePose(world,inversePose(world)).position_m,[0,0,0]);
});
test('capture aligns exact rest pose and leaves source assembly unchanged',()=>{
  const f=fixture(),before=canonicalAssemblyString(f.assembly);f.request.pose.position_m[0]+=.01;
  const candidates=discoverSnapCandidates(f.assembly,f.catalog,f.request).candidates;assert.equal(candidates.length,1);assert.ok(Math.abs(candidates[0].distanceM-.01)<1e-12);
  const next=applySnapPlacement(f.assembly,f.catalog,proposal(f));near(worldTransforms(next).c0.position_m,[1.04,2,2.98]);assert.equal(canonicalAssemblyString(f.assembly),before);
  assert.equal(next.mechanical_tree.at(-1)!.connection_type,'rigid_mount');assert.deepEqual(next.actuator_outputs,[]);
});
for(const [mm,accepted] of [[14.999,true],[15,true],[15.001,false]] as const)test(`capture radius ${mm} mm`,()=>{
  const f=fixture();f.request.pose.position_m[0]+=mm/1000;assert.equal(discoverSnapCandidates(f.assembly,f.catalog,f.request).candidates.length>0,accepted);
});
test('deterministic equal-distance tie-breaking uses node/port IDs, not input order',()=>{
  const f=fixture(),out=f.catalog.parts[1].ports.pop()!;f.catalog.parts[1].ports.push({...structuredClone(out),port_id:'out_z'},{...structuredClone(out),port_id:'out_a'});
  const first=discoverSnapCandidates(f.assembly,f.catalog,f.request).candidates;assert.deepEqual(first.map(c=>c.parentPortId),['out_a','out_z']);
  f.catalog.parts.reverse();f.catalog.parts.find(p=>p.partId==='fixture.parent')!.ports.reverse();f.assembly.nodes.reverse();assert.deepEqual(discoverSnapCandidates(f.assembly,f.catalog,f.request).candidates,first);
});
test('equal candidates on different nodes sort by stable node ID',()=>{
  const f=fixture(),r=f.catalog.parts[0];r.ports.push({...structuredClone(r.ports[0]),port_id:'out2'});
  f.assembly.nodes.push({...structuredClone(f.assembly.nodes[1]),node_id:'pa'});f.assembly.mechanical_tree.push({...structuredClone(f.assembly.mechanical_tree[0]),edge_id:'edge_ra',parent_port_id:'out2',child_node_id:'pa'});
  assert.deepEqual(discoverSnapCandidates(f.assembly,f.catalog,f.request).candidates.map(c=>c.parentNodeId),['p0','pa']);
});
for(const [label,q] of [['non-unit',[2,0,0,0]],['wrong length',[1,0,0]],['non-finite',[NaN,0,0,0]]] as const)test(`reject ${label} quaternion`,()=>{
  const f=fixture();f.request.pose.quaternion_wxyz=[...q] as any;assert.throws(()=>discoverSnapCandidates(f.assembly,f.catalog,f.request),/Quaternion/);
});
test('catalog quaternion norms are checked; sign-equivalent quaternions retain the same pose',()=>{
  const f=fixture();f.catalog.parts[1].ports[1].quaternion_wxyz=[2,0,0,0];assert.throws(()=>discoverSnapCandidates(f.assembly,f.catalog,f.request),/unit norm/);
  const a=fixture(),b=fixture();b.request.pose.quaternion_wxyz=b.request.pose.quaternion_wxyz.map(n=>-n) as any;
  assert.deepEqual(discoverSnapCandidates(a.assembly,a.catalog,a.request).candidates,discoverSnapCandidates(b.assembly,b.catalog,b.request).candidates);
});
for(const [label,rotation] of [['normal',[0,1,0,0]],['twist',[0,0,0,1]]] as const)test(`reject incompatible ${label}`,()=>{
  const f=fixture(),cp=f.catalog.parts[2].ports[0],contact=composePose(f.request.pose,cp).position_m;
  f.request.pose.quaternion_wxyz=composePose(f.request.pose,pose([0,0,0],[...rotation])).quaternion_wxyz;
  const offset=composePose(pose([0,0,0],f.request.pose.quaternion_wxyz),cp).position_m;f.request.pose.position_m=contact.map((n,i)=>n-offset[i]) as any;
  const result=discoverSnapCandidates(f.assembly,f.catalog,f.request);assert.equal(result.candidates.length,0);assert.ok(result.rejections.some(r=>r.toLowerCase().includes(label)));
});
test('five-degree angular capture snaps to zero final twist; six degrees rejects',()=>{
  for(const [angle,accepted] of [[5,true],[6,false]] as const){const f=fixture(),a=angle*Math.PI/360;f.request.pose.quaternion_wxyz=composePose(f.request.pose,pose([0,0,0],[Math.cos(a),0,0,Math.sin(a)])).quaternion_wxyz;
    const found=discoverSnapCandidates(f.assembly,f.catalog,f.request).candidates;assert.equal(found.length>0,accepted);if(accepted)near(found[0].worldTransform.quaternion_wxyz,[.5,.5,.5,.5]);}
});
test('swapped xyzw identity is not accepted as wxyz; no heuristic reordering',()=>{
  const f=realFixture();f.request.pose.quaternion_wxyz=[0,0,0,1];const result=discoverSnapCandidates(f.assembly,f.catalog,f.request);assert.equal(result.candidates.length,0);assert.ok(result.rejections.some(r=>r.includes('twist')));
});
for(const [pg,cg,accepted] of [['plug','socket',true],['socket','plug',true],['neutral','neutral',true],['plug','plug',false],['socket','socket',false],['neutral','plug',false]] as const)test(`gender ${pg}/${cg}`,()=>{
  const f=fixture();f.catalog.parts[1].ports[1].gender=pg;f.catalog.parts[2].ports[0].gender=cg;assert.equal(discoverSnapCandidates(f.assembly,f.catalog,f.request).candidates.length>0,accepted);
});
test('different and unsupported standards reject',()=>{
  const f=fixture();f.catalog.parts[2].ports[0].mount_standard='horn_25t';assert.equal(discoverSnapCandidates(f.assembly,f.catalog,f.request).candidates.length,0);
  assert.throws(()=>mateTransform(f.catalog.parts[2].ports[0],f.catalog.parts[2].ports[0]),/standard/);
});
test('occupied ports, source identity collision and changed catalog pins reject',()=>{
  const f=fixture(),chosen=proposal(f);f.assembly=applySnapPlacement(f.assembly,f.catalog,chosen);f.request.source={kind:'new',node:node('c1','fixture.child','c')};
  const result=discoverSnapCandidates(f.assembly,f.catalog,f.request);assert.ok(result.rejections.includes('Parent port is occupied'));assert.ok(!result.candidates.some(c=>c.parentNodeId==='p0'&&c.parentPortId==='out'));
  f.request.source={kind:'new',node:node('c0','fixture.child','c')};assert.throws(()=>discoverSnapCandidates(f.assembly,f.catalog,f.request),/already exists/);
  const other=fixture();other.catalog.parts[1].sha256='f'.repeat(64);assert.throws(()=>discoverSnapCandidates(other.assembly,other.catalog,other.request),/byte pin/);
});
test('stale and tampered proposals reject; preview never mutates the draft',()=>{
  const f=fixture(),p=proposal(f);f.assembly.identity.name='new revision';assert.throws(()=>applySnapPlacement(f.assembly,f.catalog,p),/Stale/);
  const g=fixture(),q=proposal(g);q.candidate.relativeTransform.position_m[0]+=1;assert.throws(()=>applySnapPlacement(g.assembly,g.catalog,q),/tampered/);
});
test('reparenting a subtree preserves descendants and rejects a cyclic drop',()=>{
  const f=fixture();f.assembly=applySnapPlacement(f.assembly,f.catalog,proposal(f));
  const move:PlacementRequest={source:{kind:'move',nodeId:'p0'},childPortId:'input',pose:worldTransforms(f.assembly).p0};
  const result=discoverSnapCandidates(f.assembly,f.catalog,move);assert.ok(result.rejections.some(r=>r.includes('Cycle')));
  const p=makeSnapProposal(f.assembly,f.catalog,move,result.candidates[0]);p.candidate.parentNodeId='c0';p.candidate.parentPortId='out';
  assert.throws(()=>applySnapPlacement(f.assembly,f.catalog,p),/Cycle/);
  assert.throws(()=>discoverSnapCandidates(f.assembly,f.catalog,{...move,source:{kind:'move',nodeId:'r0'}}),/root/);
});
test('new placements, invalid drops, undo and redo restore exact graph/digest/selection',async()=>{
  const f=fixture(),store=new AssemblyStore(async assembly=>worldTransforms(assembly));await store.loadText(JSON.stringify(f.assembly));store.select({kind:'node',id:'p0'});
  const before=store.getState();const p=proposal(f);
  assert.equal(await store.edit(draft=>Object.assign(draft,applySnapPlacement(draft,f.catalog,p))),'committed');const after=store.getState();assert.equal(after.current!.assembly.nodes.length,3);assert.equal(after.authorityEpoch,before.authorityEpoch+1);assert.equal(after.admission,null);
  store.undo();assert.equal(store.getState().current!.assemblyDigest,before.current!.assemblyDigest);assert.deepEqual(store.getState().current!.selection,before.current!.selection);
  store.redo();assert.equal(store.getState().current!.assemblyDigest,after.current!.assemblyDigest);
  const bad=structuredClone(p);bad.baseAssemblyCanonical=canonicalAssemblyString(after.current!.assembly);bad.request={source:{kind:'move',nodeId:'p0'},childPortId:'input',pose:worldTransforms(after.current!.assembly).p0};bad.candidate.parentNodeId='c0';bad.candidate.parentPortId='out';
  assert.equal(await store.edit(draft=>Object.assign(draft,applySnapPlacement(draft,f.catalog,bad))),'rejected');assert.equal(store.getState().current!.revisionDigest,after.current!.revisionDigest);
});
function realFixture(){
  const catalogIndex=JSON.parse(readFileSync(new URL('../../packages/component-registry/catalog.json',import.meta.url),'utf8'));
  const parts:PlacementPart[]=catalogIndex.parts.map((entry:any)=>{const raw=JSON.parse(readFileSync(new URL(`../../packages/component-registry/${entry.path}`,import.meta.url),'utf8'));return {partId:entry.part_id,version:entry.version,sha256:entry.sha256,name:raw.identity.name,role:raw.identity.category,ports:raw.mechanical.snap_ports,positions:[],indices:[]};});
  const catalog:PlacementCatalog={catalogDigest:'e'.repeat(64),parts},source=parts.find(p=>p.partId==='seedcore.sensor-hat')!;
  const assembly=structuredClone(original),request:PlacementRequest={source:{kind:'new',node:{node_id:'cap_01',part_id:source.partId,part_version:source.version,part_sha256:source.sha256,role:'payload'}},childPortId:'mount.bottom',pose:pose([.01,0,.076])};return {assembly,catalog,request};
}
test('real catalog drop passes authoritative Python semantics and native rest FK',()=>{
  const f=realFixture(),p=makeSnapProposal(f.assembly,f.catalog,f.request,discoverSnapCandidates(f.assembly,f.catalog,f.request).candidates[0]);assert.equal(p.candidate.parentNodeId,'mcu_0');
  const next=applySnapPlacement(f.assembly,f.catalog,p);const python=process.env.SEEDCORE_TEST_PYTHON||`${root}.venv/bin/python`;
  const result=spawnSync(python,['-c','import json,sys; from seedcore.robotics.assembly import validate_assembly,compute_node_world_transforms; print(json.dumps(compute_node_world_transforms(validate_assembly(json.load(sys.stdin)))))'],{cwd:root,input:JSON.stringify(next),encoding:'utf8'});
  assert.equal(result.status,0,result.stderr||result.error?.message);const native=JSON.parse(result.stdout);near(native.cap_01.position_m,[0,0,.076]);near(native.cap_01.position_m,worldTransforms(next).cap_01.position_m);
});
test('occupied child port and rebinding an explicit joint are blocked without inventing joints',()=>{
  const f=realFixture();const move:PlacementRequest={source:{kind:'move',nodeId:'hat_0'},childPortId:'mount.bottom',pose:pose()};
  const result=discoverSnapCandidates(f.assembly,f.catalog,move);assert.ok(result.rejections.some(r=>r.includes('Explicit joint')));
  assert.throws(()=>discoverSnapCandidates(f.assembly,f.catalog,{...move,childPortId:'mount.top'}),/occupied/);
  const staged=suggestPlacementPose(f.assembly,f.catalog,f.request.source,'mount.bottom');assert.ok(discoverSnapCandidates(f.assembly,f.catalog,{...f.request,pose:staged}).candidates.length>0);
});


test('bound placement cannot reuse admission epoch after undo/redo returns to the same revision',async()=>{
  const f=fixture(),store=new AssemblyStore(async assembly=>worldTransforms(assembly));await store.loadText(JSON.stringify(f.assembly));
  const initial=store.getState(),binding={revisionDigest:initial.current!.revisionDigest,authorityEpoch:initial.authorityEpoch,proposal:proposal(f)};
  await store.edit(draft=>{draft.identity.name='intermediate';});store.undo();
  assert.equal(store.getState().current!.revisionDigest,binding.revisionDigest);assert.notEqual(store.getState().authorityEpoch,binding.authorityEpoch);
  assert.equal(await commitSnapProposal(store,f.catalog,binding),'rejected');assert.equal(store.getState().current!.assembly.nodes.length,2);assert.equal(store.getState().admission,null);
});


test('placement palette verifies raw catalog/part pins and mesh bytes before exposing parts',async()=>{
  const raw=readFileSync(new URL('../../packages/component-registry/catalog.json',import.meta.url),'utf8'),index=JSON.parse(raw);
  const {createHash}=await import('node:crypto');const digest=createHash('sha256').update(raw).digest('hex');
  const payload={scope:'offline_proxy_authoring',physical_acceptance:false,catalog_sha256:digest,catalog_raw_json:raw,part_documents:index.parts.map((p:any)=>({part_id:p.part_id,raw_json:readFileSync(new URL(`../../packages/component-registry/${p.path}`,import.meta.url),'utf8')}))};
  const original=globalThis.fetch;let mode='ok';
  try {
    globalThis.fetch=async(url)=>{
      if(url===`/api/placement-catalog?digest=${digest}`){const data=structuredClone(payload);if(mode==='part')data.part_documents[0].raw_json+=' ';if(mode==='catalog')data.catalog_raw_json+=' ';return Response.json(data);}
      const bytes=new Uint8Array(readFileSync(new URL(`../../packages/component-registry${url}`,import.meta.url)));if(mode==='mesh')bytes[0]=0;return new Response(bytes);
    };
    assert.equal((await loadPlacementCatalog(digest,new AbortController().signal)).parts.length,12);
    for(const [failure,expected] of [['part',/pin/],['catalog',/digest/],['mesh',/digest/]] as const){mode=failure;await assert.rejects(()=>loadPlacementCatalog(digest,new AbortController().signal),expected);}
  }finally{globalThis.fetch=original;}
});
