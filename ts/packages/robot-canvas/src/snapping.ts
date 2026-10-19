/** CW-SNAP-01: pure proxy mating proposals. This module grants no authority. */
import {canonicalAssemblyString,validateAssemblyStructure,type AssemblyNode,type AssemblyRole,type RelativeTransform,type RobotAssembly} from '@seedcore/contracts';
import type {Frozen} from './store.js';

export interface SnapPort extends RelativeTransform {port_id:string;mount_standard:string;gender:'neutral'|'plug'|'socket'}
export interface PlacementPart {
  partId:string;version:string;sha256:string;name:string;role:AssemblyRole;ports:SnapPort[];
  positions:number[];indices:number[];
}
export interface PlacementCatalog {catalogDigest:string;parts:PlacementPart[]}
export type PlacementSource = {kind:'new';node:AssemblyNode}|{kind:'move';nodeId:string};
export interface PlacementRequest {source:PlacementSource;childPortId:string;pose:RelativeTransform}
export interface SnapCandidate {
  parentNodeId:string;parentPortId:string;childPortId:string;distanceM:number;
  relativeTransform:RelativeTransform;worldTransform:RelativeTransform;
}
export interface SnapProposal {baseAssemblyCanonical:string;catalogDigest:string;request:PlacementRequest;candidate:SnapCandidate}
export const SNAP_RADIUS_M=.015;
export const SNAP_CAPTURE_ANGLE_RAD=5*Math.PI/180;
const EPS=1e-12;
const lex=(a:string,b:string)=>a<b?-1:a>b?1:0;
const key=(node:string,port:string)=>JSON.stringify([node,port]);
interface Pose {readonly position_m:readonly number[];readonly quaternion_wxyz:readonly number[]}
const vector=(value:readonly number[],length:number,label:string)=>{
  if(!Array.isArray(value)||value.length!==length||value.some(n=>typeof n!=='number'||!Number.isFinite(n))) throw new Error(`${label} must contain ${length} finite numbers`);
};
export function assertPose(pose:Pose):void {
  if(!pose) throw new Error('Missing pose');
  vector(pose.position_m,3,'Position');vector(pose.quaternion_wxyz,4,'Quaternion [w,x,y,z]');
  if(Math.abs(pose.quaternion_wxyz.reduce((sum,n)=>sum+n*n,0)-1)>1e-8) throw new Error('Quaternion [w,x,y,z] must have unit norm');
}
const mul=(a:readonly number[],b:readonly number[]):[number,number,number,number]=>{
  const [w,x,y,z]=a,[v,i,j,k]=b;
  return [w*v-x*i-y*j-z*k,w*i+x*v+y*k-z*j,w*j-x*k+y*v+z*i,w*k+x*j-y*i+z*v];
};
const conjugate=(q:readonly number[])=>[q[0],-q[1],-q[2],-q[3]];
const rotate=(q:readonly number[],v:readonly number[])=>mul(mul(q,[0,...v]),conjugate(q)).slice(1) as [number,number,number];
const dot=(a:readonly number[],b:readonly number[])=>a.reduce((sum,n,i)=>sum+n*b[i],0);
const cross=(a:readonly number[],b:readonly number[])=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
export function composePose(a:Pose,b:Pose):RelativeTransform {
  assertPose(a);assertPose(b);const offset=rotate(a.quaternion_wxyz,b.position_m);
  return {position_m:a.position_m.map((n,i)=>n+offset[i]) as [number,number,number],quaternion_wxyz:mul(a.quaternion_wxyz,b.quaternion_wxyz)};
}
export function inversePose(pose:Pose):RelativeTransform {
  assertPose(pose);const q=conjugate(pose.quaternion_wxyz) as [number,number,number,number];
  return {position_m:rotate(q,pose.position_m.map(n=>-n)),quaternion_wxyz:q};
}
const IDENTITY_POSE:RelativeTransform={position_m:[0,0,0],quaternion_wxyz:[1,0,0,0]};
const flip:RelativeTransform={position_m:[0,0,0],quaternion_wxyz:[0,1,0,0]};
function assertCompatible(parent:Frozen<SnapPort>,child:Frozen<SnapPort>):void {
  assertPose(parent);assertPose(child);
  if(parent.mount_standard!=='seedcore.proxy_mount_v1'||child.mount_standard!==parent.mount_standard) throw new Error('Incompatible or unsupported mount standard');
  if(!((parent.gender==='neutral'&&child.gender==='neutral')||(['plug','socket'].includes(parent.gender)&&['plug','socket'].includes(child.gender)&&parent.gender!==child.gender))) throw new Error('Incompatible port genders');
}
/** T_parent_port * Rx(pi) * inverse(T_child_port), in parent-part coordinates. */
export function mateTransform(parent:Frozen<SnapPort>,child:Frozen<SnapPort>):RelativeTransform {
  assertCompatible(parent,child);return composePose(composePose(parent,flip),inversePose(child));
}
export function worldTransforms(raw:Frozen<RobotAssembly>):Record<string,RelativeTransform> {
  const assembly=validateAssemblyStructure(raw),result:Record<string,RelativeTransform>={[assembly.root_node_id]:structuredClone(IDENTITY_POSE)};
  const queue=[assembly.root_node_id],children=new Map<string,typeof assembly.mechanical_tree>();
  for(const edge of assembly.mechanical_tree){const list=children.get(edge.parent_node_id)??[];list.push(edge);children.set(edge.parent_node_id,list);}
  while(queue.length){const parent=queue.shift()!;for(const edge of children.get(parent)??[]){result[edge.child_node_id]=composePose(result[parent],edge.relative_transform);queue.push(edge.child_node_id);}}
  return result;
}
export function partForNode(catalog:Frozen<PlacementCatalog>,node:Frozen<AssemblyNode>):Frozen<PlacementPart> {
  const part=catalog.parts.find(p=>p.partId===node.part_id);
  if(!part||part.version!==node.part_version||part.sha256!==node.part_sha256) throw new Error('Placement part identity/version/byte pin mismatch');
  if(!part.ports.length||part.ports.length>32||new Set(part.ports.map(p=>p.port_id)).size!==part.ports.length) throw new Error('Invalid placement ports');
  part.ports.forEach(assertPose);return part;
}
function context(raw:Frozen<RobotAssembly>,catalog:Frozen<PlacementCatalog>,source:Frozen<PlacementSource>){
  const assembly=validateAssemblyStructure(raw);
  if(catalog.parts.length<1||catalog.parts.length>256||new Set(catalog.parts.map(p=>p.partId)).size!==catalog.parts.length) throw new Error('Invalid or duplicate placement catalog');
  for(const node of assembly.nodes) partForNode(catalog,node);
  const node=source.kind==='new'?structuredClone(source.node):assembly.nodes.find(n=>n.node_id===source.nodeId);
  if(!node||!/^[a-z][a-z0-9._-]{1,63}$/.test(node.node_id)) throw new Error('Unknown node or invalid instance ID');
  if(source.kind==='new'&&assembly.nodes.some(n=>n.node_id===node.node_id)) throw new Error('Instance ID already exists');
  if(source.kind==='move'&&node.node_id===assembly.root_node_id) throw new Error('The assembly root cannot be reparented');
  const part=partForNode(catalog,node),incoming=source.kind==='move'?assembly.mechanical_tree.find(e=>e.child_node_id===node.node_id):undefined;
  const moving=new Set<string>(source.kind==='move'?[node.node_id]:[]),queue=[...moving];
  while(queue.length){const parent=queue.pop()!;for(const edge of assembly.mechanical_tree)if(edge.parent_node_id===parent&&!moving.has(edge.child_node_id)){moving.add(edge.child_node_id);queue.push(edge.child_node_id);}}
  const occupied=new Set<string>();
  for(const edge of assembly.mechanical_tree)if(edge!==incoming){occupied.add(key(edge.parent_node_id,edge.parent_port_id));occupied.add(key(edge.child_node_id,edge.child_port_id));}
  const outputs=new Set(assembly.actuator_outputs.map(o=>key(o.node_id,o.port_id)));
  return {assembly,node,part,incoming,moving,occupied,outputs};
}
function parentAllowed(ctx:ReturnType<typeof context>,parent:string,port:string):void {
  if(ctx.moving.has(parent)||parent===ctx.node.node_id) throw new Error('Cycle: target is inside the moving subtree');
  if(ctx.occupied.has(key(parent,port))) throw new Error('Parent port is occupied');
  if(ctx.incoming?.connection_type==='articulated_joint'&&(ctx.incoming.parent_node_id!==parent||ctx.incoming.parent_port_id!==port)) throw new Error('Explicit joint cannot be rebound by a rigid placement');
  if(ctx.outputs.has(key(parent,port))&&!(ctx.incoming?.connection_type==='articulated_joint'&&ctx.incoming.parent_node_id===parent&&ctx.incoming.parent_port_id===port)) throw new Error('Rotating output requires an explicit joint');
}
function childPort(ctx:ReturnType<typeof context>,portId:string):Frozen<SnapPort>{
  const port=ctx.part.ports.find(p=>p.port_id===portId);
  if(!port) throw new Error('Unknown child port');
  if(ctx.occupied.has(key(ctx.node.node_id,portId))) throw new Error('Child port is occupied');
  if(ctx.outputs.has(key(ctx.node.node_id,portId))) throw new Error('An actuator output cannot be used as a housing attachment');
  return port;
}
export function discoverSnapCandidates(raw:Frozen<RobotAssembly>,catalog:Frozen<PlacementCatalog>,request:Frozen<PlacementRequest>):{candidates:SnapCandidate[];rejections:string[]} {
  assertPose(request.pose);const ctx=context(raw,catalog,request.source),cp=childPort(ctx,request.childPortId),world=worldTransforms(ctx.assembly);
  const actualChildPort=composePose(request.pose,cp),candidates:SnapCandidate[]=[],rejections=new Set<string>();
  for(const parent of ctx.assembly.nodes) for(const pp of partForNode(catalog,parent).ports){
    try {
      parentAllowed(ctx,parent.node_id,pp.port_id);assertCompatible(pp,cp);
      const parentWorld=composePose(world[parent.node_id],pp),delta=actualChildPort.position_m.map((n,i)=>n-parentWorld.position_m[i]);
      const distanceM=Math.hypot(...delta);if(distanceM>SNAP_RADIUS_M+EPS) throw new Error('Outside 15 mm capture radius');
      const normal=rotate(parentWorld.quaternion_wxyz,[0,0,1]),childNormal=rotate(actualChildPort.quaternion_wxyz,[0,0,1]);
      if(dot(normal,childNormal)>-Math.cos(SNAP_CAPTURE_ANGLE_RAD)+EPS) throw new Error('Port normals must oppose within 5 degrees');
      const desiredX=rotate(parentWorld.quaternion_wxyz,[1,0,0]),actualX=rotate(actualChildPort.quaternion_wxyz,[1,0,0]);
      const projected=actualX.map((n,i)=>n-dot(actualX,normal)*normal[i]);const size=Math.hypot(...projected);
      if(size<EPS) throw new Error('Invalid port twist');
      const x=projected.map(n=>n/size),twist=Math.atan2(dot(normal,cross(desiredX,x)),dot(desiredX,x));
      if(Math.abs(twist)>SNAP_CAPTURE_ANGLE_RAD+EPS) throw new Error('Port twist exceeds 5 degree capture; final twist must be zero');
      const relativeTransform=mateTransform(pp,cp),worldTransform=composePose(world[parent.node_id],relativeTransform);
      candidates.push({parentNodeId:parent.node_id,parentPortId:pp.port_id,childPortId:cp.port_id,distanceM,relativeTransform,worldTransform});
    }catch(error){rejections.add(error instanceof Error?error.message:'Invalid mount');}
  }
  candidates.sort((a,b)=>a.distanceM-b.distanceM||lex(a.parentNodeId,b.parentNodeId)||lex(a.parentPortId,b.parentPortId)||lex(a.childPortId,b.childPortId));
  return {candidates,rejections:[...rejections].sort(lex)};
}
export function makeSnapProposal(raw:Frozen<RobotAssembly>,catalog:Frozen<PlacementCatalog>,request:Frozen<PlacementRequest>,candidate:Frozen<SnapCandidate>):SnapProposal {
  const result=discoverSnapCandidates(raw,catalog,request).candidates.find(c=>c.parentNodeId===candidate.parentNodeId&&c.parentPortId===candidate.parentPortId&&c.childPortId===candidate.childPortId);
  if(!result) throw new Error('Mount is not a valid capture candidate');
  return {baseAssemblyCanonical:canonicalAssemblyString(raw),catalogDigest:catalog.catalogDigest,request:structuredClone(request) as PlacementRequest,candidate:result};
}
/** Recheck the proposal against the current draft. Caller commits through AssemblyStore.edit. */
export function applySnapPlacement(raw:Frozen<RobotAssembly>,catalog:Frozen<PlacementCatalog>,proposal:Frozen<SnapProposal>):RobotAssembly {
  if(proposal.baseAssemblyCanonical!==canonicalAssemblyString(raw)||proposal.catalogDigest!==catalog.catalogDigest) throw new Error('Stale placement proposal');
  const ctx=context(raw,catalog,proposal.request.source),chosen=proposal.candidate;
  parentAllowed(ctx,chosen.parentNodeId,chosen.parentPortId);
  const fresh=makeSnapProposal(raw,catalog,proposal.request,chosen).candidate;
  if(canonicalAssemblyString(fresh)!==canonicalAssemblyString(chosen)) throw new Error('Placement candidate changed or was tampered with');
  if(proposal.request.source.kind==='new') ctx.assembly.nodes.push(structuredClone(proposal.request.source.node));
  let edgeId=ctx.incoming?.edge_id;
  if(!edgeId){let suffix=1;const base=`edge_${ctx.node.node_id}`.slice(0,58);edgeId=base;while(ctx.assembly.mechanical_tree.some(e=>e.edge_id===edgeId)) edgeId=`${base}_${++suffix}`;}
  const edge={...(ctx.incoming??{connection_type:'rigid_mount' as const}),edge_id:edgeId,parent_node_id:fresh.parentNodeId,parent_port_id:fresh.parentPortId,child_node_id:ctx.node.node_id,child_port_id:fresh.childPortId,relative_transform:fresh.relativeTransform};
  ctx.assembly.mechanical_tree=ctx.assembly.mechanical_tree.filter(e=>e!==ctx.incoming);ctx.assembly.mechanical_tree.push(edge);
  return validateAssemblyStructure(ctx.assembly);
}
/** Seed a nearby numeric pose; final selection still goes through discovery and explicit commit. */
export function suggestPlacementPose(raw:Frozen<RobotAssembly>,catalog:Frozen<PlacementCatalog>,source:Frozen<PlacementSource>,childPortId:string,preferredParent?:string):RelativeTransform {
  const ctx=context(raw,catalog,source),cp=childPort(ctx,childPortId),world=worldTransforms(ctx.assembly);
  const parents=ctx.assembly.nodes.flatMap(n=>partForNode(catalog,n).ports.map(p=>({node:n,port:p})));
  parents.sort((a,b)=>Number(b.node.node_id===preferredParent)-Number(a.node.node_id===preferredParent)||Number(b.port.port_id==='mount.top')-Number(a.port.port_id==='mount.top')||lex(a.node.node_id,b.node.node_id)||lex(a.port.port_id,b.port.port_id));
  for(const {node,port} of parents)try{parentAllowed(ctx,node.node_id,port.port_id);const pose=composePose(world[node.node_id],mateTransform(port,cp));pose.position_m[0]+=.01;return pose;}catch{}
  throw new Error('No compatible open proxy port for this source');
}

/** Bind a UI proposal to a local revision/epoch, including undo/redo ABA fences. */
export function commitSnapProposal<S>(store:import('./store.js').AssemblyStore<S>,catalog:Frozen<PlacementCatalog>,binding:{revisionDigest:string;authorityEpoch:number;proposal:Frozen<SnapProposal>}):Promise<import('./store.js').LoadResult> {
  return store.edit(draft=>{
    const state=store.getState();
    if(state.current?.revisionDigest!==binding.revisionDigest||state.authorityEpoch!==binding.authorityEpoch) throw new Error('Stale placement revision or authority epoch');
    Object.assign(draft,applySnapPlacement(draft,catalog,binding.proposal));
  });
}
