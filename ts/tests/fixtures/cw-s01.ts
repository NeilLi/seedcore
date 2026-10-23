/** Mathematical fixtures only. No supplier, drawing, price or hardware qualification. */
import { readFileSync } from 'node:fs';
import { canonicalAssemblyString, type RobotAssembly, type RelativeTransform } from '../../packages/contracts/src/index.js';
import { evaluateAssemblyDrc, parseDrcCatalogFromRaw, sha256Hex } from '../../packages/drc-solver/src/index.js';
import type { CompilerInput, RawCompilerCatalog } from '../../packages/wasm-sim-bridge/src/index.js';

const registry = new URL('../../../packages/component-registry/', import.meta.url);
export function realStarterInput(): CompilerInput {
  const catalogRawJson = readFileSync(new URL('catalog.json', registry), 'utf8');
  const index = JSON.parse(catalogRawJson);
  const catalog: RawCompilerCatalog = {
    catalogRawJson, catalogSha256: sha256Hex(catalogRawJson), provenance: 'verified_local_catalog',
    partDocuments: index.parts.map((p: any) => ({ part_id: p.part_id, raw_json: readFileSync(new URL(p.path, registry), 'utf8') })),
  };
  const assembly = JSON.parse(readFileSync(new URL('assemblies/tabletop-starter.sc-assembly.json', registry), 'utf8'));
  return { assembly, catalog, drcReport: evaluateAssemblyDrc(assembly, parseDrcCatalogFromRaw(catalog)), options: { actuatorMode: 'position' } };
}

export function studioReferenceInput(): CompilerInput {
  const profile = JSON.parse(readFileSync(new URL('../../../packages/simulation-fixtures/cw-s01/reference.json', import.meta.url), 'utf8'));
  const { assembly, catalog } = profile;
  return { assembly, catalog, drcReport: evaluateAssemblyDrc(assembly, parseDrcCatalogFromRaw(catalog)), options: { actuatorMode: 'position' } };
}

type Q4 = [number, number, number, number];
const mul = (a: Q4, b: Q4): Q4 => {
  const [w,x,y,z] = a, [v,i,j,k] = b;
  return [w*v-x*i-y*j-z*k,w*i+x*v+y*k-z*j,w*j-x*k+y*v+z*i,w*k+x*j-y*i+z*v];
};
const inv = (q: Q4): Q4 => [q[0],-q[1],-q[2],-q[3]];
function mate(p: RelativeTransform, c: RelativeTransform): RelativeTransform {
  const q = mul(mul(p.quaternion_wxyz,[0,1,0,0]),inv(c.quaternion_wxyz));
  const r = mul(mul(q,[0,...c.position_m]),inv(q));
  return {position_m:p.position_m.map((v,i)=>v-r[i+1]) as [number,number,number],quaternion_wxyz:q};
}

/** Re-pin only in-memory test documents; actual catalog/starter bytes never change. */
export function makeSyntheticSimulationInput(jointCount: 1|2|3 = 1, rotated = false): CompilerInput {
  const real = realStarterInput();
  const sources = ['seedcore.tabletop-base','feetech.sts3215-draft','seedcore.sensor-hat'];
  const parts = sources.map((id, i) => {
    const part = JSON.parse(real.catalog.partDocuments.find(p => p.part_id === id)!.raw_json);
    part.identity.part_id = `synthetic.cw-s01.${['base','actuator','payload'][i]}`;
    part.identity.name = `CW-S01 synthetic mathematical ${i}; no physical claims`;
    part.identity.notes = 'Synthetic conformance fixture, not supplier data or hardware acceptance.';
    part.identity.cost_basis = 'estimate'; part.identity.bom_cost_usd = 1;
    // Synthetic power bookkeeping only; these numbers are not supplier ratings.
    part.electrical = {rating_basis:'not_applicable',min_v:null,max_v:null,continuous_ma:null,peak_ma:null,output_capacity_ma:null,bus_interfaces:[]};
    if (i < 2) part.electrical = {
      rating_basis:'documented', min_v:i===0?6:5, max_v:i===0?6:7.4,
      continuous_ma:i===0?0:100, peak_ma:i===0?0:200, output_capacity_ma:i===0?10000:null,
      bus_interfaces:[{interface_id:'power',kind:'POWER_RAIL',role:i===0?'source':'sink',protocol:null,logic_min_v:null,logic_max_v:null,i2c_address:null,pins:['VIN','GND']}],
    };
    if (rotated && i === 0) part.mechanical.snap_ports[1].quaternion_wxyz = [Math.SQRT1_2,0,0,Math.SQRT1_2];
    if (rotated && i === 2) {
      part.mechanical.snap_ports[0].quaternion_wxyz = mul(inv([Math.SQRT1_2,0,0,Math.SQRT1_2]),[0,1,0,0]);
      // Deliberately non-diagonal inertia in a synthetic non-actuator part.
      part.mechanical.basis = 'drawing_reviewed';
      part.mechanical.visual_mesh.origin = 'reviewed_asset';
      part.mechanical.snap_ports.forEach((p: any) => p.qualification = 'drawing_reviewed');
      part.mechanical.center_of_mass_m = [0.001,-0.002,0.001];
      part.mechanical.inertia_kg_m2 = {ixx:0.000012,iyy:0.000014,izz:0.000016,ixy:0.000001,ixz:-0.0000008,iyz:0.0000006};
    }
    return part;
  });
  const documents = parts.map(p => ({part_id:p.identity.part_id,raw_json:JSON.stringify(p)}));
  const index = {schema_version:'seedcore.component-catalog.v1',status:'synthetic_fixture',parts:documents.map((d,i)=>({part_id:d.part_id,version:parts[i].identity.version,path:`parts/${d.part_id}.sc-part.json`,sha256:sha256Hex(d.raw_json)}))};
  const catalogRawJson = JSON.stringify(index);
  const catalog: RawCompilerCatalog = {catalogRawJson,catalogSha256:sha256Hex(catalogRawJson),partDocuments:documents,provenance:'synthetic_fixture'};
  const assembly = structuredClone(real.assembly);
  assembly.identity = {...assembly.identity,assembly_id:'synthetic.cw-s01.serial',name:'Synthetic serial fixture; no hardware acceptance',notes:'Ideal mathematical actuators and synthetic estimates; not product data.'};
  assembly.metadata = {notes:'Synthetic positive simulation fixture; never a hardware profile.'};
  assembly.root_node_id = 'base'; assembly.nodes = []; assembly.mechanical_tree = []; assembly.actuator_outputs = []; assembly.electrical_nets = [];
  const sequence = ['base',...Array.from({length:jointCount},(_,i)=>`servo_${i}`),'payload'];
  const partFor = (id: string): any => parts[id==='base'?0:id==='payload'?2:1];
  for (const id of sequence) {
    const p = partFor(id), pin = index.parts.find(p => p.part_id === partFor(id).identity.part_id)!;
    assembly.nodes.push({node_id:id,part_id:pin.part_id,part_version:pin.version,part_sha256:pin.sha256,role:id==='base'?'chassis':id==='payload'?'payload':'actuator'});
  }
  for (let i=1; i<sequence.length; i++) {
    const parent = sequence[i-1], child = sequence[i];
    const pp = partFor(parent).mechanical.snap_ports.find((p: any) => p.port_id === 'mount.top');
    const cp = partFor(child).mechanical.snap_ports.find((p: any) => p.port_id === 'mount.bottom');
    const edge = {edge_id:`edge_${i}`,parent_node_id:parent,parent_port_id:'mount.top',child_node_id:child,child_port_id:'mount.bottom',relative_transform:mate(pp,cp)};
    if (parent === 'base') assembly.mechanical_tree.push({...edge,connection_type:'rigid_mount'});
    else {
      const axis: [number,number,number] = rotated ? [Math.SQRT1_2,Math.SQRT1_2,0] : [0,1,0];
      assembly.actuator_outputs.push({node_id:parent,port_id:'mount.top',channel:1,basis:'simulation_proxy',axis,pivot_m:pp.position_m});
      assembly.mechanical_tree.push({...edge,connection_type:'articulated_joint',joint:{joint_id:`joint_${parent}`,kind:'revolute',frame:'parent_part',axis,pivot_m:pp.position_m,actuator_node_id:parent,actuator_channel:1,rest_angle_rad:rotated?0.2:0,limits_rad:{min_rad:-0.5,max_rad:0.5,max_velocity_rad_s:1,max_torque_nm:0.2}}});
    }
  }
  assembly.electrical_nets=[{net_id:'synthetic_power',kind:'power',nominal_voltage_v:6,endpoints:sequence.filter(id=>id!=='payload').map(node_id=>({node_id,interface_id:'power',pins:['VIN']}))}];
  const drcReport = evaluateAssemblyDrc(assembly,parseDrcCatalogFromRaw(catalog));
  return {assembly,catalog,drcReport,options:{actuatorMode:'position'}};
}

export function refreshFixture(input: CompilerInput): void {
  input.drcReport = evaluateAssemblyDrc(input.assembly,parseDrcCatalogFromRaw(input.catalog),input.drcOptions);
}
export function rewriteFixturePart(input: CompilerInput, id: string, edit: (part: any) => void): void {
  const doc = input.catalog.partDocuments.find(p => p.part_id === id)!;
  const value = JSON.parse(doc.raw_json); edit(value); doc.raw_json = JSON.stringify(value);
  const index = JSON.parse(input.catalog.catalogRawJson);
  const digest = sha256Hex(doc.raw_json);
  index.parts.find((p: any)=>p.part_id===id).sha256 = digest;
  for (const node of input.assembly.nodes) if (node.part_id===id) node.part_sha256=digest;
  input.catalog.catalogRawJson=JSON.stringify(index); input.catalog.catalogSha256=sha256Hex(input.catalog.catalogRawJson);
  refreshFixture(input);
}
export const snapshotFixture = (input: CompilerInput): string => canonicalAssemblyString(input);
