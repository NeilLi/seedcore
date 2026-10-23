import { canonicalAssemblyString, parseStrictJson, type RobotAssembly, type RelativeTransform } from '@seedcore/contracts';
import { sha256Text } from './store.js';
import type {PlacementCatalog,PlacementPart,SnapPort} from './snapping.js';
import type {AssemblyRole} from '@seedcore/contracts';

export interface ProxyNode { id: string; label: string; role: string; transform: RelativeTransform; positions: number[]; indices: number[] }
export interface ProxyScene { nodes: ProxyNode[]; catalogDigest: string }

/** Bound response bytes while streaming, rather than after an unbounded allocation. */
export async function readBounded(response: Response, limit: number, options: { allowErrorStatus?: boolean } = {}): Promise<Uint8Array<ArrayBuffer>> {
  if (!response.ok && !options.allowErrorStatus) throw new Error(`Request failed (${response.status})`);
  if (!response.body) throw new Error('Empty response');
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try {
    for (;;) {
      const {done, value} = await reader.read(); if (done) break;
      size += value.length; if (size > limit) throw new Error('Response exceeds byte bound'); chunks.push(value);
    }
  } catch (error) { await reader.cancel(); throw error; }
  finally { reader.releaseLock(); }
  const result = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.length; }
  return result;
}
export async function fetchAssemblyText(url: string, signal: AbortSignal): Promise<string> {
  return new TextDecoder('utf-8', {fatal: true}).decode(await readBounded(await fetch(url, {signal}), 262144));
}
export function decodeProxy(bytes: Uint8Array<ArrayBuffer>): {positions: number[]; indices: number[]} {
  if (bytes.length < 28) throw new Error('Truncated proxy');
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (view.getUint32(0,true) !== 0x46546c67 || view.getUint32(4,true) !== 2 || view.getUint32(8,true) !== bytes.length) throw new Error('Invalid GLB header');
  const length = view.getUint32(12,true), binHeader = 20 + length;
  if (binHeader + 8 > bytes.length || view.getUint32(16,true) !== 0x4e4f534a || view.getUint32(binHeader+4,true) !== 0x004e4942 || binHeader+8+view.getUint32(binHeader,true) !== bytes.length) throw new Error('Invalid GLB chunks');
  const model = JSON.parse(new TextDecoder('utf-8', {fatal:true}).decode(bytes.slice(20, binHeader)));
  if (model.buffers?.length !== 1 || model.buffers[0].uri || model.accessors?.length !== 2 || model.bufferViews?.length !== 2 ||
      model.accessors[0].count !== 8 || model.accessors[0].componentType !== 5126 || model.accessors[0].type !== 'VEC3' ||
      model.accessors[1].count !== 36 || model.accessors[1].componentType !== 5123 || model.accessors[1].type !== 'SCALAR') throw new Error('Only frozen box proxies are supported');
  const positions: number[] = [], indices: number[] = [];
  const positionOffset = binHeader+8+model.bufferViews[0].byteOffset, indexOffset = binHeader+8+model.bufferViews[1].byteOffset;
  if (!Number.isSafeInteger(positionOffset) || !Number.isSafeInteger(indexOffset) || positionOffset < binHeader+8 || indexOffset < binHeader+8 || positionOffset+96 > bytes.length || indexOffset+72 > bytes.length) throw new Error('Invalid proxy offsets');
  for (let i=0;i<8;i++) positions.push(view.getFloat32(positionOffset+i*12,true), -view.getFloat32(positionOffset+i*12+8,true), view.getFloat32(positionOffset+i*12+4,true));
  for (let i=0;i<36;i++) indices.push(view.getUint16(indexOffset+i*2,true));
  if (positions.some(v=>!Number.isFinite(v)) || indices.some(v=>v>=8)) throw new Error('Invalid proxy geometry');
  return {positions,indices};
}

/** Catalog semantics are checked by the local service; raw byte pins are rechecked here. */
export async function prepareProxyScene(assembly: RobotAssembly, signal: AbortSignal): Promise<ProxyScene> {
  const response = await fetch('/api/assembly/validate', {method:'POST', headers:{'Content-Type':'application/json'}, body:canonicalAssemblyString(assembly), signal});
  if (!response.ok) {
    const detail = response.body ? new TextDecoder().decode(await readBounded(response, 4096, {allowErrorStatus:true})) : '';
    throw new Error(`Catalog validation rejected build (HTTP ${response.status})${detail ? `: ${detail.slice(0,500)}` : ''}`);
  }
  const payload = JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(await readBounded(response, 2*1024*1024)));
  if (payload.scope !== 'offline_proxy_authoring' || payload.physical_acceptance !== false || payload.assembly_digest !== await sha256Text(canonicalAssemblyString(assembly))) throw new Error('Authoring validation scope/digest mismatch');
  const documents = new Map<string, any>();
  for (const item of payload.part_documents) {
    if (documents.has(item.part_id)) throw new Error('Duplicate part document');
    documents.set(item.part_id, {part: parseStrictJson(item.raw_json), digest:await sha256Text(item.raw_json)});
  }
  const geometries = new Map<string, {positions:number[];indices:number[]}>();
  const nodes: ProxyNode[] = [];
  for (const node of assembly.nodes) {
    const entry = documents.get(node.part_id), part = entry?.part;
    if (!part || entry.digest !== node.part_sha256 || part.identity.part_id !== node.part_id || part.identity.version !== node.part_version || part.hal_and_safety.runtime_binding !== null || part.hal_and_safety.execution_authority !== 'none' || part.hal_and_safety.qualification !== 'unqualified') throw new Error('Part pin or authoring scope mismatch');
    const visual = part.mechanical.visual_mesh;
    let geometry = geometries.get(visual.sha256);
    if (!geometry) {geometry = await loadProxyMesh(visual,signal);geometries.set(visual.sha256,geometry);}
    const transform = payload.transforms[node.node_id] as RelativeTransform;
    if (!transform || transform.position_m?.length !== 3 || transform.quaternion_wxyz?.length !== 4 || [...transform.position_m,...transform.quaternion_wxyz].some(v=>!Number.isFinite(v))) throw new Error('Invalid rest transform');
    nodes.push({id:node.node_id, label:node.display_name ?? part.identity.name,role:node.role,transform,...geometry});
  }
  return {nodes,catalogDigest:payload.catalog_sha256};
}

async function loadProxyMesh(visual: {origin:string;up_axis:string;uri:string;sha256:string},signal:AbortSignal):Promise<{positions:number[];indices:number[]}> {
  if(visual.origin!=='seedcore_box_proxy'||visual.up_axis!=='Y'||!/^assets\/[a-z0-9-]+\.glb$/.test(visual.uri)||!/^[a-f0-9]{64}$/.test(visual.sha256)) throw new Error('Unsupported proxy asset');
  const bytes=await readBounded(await fetch(`/${visual.uri}`,{signal}),1048576);
  const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(b=>b.toString(16).padStart(2,'0')).join('');
  if(digest!==visual.sha256) throw new Error('Proxy mesh digest mismatch');
  return decodeProxy(bytes);
}

/** Read-only palette; its catalog digest must match the accepted assembly's scene. */
export async function loadPlacementCatalog(expectedDigest:string,signal:AbortSignal):Promise<PlacementCatalog> {
  const response=await fetch(`/api/placement-catalog?digest=${encodeURIComponent(expectedDigest)}`,{signal});
  const data=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(await readBounded(response,2*1024*1024)));
  if(data.scope!=='offline_proxy_authoring'||data.physical_acceptance!==false||data.catalog_sha256!==expectedDigest||await sha256Text(data.catalog_raw_json)!==expectedDigest) throw new Error('Placement catalog scope/digest mismatch');
  const index=parseStrictJson(data.catalog_raw_json) as {parts:{part_id:string;version:string;sha256:string}[]};
  if(!Array.isArray(index.parts)||index.parts.length<1||index.parts.length>256||!Array.isArray(data.part_documents)||data.part_documents.length!==index.parts.length) throw new Error('Invalid placement catalog size');
  const pins=new Map(index.parts.map(p=>[p.part_id,p]));
  if(pins.size!==index.parts.length) throw new Error('Duplicate catalog identity');
  const seen=new Set<string>();
  const parts=await Promise.all(data.part_documents.map(async (item:{part_id:string;raw_json:string}):Promise<PlacementPart>=>{
    if(seen.has(item.part_id)) throw new Error('Duplicate placement part');seen.add(item.part_id);
    const pin=pins.get(item.part_id),part=parseStrictJson(item.raw_json) as any;
    if(!pin||await sha256Text(item.raw_json)!==pin.sha256||part.identity.part_id!==pin.part_id||part.identity.version!==pin.version||part.hal_and_safety.execution_authority!=='none'||part.hal_and_safety.runtime_binding!==null||part.hal_and_safety.qualification!=='unqualified') throw new Error('Placement part pin/scope mismatch');
    if(!Array.isArray(part.mechanical.snap_ports)||part.mechanical.snap_ports.length<1||part.mechanical.snap_ports.length>32) throw new Error('Invalid placement ports');
    const geometry=await loadProxyMesh(part.mechanical.visual_mesh,signal);
    return {partId:pin.part_id,version:pin.version,sha256:pin.sha256,name:part.identity.name,role:part.identity.category as AssemblyRole,ports:part.mechanical.snap_ports as SnapPort[],...geometry};
  }));
  return {catalogDigest:expectedDigest,parts};
}
