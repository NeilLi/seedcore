/**
 * Central World Robot Assembly Contract types and structural validation.
 *
 * Provides schema types, constants, and canonical serialization for CW-A01
 * versioned assembly graphs (seedcore.assembly.v1).
 */

export const SEEDCORE_ASSEMBLY_SCHEMA_V1 = "seedcore.assembly.v1" as const;

export const ASSEMBLY_ROLE_VALUES = [
  "chassis",
  "actuator",
  "sensor",
  "mcu",
  "power",
  "bracket",
  "link",
  "payload",
  "other",
] as const;
export type AssemblyRole = (typeof ASSEMBLY_ROLE_VALUES)[number];

export const CONNECTION_TYPE_VALUES = [
  "rigid_mount",
  "articulated_joint",
] as const;
export type ConnectionType = (typeof CONNECTION_TYPE_VALUES)[number];

export const JOINT_KIND_VALUES = [
  "revolute",
  "fixed",
  "continuous",
  "prismatic",
] as const;
export type JointKind = (typeof JOINT_KIND_VALUES)[number];

export const NET_KIND_VALUES = [
  "TTL_UART_BUS",
  "I2C",
  "PWM",
  "GPIO",
  "power",
  "ground",
  "other",
] as const;
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
  max_velocity_rad_s?: number | null;
  max_torque_nm?: number | null;
}

export interface JointRecord {
  joint_id: string;
  kind: JointKind;
  axis: [number, number, number];
  pivot_m: [number, number, number];
  actuator_node_id?: string | null;
  actuator_channel?: number | string | null;
  rest_angle_rad: number;
  limits_rad: JointLimits;
}

export interface MechanicalEdge {
  edge_id: string;
  parent_node_id: string;
  parent_port_id: string;
  child_node_id: string;
  child_port_id: string;
  connection_type: ConnectionType;
  relative_transform?: RelativeTransform;
  joint?: JointRecord;
}

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
  schema_version: typeof SEEDCORE_ASSEMBLY_SCHEMA_V1;
  identity: AssemblyIdentity;
  root_node_id: string;
  nodes: AssemblyNode[];
  mechanical_tree: MechanicalEdge[];
  electrical_nets: ElectricalNet[];
  metadata?: {
    notes?: string;
    generator?: string;
  };
}

/**
 * Return RFC-8785 style canonical JSON string for deterministic hashing.
 */
export function canonicalAssemblyString(data: unknown): string {
  function sortKeys(value: unknown): unknown {
    if (value === null || typeof value !== "object") {
      if (typeof value === "number" && !Number.isFinite(value)) {
        throw new Error(`Non-finite number in assembly: ${value}`);
      }
      return value;
    }
    if (Array.isArray(value)) {
      return value.map(sortKeys);
    }
    const sortedObj: Record<string, unknown> = {};
    const keys = Object.keys(value as Record<string, unknown>).sort();
    for (const key of keys) {
      const val = (value as Record<string, unknown>)[key];
      if (val !== undefined) {
        sortedObj[key] = sortKeys(val);
      }
    }
    return sortedObj;
  }

  return JSON.stringify(sortKeys(data));
}

/**
 * Validate structural requirements of a RobotAssembly object.
 */
export function validateAssemblyStructure(raw: unknown): RobotAssembly {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("Assembly must be a non-null object");
  }
  const obj = raw as Record<string, unknown>;

  if (obj.schema_version !== SEEDCORE_ASSEMBLY_SCHEMA_V1) {
    throw new Error(`Invalid schema_version: ${obj.schema_version}`);
  }

  if (!obj.identity || typeof obj.identity !== "object") {
    throw new Error("Missing or invalid identity block");
  }
  const idBlock = obj.identity as Record<string, unknown>;
  if (typeof idBlock.assembly_id !== "string" || !idBlock.assembly_id) {
    throw new Error("Invalid assembly_id");
  }

  if (typeof obj.root_node_id !== "string" || !obj.root_node_id) {
    throw new Error("Invalid root_node_id");
  }

  if (!Array.isArray(obj.nodes) || obj.nodes.length === 0) {
    throw new Error("nodes must be a non-empty array");
  }

  const nodeIds = new Set<string>();
  for (const n of obj.nodes) {
    if (!n || typeof n !== "object") throw new Error("Invalid node entry");
    const node = n as Record<string, unknown>;
    if (typeof node.node_id !== "string" || !node.node_id) throw new Error("Invalid node_id");
    if (nodeIds.has(node.node_id)) throw new Error(`Duplicate node_id: ${node.node_id}`);
    nodeIds.add(node.node_id);

    if (typeof node.part_id !== "string" || !node.part_id) throw new Error("Invalid part_id");
    if (typeof node.part_sha256 !== "string" || node.part_sha256.length !== 64) {
      throw new Error(`Invalid part_sha256 for node ${node.node_id}`);
    }
  }

  if (!nodeIds.has(obj.root_node_id as string)) {
    throw new Error(`root_node_id '${obj.root_node_id}' not present in nodes`);
  }

  if (!Array.isArray(obj.mechanical_tree)) {
    throw new Error("mechanical_tree must be an array");
  }

  const expectedEdges = obj.nodes.length - 1;
  if (obj.mechanical_tree.length !== expectedEdges) {
    throw new Error(
      `mechanical_tree must have N-1 (${expectedEdges}) edges, got ${obj.mechanical_tree.length}`
    );
  }

  const childIds = new Set<string>();
  for (const e of obj.mechanical_tree) {
    if (!e || typeof e !== "object") throw new Error("Invalid mechanical edge");
    const edge = e as Record<string, unknown>;
    const pNode = edge.parent_node_id as string;
    const cNode = edge.child_node_id as string;

    if (!nodeIds.has(pNode)) throw new Error(`Parent node not found: ${pNode}`);
    if (!nodeIds.has(cNode)) throw new Error(`Child node not found: ${cNode}`);
    if (pNode === cNode) throw new Error(`Self-loop detected on node ${pNode}`);
    if (cNode === obj.root_node_id) throw new Error(`Root node cannot be a child: ${cNode}`);
    if (childIds.has(cNode)) throw new Error(`Node has multiple parents: ${cNode}`);
    childIds.add(cNode);

    const connType = edge.connection_type as string;
    if (connType === "rigid_mount") {
      if (edge.joint) throw new Error(`Rigid mount edge '${edge.edge_id}' cannot declare a joint`);
    } else if (connType === "articulated_joint") {
      if (!edge.joint || typeof edge.joint !== "object") {
        throw new Error(`Articulated joint edge '${edge.edge_id}' must declare joint details`);
      }
    } else {
      throw new Error(`Unknown connection_type: ${connType}`);
    }
  }

  if (!Array.isArray(obj.electrical_nets)) {
    throw new Error("electrical_nets must be an array");
  }

  return raw as RobotAssembly;
}
