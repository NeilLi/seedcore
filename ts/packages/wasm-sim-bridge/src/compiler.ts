import {
  assertComponentStructure, canonicalAssemblyString, parseStrictJson, validateAssemblyStructure,
  type RobotAssembly, type RelativeTransform, type MechanicalEdge,
} from '@seedcore/contracts';
import {
  evaluateAssemblyDrc, isValidInertiaTensor, parseDrcCatalogFromRaw, sha256Hex,
  type DrcCatalog, type DrcEvalOptions, type DrcPart, type DrcReport,
} from '@seedcore/drc-solver';

export const CW_S01_COMPILER = 'seedcore.cw-s01.compiler.v1' as const;
export const CW_S01_SUBSET = 'fixed_tabletop_serial_boxes_v1' as const;
export const SIMULATION_READINESS_POLICY = 'seedcore.cw-s01.simulation-readiness.v1' as const;
export type RawCompilerCatalog = Parameters<typeof parseDrcCatalogFromRaw>[0];
export type CompilerOptions = {
  actuatorMode: 'position' | 'torque';
  positionGain?: number;
  timestepSeconds?: number;
};
export interface CompilerInput {
  assembly: RobotAssembly;
  catalog: RawCompilerCatalog;
  drcReport: DrcReport;
  drcOptions?: DrcEvalOptions;
  options: CompilerOptions;
}
export type CompilerErrorCode = 'ASSEMBLY_INVALID' | 'CATALOG_INVALID' | 'SEMANTIC_INVALID'
  | 'UNSUPPORTED_SUBSET' | 'DRC_BINDING_MISMATCH' | 'DRC_NOT_READY' | 'OPTIONS_INVALID'
  | 'MODEL_BINDING_MISMATCH';
export class CwS01Error extends Error {
  constructor(readonly code: CompilerErrorCode, message: string) {
    super(`${code}: ${message}`); this.name = 'CwS01Error';
  }
}
const fail = (code: CompilerErrorCode, message: string): never => { throw new CwS01Error(code, message); };
const hash = (value: unknown): string => sha256Hex(canonicalAssemblyString(value));
const near = (a: readonly number[], b: readonly number[]): boolean => a.length === b.length && a.every((n, i) => Math.abs(n - b[i]) <= 1e-8);
const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);
type V3 = [number, number, number];
type Q4 = [number, number, number, number];
const mul = (a: Q4, b: Q4): Q4 => {
  const [w, x, y, z] = a, [v, i, j, k] = b;
  return [w*v-x*i-y*j-z*k, w*i+x*v+y*k-z*j, w*j-x*k+y*v+z*i, w*k+x*j-y*i+z*v];
};
const inverse = (q: Q4): Q4 => [q[0], -q[1], -q[2], -q[3]];
const rotate = (q: Q4, v: V3): V3 => mul(mul(q, [0, ...v]), inverse(q)).slice(1) as V3;
function pose(p: RelativeTransform): void {
  if (!p || !Array.isArray(p.position_m) || p.position_m.length !== 3 || !p.position_m.every(finite)
    || !Array.isArray(p.quaternion_wxyz) || p.quaternion_wxyz.length !== 4 || !p.quaternion_wxyz.every(finite)
    || Math.abs(p.quaternion_wxyz.reduce((s, n) => s+n*n, 0)-1) > 1e-8) fail('SEMANTIC_INVALID', 'Invalid catalog port pose');
}
function mate(parent: RelativeTransform, child: RelativeTransform): RelativeTransform {
  pose(parent); pose(child);
  const q = mul(mul(parent.quaternion_wxyz, [0, 1, 0, 0]), inverse(child.quaternion_wxyz));
  const v = rotate(q, child.position_m);
  return { position_m: parent.position_m.map((n, i) => n-v[i]) as V3, quaternion_wxyz: q };
}

/** Intrinsic source semantics used by the primitive compiler; no visual asset loading. */
function componentSemantics(part: any): void {
  const m = part.mechanical, e = part.electrical, s = part.hal_and_safety;
  const pair = (a: number | null, b: number | null) => {
    if ((a === null) !== (b === null) || (a !== null && b !== null && a > b)) throw new Error('Inconsistent component range');
  };
  pair(e.min_v, e.max_v); pair(e.continuous_ma, e.peak_ma);
  const ratings = [e.min_v,e.max_v,e.continuous_ma,e.peak_ma,e.output_capacity_ma];
  if ((e.rating_basis !== 'documented' && ratings.some(v => v !== null))
    || (e.rating_basis === 'documented' && ratings.slice(0,4).some(v => v === null))
    || (e.rating_basis === 'not_applicable' && e.bus_interfaces.length)) throw new Error('Inconsistent component electrical basis');
  if (new Set(e.bus_interfaces.map((b: any) => b.interface_id)).size !== e.bus_interfaces.length) throw new Error('Duplicate component interface');
  for (const b of e.bus_interfaces) {
    pair(b.logic_min_v,b.logic_max_v);
    if (b.kind !== 'I2C' && b.i2c_address !== null) throw new Error('I2C address on another bus');
  }
  const joint = s.capabilities.includes('actuator.joint_position');
  for (const key of ['hard_limits','simulation_limits']) {
    const l = s[key];
    if (!l) { if (joint && key === 'simulation_limits') throw new Error('Missing simulation limits'); continue; }
    pair(l.min_rad,l.max_rad);
    if ((l.min_rad !== null && l.min_rad === l.max_rad)
      || (!joint && Object.values(l).some(v => v !== null))
      || (key === 'simulation_limits' && Object.values(l).some(v => v === null))) throw new Error('Inconsistent component joint limits');
  }
  if (m.basis === 'simulation_proxy' && m.snap_ports.some((p: any) => p.qualification !== 'illustrative')) throw new Error('Proxy port claims drawing qualification');
  if (m.visual_mesh.origin === 'seedcore_box_proxy') {
    const [x,y,z] = m.collision.size_m, mass = m.mass_kg, I=m.inertia_kg_m2;
    const expected = [mass*(y*y+z*z)/12,mass*(x*x+z*z)/12,mass*(x*x+y*y)/12];
    if (m.basis !== 'simulation_proxy' || m.center_of_mass_m.some((v: number) => v !== 0)
      || [I.ixy,I.ixz,I.iyz].some(v => v !== 0)
      || [I.ixx,I.iyy,I.izz].some((v,i) => Math.abs(v-expected[i]) > Math.abs(expected[i])*1e-10)) throw new Error('Box proxy mass/COM/inertia disagree with authored geometry');
  }
}

export interface SimulationReadiness {
  policy: typeof SIMULATION_READINESS_POLICY;
  scope: 'offline_simulation_only';
  physicalAcceptance: false;
  executionAuthority: 'none';
  ready: boolean;
  drcDisposition: DrcReport['disposition'];
  deferredPhysicalFindings: string[];
  blockingFindings: string[];
}
interface Prepared {
  assembly: RobotAssembly;
  catalog: DrcCatalog;
  parts: Map<string, DrcPart>;
  chain: string[];
  edges: Map<string, MechanicalEdge>;
  drc: DrcReport;
  readiness: SimulationReadiness;
  drcOptionsDigest: string;
}

function prepare(input: CompilerInput): Prepared {
  let assembly: RobotAssembly;
  try { assembly = validateAssemblyStructure(input.assembly); }
  catch (error) { return fail('ASSEMBLY_INVALID', String(error)); }
  if (assembly.nodes.length > 32 || assembly.nodes.find(n => n.node_id === assembly.root_node_id)?.role !== 'chassis') {
    fail('UNSUPPORTED_SUBSET', 'Require a fixed chassis root and at most 32 bodies');
  }
  const chain = [assembly.root_node_id], edges = new Map<string, MechanicalEdge>();
  const outgoing = new Map<string, MechanicalEdge>();
  for (const edge of assembly.mechanical_tree) {
    if (outgoing.has(edge.parent_node_id)) fail('UNSUPPORTED_SUBSET', 'Branched graphs are unsupported');
    outgoing.set(edge.parent_node_id, edge); edges.set(edge.child_node_id, edge);
  }
  while (outgoing.has(chain[chain.length-1])) chain.push(outgoing.get(chain[chain.length-1])!.child_node_id);
  const joints = assembly.mechanical_tree.filter(e => e.connection_type === 'articulated_joint');
  if (chain.length !== assembly.nodes.length || joints.length < 1 || joints.length > 3 || assembly.actuator_outputs.length !== joints.length) {
    fail('UNSUPPORTED_SUBSET', 'Require a serial chain with one to three explicitly actuated revolute joints');
  }
  let catalog: DrcCatalog;
  const documents = new Map<string, any>();
  try {
    const raw = input.catalog;
    if (new TextEncoder().encode(raw.catalogRawJson).length + raw.partDocuments.reduce((s, p) => s + new TextEncoder().encode(p.raw_json).length, 0) > 2*1024*1024) {
      throw new Error('Catalog exceeds the 2 MiB compiler input bound');
    }
    const index = parseStrictJson(raw.catalogRawJson) as { schema_version: string; parts: { path: string }[] };
    if (index.schema_version !== 'seedcore.component-catalog.v1' || index.parts.some(p => !/^parts\/[a-zA-Z0-9_.-]+\.sc-part\.json$/.test(p.path) || p.path.includes('..'))) {
      throw new Error('Unsupported catalog or unsafe part path');
    }
    catalog = parseDrcCatalogFromRaw(raw);
    for (const document of raw.partDocuments) {
      const part = parseStrictJson(document.raw_json) as any;
      assertComponentStructure(part);
      componentSemantics(part);
      if (part.schema_version !== 'seedcore.component.v1' || part.mechanical?.frame !== 'right_handed_z_up_meters'
        || part.mechanical?.collision?.type !== 'box'
        || !/^assets\/[a-zA-Z0-9_.-]+\.glb$/.test(part.mechanical?.visual_mesh?.uri ?? '')
        || part.mechanical.visual_mesh.uri.includes('..')) throw new Error('Only local pinned box parts are supported; unsafe asset path or frame');
      documents.set(document.part_id, part);
    }
  } catch (error) { return fail('CATALOG_INVALID', String(error)); }
  const byId = new Map(catalog.parts.map(p => [p.partId, p]));
  const parts = new Map<string, DrcPart>();
  for (const node of assembly.nodes) {
    const part = byId.get(node.part_id);
    if (!part || part.sha256 !== node.part_sha256 || part.version !== node.part_version) return fail('CATALOG_INVALID', `Part pin mismatch: ${node.node_id}`);
    const m = part.mechanical;
    if (!Array.isArray(m.sizeM) || m.sizeM.length !== 3 || m.sizeM.some(v => !finite(v) || v <= 0 || v > 1)
      || !finite(m.massKg) || m.massKg <= 0 || m.massKg > 5
      || !Array.isArray(m.centerOfMassM) || m.centerOfMassM.length !== 3 || !m.centerOfMassM.every(finite)
      || !isValidInertiaTensor(m.inertiaKgM2).valid) fail('SEMANTIC_INVALID', 'Invalid primitive dimensions, mass, COM or full inertia');
    if (new Set(m.snapPorts.map(p => p.port_id)).size !== m.snapPorts.length) fail('SEMANTIC_INVALID', 'Duplicate catalog port');
    for (const port of m.snapPorts) pose(port);
    parts.set(node.node_id, part);
  }
  if (parts.get(assembly.root_node_id)!.category !== 'chassis') fail('UNSUPPORTED_SUBSET', 'Root must resolve to a chassis part');
  if ([...parts.values()].reduce((s, p) => s+p.mechanical.massKg, 0) > 5) fail('UNSUPPORTED_SUBSET', 'Total modeled mass exceeds the 5 kg software subset bound');
  const port = (nodeId: string, id: string) => {
    const p = parts.get(nodeId)!.mechanical.snapPorts.find(p => p.port_id === id);
    if (!p) return fail('SEMANTIC_INVALID', `Unknown port: ${nodeId}:${id}`);
    return p;
  };
  for (const output of assembly.actuator_outputs) {
    const part = parts.get(output.node_id)!;
    if (part.mechanical.basis !== 'simulation_proxy' || !part.halAndSafety.capabilities.includes('actuator.joint_position')
      || !near(output.pivot_m, port(output.node_id, output.port_id).position_m)) {
      fail('SEMANTIC_INVALID', 'v2 requires a declared proxy actuator output at the catalog port');
    }
  }
  for (const edge of assembly.mechanical_tree) {
    const pp = port(edge.parent_node_id, edge.parent_port_id), cp = port(edge.child_node_id, edge.child_port_id);
    if (pp.mount_standard !== 'seedcore.proxy_mount_v1' || cp.mount_standard !== pp.mount_standard
      || !((pp.gender === 'neutral' && cp.gender === 'neutral') || (pp.gender !== cp.gender && [pp.gender, cp.gender].every(g => ['plug', 'socket'].includes(g))))) {
      fail('SEMANTIC_INVALID', 'Incompatible mount standard or gender');
    }
    const expected = mate(pp, cp), actual = edge.relative_transform;
    if (!near(expected.position_m, actual.position_m)
      || !(near(expected.quaternion_wxyz, actual.quaternion_wxyz) || near(expected.quaternion_wxyz, actual.quaternion_wxyz.map(n => -n)))) {
      fail('SEMANTIC_INVALID', 'Rest transform does not mate declared ports');
    }
    if (edge.connection_type === 'articulated_joint') {
      const bounds = documents.get(parts.get(edge.parent_node_id)!.partId).hal_and_safety.simulation_limits;
      const requested = edge.joint.limits_rad;
      if (!bounds || ![bounds.min_rad, bounds.max_rad, bounds.max_rad_s, bounds.max_torque_nm].every(finite)
        || requested.min_rad < bounds.min_rad || requested.max_rad > bounds.max_rad
        || requested.max_velocity_rad_s > bounds.max_rad_s || requested.max_torque_nm > bounds.max_torque_nm) {
        fail('SEMANTIC_INVALID', 'Unknown or exceeded catalog simulation actuator limits');
      }
    }
  }
  // Preserve catalog-aware electrical semantics absent from the structural validator.
  const used = new Map<string, Set<string>>();
  const kinds = { TTL_UART_BUS: 'TTL_UART_BUS', I2C: 'I2C', PWM: 'PWM', power: 'POWER_RAIL', ground: 'POWER_RAIL' };
  for (const net of assembly.electrical_nets) {
    const endpoints = new Set<string>(); let controllers = 0;
    for (const ep of net.endpoints) {
      const key = JSON.stringify([ep.node_id, ep.interface_id]);
      const bus = parts.get(ep.node_id)!.electrical.busInterfaces.find(b => b.interface_id === ep.interface_id);
      const power = net.kind === 'power' || net.kind === 'ground';
      const selected = new Set(ep.pins ?? []);
      if (!bus || endpoints.has(key) || bus.kind !== kinds[net.kind]
        || !(power ? ['source','sink'] : ['controller','peripheral']).includes(bus.role)
        || [...selected].some(pin => !bus.pins.includes(pin)) || (power && !selected.size)) {
        fail('SEMANTIC_INVALID', 'Invalid, duplicate or unpinned electrical endpoint');
      }
      endpoints.add(key); controllers += Number(bus!.role === 'controller');
      const previous = used.get(key) ?? new Set<string>();
      const resources = selected.size ? selected : new Set(['*']);
      if (previous.size && (!power || previous.has('*') || resources.has('*') || [...resources].some(p => previous.has(p)))) {
        fail('SEMANTIC_INVALID', 'Electrical interface/pin reused across nets');
      }
      for (const pin of resources) previous.add(pin);
      used.set(key, previous);
    }
    if (!['power','ground'].includes(net.kind) && controllers > 1) fail('SEMANTIC_INVALID', 'Bus has multiple controllers');
  }
  let fresh: DrcReport;
  try { fresh = evaluateAssemblyDrc(assembly, catalog, input.drcOptions); }
  catch (error) { return fail('SEMANTIC_INVALID', String(error)); }
  if (!input.drcReport) fail('DRC_NOT_READY', 'A current full DRC report is required');
  try {
    if (canonicalAssemblyString(fresh) !== canonicalAssemblyString(input.drcReport)) fail('DRC_BINDING_MISMATCH', 'Missing, stale or altered DRC report');
  } catch (error) {
    if (error instanceof CwS01Error) throw error;
    return fail('DRC_BINDING_MISMATCH', String(error));
  }
  // Sole exception: v2 proxy geometry cannot establish physical fit. Never rewrite DRC.
  const deferred = fresh.findings.filter(f => f.code === 'MECHANICAL_PROXY_UNQUALIFIED' && f.severity === 'blocked');
  const blocking = fresh.findings.filter(f => !deferred.includes(f));
  const readiness: SimulationReadiness = {
    policy: SIMULATION_READINESS_POLICY, scope: 'offline_simulation_only', physicalAcceptance: false, executionAuthority: 'none',
    ready: blocking.length === 0, drcDisposition: fresh.disposition,
    deferredPhysicalFindings: deferred.map(f => f.id), blockingFindings: blocking.map(f => f.id),
  };
  return { assembly, catalog, parts, chain, edges, drc: fresh, readiness, drcOptionsDigest: hash(input.drcOptions ?? {}) };
}

/** Separate versioned readiness result; the supplied full DRC report stays unchanged. */
export function assessSimulationReadiness(input: CompilerInput): SimulationReadiness {
  return structuredClone(prepare(input).readiness);
}

export interface ModelManifest {
  compiler: typeof CW_S01_COMPILER;
  subset: typeof CW_S01_SUBSET;
  assemblyDigest: string;
  catalogDigest: string;
  electricalPlanDigest: string;
  drcDigest: string;
  drcOptionsDigest: string;
  options: { actuatorMode: 'position' | 'torque'; positionGain: number | null; timestepSeconds: number };
  catalogProvenance: DrcCatalog['provenance'];
  readiness: SimulationReadiness;
  bodies: { nodeId: string; bodyName: string; parentNodeId: string | null }[];
  joints: { jointId: string; jointName: string; actuatorName: string; childNodeId: string; restAngleRad: number; maxVelocityRadS: number }[];
  limitations: string[];
}
export interface CompiledMjcf {
  schemaVersion: 'seedcore.cw-s01.model.v1';
  scope: 'offline_simulation_only';
  physicalAcceptance: false;
  executionAuthority: 'none';
  xml: string;
  manifest: ModelManifest;
  modelDigest: string;
}
export interface CurrentModelBinding {
  assemblyDigest: string; catalogDigest: string; drcDigest: string; modelDigest: string;
}
const number = (n: number): string => Object.is(n, -0) ? '0' : String(n);
const numbers = (v: readonly number[]): string => v.map(number).join(' ');

/** Deterministic, asset-free MJCF for the declared serial fixed-base subset. */
export function compileAssemblyToMjcf(input: CompilerInput): CompiledMjcf {
  const p = prepare(input);
  if (!p.readiness.ready) fail('DRC_NOT_READY', `Simulation-blocking DRC findings: ${p.readiness.blockingFindings.join(', ')}`);
  const opt = input.options;
  if (!opt || Object.keys(opt).some(k => !['actuatorMode', 'positionGain', 'timestepSeconds'].includes(k))
    || !['position', 'torque'].includes(opt.actuatorMode)) fail('OPTIONS_INVALID', 'Select position or ideal torque mode; arbitrary XML/assets are unsupported');
  const dt = opt.timestepSeconds ?? 0.002;
  const kp = opt.actuatorMode === 'position' ? opt.positionGain ?? 10 : null;
  if (!finite(dt) || dt < 0.0001 || dt > 0.01 || (kp !== null && (!finite(kp) || kp <= 0 || kp > 1000))
    || (opt.actuatorMode === 'torque' && opt.positionGain !== undefined)) fail('OPTIONS_INVALID', 'Invalid explicit model timing/gain settings');
  const manifest: ModelManifest = {
    compiler: CW_S01_COMPILER, subset: CW_S01_SUBSET, assemblyDigest: p.drc.assemblyDigest,
    catalogDigest: p.drc.catalogDigest, electricalPlanDigest: p.drc.electricalPlanDigest,
    drcDigest: hash(p.drc), drcOptionsDigest: p.drcOptionsDigest,
    options: { actuatorMode: opt.actuatorMode, positionGain: kp, timestepSeconds: dt },
    catalogProvenance: p.catalog.provenance, readiness: p.readiness, bodies: [], joints: [],
    limitations: ['Proxy boxes have no contact collisions.', 'Ideal actuator models omit electrical and thermal dynamics.',
      'Velocity limits are metadata, not enforced by MJCF.', 'No runtime admission, hardware capability or physical acceptance.'],
  };
  const xml = ['<mujoco model="seedcore_cw_s01">',
    '  <compiler angle="radian" inertiafromgeom="false" fusestatic="false" balanceinertia="false"/>',
    `  <option timestep="${number(dt)}" gravity="0 0 -9.81"/>`, '  <worldbody>'];
  const actuators: string[] = [];
  for (const [i, nodeId] of p.chain.entries()) {
    const part = p.parts.get(nodeId)!, m = part.mechanical, edge = p.edges.get(nodeId);
    const rest = edge?.relative_transform ?? { position_m: [0, 0, 0] as V3, quaternion_wxyz: [1, 0, 0, 0] as Q4 };
    const indent = '  '.repeat(i+2), name = `cw_body_${i}`;
    manifest.bodies.push({ nodeId, bodyName: name, parentNodeId: edge?.parent_node_id ?? null });
    xml.push(`${indent}<body name="${name}" pos="${numbers(rest.position_m)}" quat="${numbers(rest.quaternion_wxyz)}">`);
    if (edge?.connection_type === 'articulated_joint') {
      const j = edge.joint, l = j.limits_rad, index = manifest.joints.length;
      const jointName = `cw_joint_${index}`, actuatorName = `cw_actuator_${index}`;
      // Joint declarations are in the parent-part frame; MJCF uses the child-body frame.
      const q = inverse(rest.quaternion_wxyz), axis = rotate(q, j.axis);
      const pivot = rotate(q, j.pivot_m.map((n, k) => n-rest.position_m[k]) as V3);
      xml.push(`${indent}  <joint name="${jointName}" type="hinge" pos="${numbers(pivot)}" axis="${numbers(axis)}" ref="${number(j.rest_angle_rad)}" limited="true" range="${numbers([l.min_rad, l.max_rad])}" actuatorfrclimited="true" actuatorfrcrange="${numbers([-l.max_torque_nm, l.max_torque_nm])}"/>`);
      const common = `name="${actuatorName}" joint="${jointName}" gear="1" ctrllimited="true" forcelimited="true" forcerange="${numbers([-l.max_torque_nm, l.max_torque_nm])}"`;
      actuators.push(opt.actuatorMode === 'position'
        ? `    <position ${common} kp="${number(kp!)}" ctrlrange="${numbers([l.min_rad, l.max_rad])}"/>`
        : `    <motor ${common} ctrlrange="${numbers([-l.max_torque_nm, l.max_torque_nm])}"/>`);
      manifest.joints.push({ jointId: j.joint_id, jointName, actuatorName, childNodeId: nodeId, restAngleRad: j.rest_angle_rad, maxVelocityRadS: l.max_velocity_rad_s });
    }
    const I = m.inertiaKgM2;
    xml.push(`${indent}  <inertial pos="${numbers(m.centerOfMassM)}" mass="${number(m.massKg)}" fullinertia="${numbers([I.ixx, I.iyy, I.izz, I.ixy, I.ixz, I.iyz])}"/>`);
    xml.push(`${indent}  <geom name="cw_box_${i}" type="box" size="${numbers(m.sizeM.map(n => n/2))}" mass="0" contype="0" conaffinity="0"/>`);
  }
  for (let i = p.chain.length-1; i >= 0; --i) xml.push(`${'  '.repeat(i+2)}</body>`);
  xml.push('  </worldbody>', '  <actuator>', ...actuators, '  </actuator>', '</mujoco>', '');
  const payload = { schemaVersion: 'seedcore.cw-s01.model.v1' as const, scope: 'offline_simulation_only' as const,
    physicalAcceptance: false as const, executionAuthority: 'none' as const, xml: xml.join('\n'), manifest };
  return { ...payload, modelDigest: hash(payload) };
}

/** Validate cached bytes against independently retained current build/model bindings. */
export function assertCompiledModelCurrent(artifact: CompiledMjcf, expected: CurrentModelBinding): void {
  try {
    const { modelDigest, ...payload } = artifact;
    if (artifact.schemaVersion !== 'seedcore.cw-s01.model.v1' || artifact.scope !== 'offline_simulation_only'
      || artifact.physicalAcceptance !== false || artifact.executionAuthority !== 'none'
      || modelDigest !== hash(payload) || modelDigest !== expected.modelDigest
      || artifact.manifest.assemblyDigest !== expected.assemblyDigest
      || artifact.manifest.catalogDigest !== expected.catalogDigest
      || artifact.manifest.drcDigest !== expected.drcDigest) fail('MODEL_BINDING_MISMATCH', 'Stale or altered compiled model');
  } catch (error) {
    if (error instanceof CwS01Error) throw error;
    fail('MODEL_BINDING_MISMATCH', String(error));
  }
}
