/** Offline assembly v2 authoring contract; never an execution grant. */
import { Ajv2020 } from "ajv/dist/2020.js";
import { ROBOT_ASSEMBLY_SCHEMA } from "./robotAssemblySchema.js";

/** Historical draft identifier only; v1 is not accepted by this validator. */
export const SEEDCORE_ASSEMBLY_SCHEMA_V1 = "seedcore.assembly.v1" as const;
export const SEEDCORE_ASSEMBLY_SCHEMA_V2 = "seedcore.assembly.v2" as const;
export const ASSEMBLY_CANONICAL_PROFILE = "seedcore.jcs-safe-integers.v1" as const;
export const ASSEMBLY_ROLE_VALUES = ["chassis", "actuator", "sensor", "mcu", "power", "bracket", "link", "payload", "other"] as const;
export type AssemblyRole = (typeof ASSEMBLY_ROLE_VALUES)[number];
export const CONNECTION_TYPE_VALUES = ["rigid_mount", "articulated_joint"] as const;
export type ConnectionType = (typeof CONNECTION_TYPE_VALUES)[number];
export const JOINT_KIND_VALUES = ["revolute"] as const;
export type JointKind = (typeof JOINT_KIND_VALUES)[number];
export const NET_KIND_VALUES = ["TTL_UART_BUS", "I2C", "PWM", "power", "ground"] as const;
export type NetKind = (typeof NET_KIND_VALUES)[number];
export interface RelativeTransform {
  position_m: [number, number, number];
  quaternion_wxyz: [number, number, number, number];
}
export interface AssemblyIdentity {
  assembly_id: string;
  version: string;
  name: string;
  status: "draft" | "documented";
  created_at: string;
  notes: string;
}
export interface AssemblyNode {
  node_id: string;
  part_id: string;
  part_version: string;
  part_sha256: string;
  role: AssemblyRole;
  display_name?: string;
}
export interface JointLimits {
  min_rad: number;
  max_rad: number;
  max_velocity_rad_s: number;
  max_torque_nm: number;
}
export interface JointRecord {
  joint_id: string;
  kind: JointKind;
  frame: "parent_part";
  axis: [number, number, number];
  pivot_m: [number, number, number];
  actuator_node_id: string;
  actuator_channel: number;
  rest_angle_rad: number;
  limits_rad: JointLimits;
}
export interface ActuatorOutput {
  node_id: string;
  port_id: string;
  channel: number;
  basis: "simulation_proxy";
  axis: [number, number, number];
  pivot_m: [number, number, number];
}
interface MechanicalEdgeBase {
  edge_id: string;
  parent_node_id: string;
  parent_port_id: string;
  child_node_id: string;
  child_port_id: string;
  relative_transform: RelativeTransform;
}
export type MechanicalEdge = MechanicalEdgeBase & (
  | { connection_type: "rigid_mount"; joint?: never }
  | { connection_type: "articulated_joint"; joint: JointRecord }
);
export interface NetEndpoint {
  node_id: string;
  interface_id: string;
  pins?: string[];
}
export interface ElectricalNet {
  net_id: string;
  kind: NetKind;
  nominal_voltage_v?: number | null;
  endpoints: NetEndpoint[];
}
export interface RobotAssembly {
  schema_version: typeof SEEDCORE_ASSEMBLY_SCHEMA_V2;
  canonicalization: typeof ASSEMBLY_CANONICAL_PROFILE;
  runtime_profile: "offline_proxy_no_actuation";
  mating_convention: "opposed_z_rx_pi";
  identity: AssemblyIdentity;
  root_node_id: string;
  nodes: AssemblyNode[];
  mechanical_tree: MechanicalEdge[];
  actuator_outputs: ActuatorOutput[];
  electrical_nets: ElectricalNet[];
  metadata?: { notes?: string; generator?: string };
}

/** RFC 8785 serialization, restricted to safe integral numbers and bounded JSON. */
export function canonicalAssemblyString(data: unknown): string {
  let count = 0;
  const encode = (value: unknown, depth: number): string => {
    if (++count > 50000 || depth > 32) throw new Error("Assembly JSON nesting/node bound exceeded");
    if (value === null) return "null";
    if (typeof value === "string") {
      if (value.length > 262144 || /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(value)) {
        throw new Error("Invalid Unicode or oversized assembly string");
      }
      return JSON.stringify(value);
    }
    if (typeof value === "number") {
      if (!Number.isFinite(value)) throw new Error("Non-finite number in assembly");
      if (Number.isInteger(value) && !Number.isSafeInteger(value)) throw new Error("Unsafe integer in assembly");
      return JSON.stringify(value);
    }
    if (typeof value === "boolean") return JSON.stringify(value);
    if (Array.isArray(value)) {
      // Array.map skips holes, which would silently change the serialized value.
      return `[${Array.from(value, item => encode(item, depth + 1)).join(",")}]`;
    }
    if (typeof value === "object" && value !== null &&
        (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null)) {
      if (Object.getOwnPropertySymbols(value).length) throw new Error("Non-JSON assembly key");
      const object = value as Record<string, unknown>;
      return `{${Object.keys(object).sort().map(key => `${encode(key, depth + 1)}:${encode(object[key], depth + 1)}`).join(",")}}`;
    }
    throw new Error("Assembly contains a non-JSON value");
  };
  const result = encode(data, 0);
  if (new TextEncoder().encode(result).length > 262144) throw new Error("Assembly JSON exceeds size bound");
  return result;
}

const ajv = new Ajv2020({ strict: true, strictRequired: false });
const validateSchema = ajv.compile<RobotAssembly>(ROBOT_ASSEMBLY_SCHEMA);
const keyFor = (node: string, port: string | number): string => `${node}:${port}`;
const unit = (v: number[], label: string): void => {
  if (Math.abs(v.reduce((s, n) => s + n*n, 0) - 1) > 1e-8) throw new Error(`${label} must be unit length`);
};
const near = (a: number[], b: number[]): boolean => a.every((n, i) => Math.abs(n-b[i]) <= 1e-8);

/** Schema + catalog-independent graph checks. Catalog/geometry/DRC remain separate. */
export function validateAssemblyStructure(raw: unknown): RobotAssembly {
  canonicalAssemblyString(raw);
  if (!validateSchema(raw)) throw new Error(`Assembly schema: ${ajv.errorsText(validateSchema.errors)}`);
  const data = raw;
  const nodes = new Set(data.nodes.map(n => n.node_id));
  if (nodes.size !== data.nodes.length) throw new Error("Duplicate node_id");
  if (!nodes.has(data.root_node_id)) throw new Error("root_node_id not present in nodes");
  if (data.mechanical_tree.length !== nodes.size - 1) throw new Error("Mechanical tree must have N-1 edges");
  const children = new Map([...nodes].map(id => [id, [] as string[]]));
  const parents = new Set<string>(), edgeIds = new Set<string>(), joints = new Set<string>();
  const ports = new Set<string>(), channels = new Set<string>();
  for (const edge of data.mechanical_tree) {
    const p = edge.parent_node_id, c = edge.child_node_id;
    if (edgeIds.has(edge.edge_id)) throw new Error("Duplicate edge_id");
    edgeIds.add(edge.edge_id);
    if (!nodes.has(p) || !nodes.has(c)) throw new Error("Mechanical endpoint not in nodes");
    if (p === c) throw new Error("Self-loop detected");
    if (c === data.root_node_id) throw new Error("Root node cannot be a child");
    if (parents.has(c)) throw new Error("Node has multiple parents");
    parents.add(c); children.get(p)!.push(c);
    for (const key of [keyFor(p, edge.parent_port_id), keyFor(c, edge.child_port_id)]) {
      if (ports.has(key)) throw new Error("Duplicate occupied port");
      ports.add(key);
    }
    unit(edge.relative_transform.quaternion_wxyz, "Transform quaternion");
    if (edge.connection_type === "articulated_joint") {
      const j = edge.joint, limits = j.limits_rad;
      if (joints.has(j.joint_id)) throw new Error("Duplicate joint_id");
      joints.add(j.joint_id); unit(j.axis, "Rotation axis");
      if (limits.min_rad >= limits.max_rad) throw new Error("Joint range must have positive width");
      if (j.rest_angle_rad < limits.min_rad || j.rest_angle_rad > limits.max_rad) throw new Error("Rest angle outside limits");
      const key = keyFor(j.actuator_node_id, j.actuator_channel);
      if (channels.has(key)) throw new Error("Actuator channel assigned to multiple joints");
      channels.add(key);
      if (j.actuator_node_id !== p) throw new Error("Actuator output must belong to parent node");
    }
  }
  const visited = new Set<string>(), queue = [data.root_node_id];
  while (queue.length) {
    const node = queue.pop()!;
    if (visited.has(node)) throw new Error("Mechanical cycle");
    visited.add(node); queue.push(...children.get(node)!);
  }
  if (visited.size !== nodes.size) throw new Error("Disconnected or unreachable nodes");
  const outputs = new Map<string, ActuatorOutput>(), outputPorts = new Set<string>();
  for (const output of data.actuator_outputs) {
    const key = keyFor(output.node_id, output.channel), port = keyFor(output.node_id, output.port_id);
    if (!nodes.has(output.node_id) || outputs.has(key) || outputPorts.has(port)) throw new Error("Invalid or duplicate actuator output");
    unit(output.axis, "Output axis"); outputs.set(key, output); outputPorts.add(port);
  }
  for (const edge of data.mechanical_tree) {
    if (edge.connection_type === "articulated_joint") {
      const j = edge.joint, output = outputs.get(keyFor(j.actuator_node_id, j.actuator_channel));
      if (!output || output.port_id !== edge.parent_port_id) throw new Error("Unknown actuator output/channel");
      if (!near(output.axis, j.axis) || !near(output.pivot_m, j.pivot_m)) throw new Error("Joint frame differs from declared output");
    } else if (outputPorts.has(keyFor(edge.parent_node_id, edge.parent_port_id))) {
      throw new Error("Rotating output requires articulated_joint");
    }
    if (outputPorts.has(keyFor(edge.child_node_id, edge.child_port_id))) throw new Error("Rotating output cannot be housing attachment");
  }
  const nets = new Set<string>();
  for (const net of data.electrical_nets) {
    if (nets.has(net.net_id)) throw new Error("Duplicate net_id");
    nets.add(net.net_id);
    for (const ep of net.endpoints) if (!nodes.has(ep.node_id)) throw new Error("Electrical endpoint not in nodes");
  }
  return structuredClone(data);
}
