/**
 * CW-A04 (CW-DRC-01..03): Pure deterministic assembly DRC, routing proposals,
 * 3D rotated/parallel-axis mass & inertia solver, and unknown-aware BOM.
 * Never grants HAL or runtime execution authority.
 */
import {
  canonicalAssemblyString,
  parseStrictJson,
  validateAssemblyStructure,
  type AssemblyRole,
  type RelativeTransform,
  type RobotAssembly,
} from '@seedcore/contracts';

export type DrcDisposition = 'pass' | 'blocked' | 'conflict';
export type DrcRuleId = 'CW-DRC-01' | 'CW-DRC-02' | 'CW-DRC-03';
export type DrcCategory =
  | 'uart_routing'
  | 'i2c_routing'
  | 'gpio_pinout'
  | 'power_rail'
  | 'mechanics_mass'
  | 'bom_cost';

export interface DrcInertiaTensor {
  ixx: number;
  iyy: number;
  izz: number;
  ixy: number;
  ixz: number;
  iyz: number;
}

export interface DrcSupplierSku {
  supplier: string;
  sku: string;
  url: string;
  quoted_on: string | null;
}

export interface DrcBusInterface {
  interface_id: string;
  kind: 'TTL_UART_BUS' | 'I2C' | 'PWM' | 'SPI' | 'POWER_RAIL' | 'CAMERA_PARALLEL';
  role: 'controller' | 'peripheral' | 'source' | 'sink';
  protocol: string | null;
  logic_min_v: number | null;
  logic_max_v: number | null;
  i2c_address: number | null;
  pins: string[];
}

export interface DrcSnapPort extends RelativeTransform {
  port_id: string;
  mount_standard: string;
  gender: 'neutral' | 'plug' | 'socket';
  qualification: 'illustrative' | 'drawing_reviewed';
}

export interface DrcPart {
  partId: string;
  version: string;
  sha256: string;
  name: string;
  category: 'mcu' | 'actuator' | 'sensor' | 'power' | 'chassis';
  status: 'draft' | 'documented';
  bomCostUsd: number | null;
  costBasis: 'unknown' | 'estimate' | 'supplier_quote';
  supplierSkus: DrcSupplierSku[];
  mechanical: {
    basis: 'simulation_proxy' | 'drawing_reviewed';
    sizeM: [number, number, number];
    massKg: number;
    centerOfMassM: [number, number, number];
    inertiaKgM2: DrcInertiaTensor;
    snapPorts: DrcSnapPort[];
  };
  electrical: {
    ratingBasis: 'unknown' | 'not_applicable' | 'documented';
    minV: number | null;
    maxV: number | null;
    continuousMa: number | null;
    peakMa: number | null;
    outputCapacityMa: number | null;
    busInterfaces: DrcBusInterface[];
  };
  halAndSafety: {
    capabilities: string[];
    runtimeBinding: null;
    qualification: 'unqualified' | 'qualified';
    executionAuthority: 'none';
  };
}

export interface DrcCatalog {
  catalogDigest: string;
  provenance: 'verified_local_catalog' | 'synthetic_fixture';
  parts: DrcPart[];
}

export interface DrcEvalOptions {
  /** Optional explicit servo IDs keyed by `${nodeId}:${interfaceId}` or `nodeId`. */
  servoIds?: Record<string, number>;
  /** Optional reviewed servo ID bounds by protocol (default [1, 253]). */
  servoIdRangeByProtocol?: Record<string, [number, number]>;
  /** Optional max servos per UART controller interface (default 16). */
  maxServosPerBus?: number;
  /** Optional I2C pull-up supply voltage (V) keyed by net_id. */
  i2cPullUpVoltageByNet?: Record<string, number | null>;
  /** Optional reviewed I2C multiplexer presence keyed by net_id. */
  i2cMuxByNet?: Record<string, boolean>;
  /** Optional additional reserved pins keyed by part_id. */
  reservedPinsByPart?: Record<string, string[]>;
  /** Optional wire current limit (mA) keyed by net_id. */
  wireLimitMaByNet?: Record<string, number>;
  /** Optional fuse current limit (mA) keyed by net_id. */
  fuseLimitMaByNet?: Record<string, number>;
  /** Optional worst-case line/harness voltage drop (V) keyed by net_id. */
  lineDropVByNet?: Record<string, number>;
  /** Required brownout voltage margin above sink min_v (default 0.3 V). */
  brownoutMarginV?: number;
  /** Reviewed continuous/peak regulator derating factor (default 0.8). */
  becDeratingFactor?: number;
  /** Reviewed step-down regulator conversion efficiency (default 0.85). */
  becEfficiency?: number;
  /** Node IDs acting as passive power distribution boards (not power sources). */
  distributionNodeIds?: string[];
  /**
   * Optional caller-claimed current budget assertions to verify against
   * double-counted MCU loads or invalid direct mA summation across unlike voltages.
   */
  claimedLoadAssertions?: {
    mcuCountedTimes?: number;
    summedUnlikeVoltageCurrents?: boolean;
  };
}

export interface DrcFinding {
  id: string;
  ruleId: DrcRuleId;
  category: DrcCategory;
  severity: 'blocked' | 'conflict';
  code: string;
  fieldRefs: string[];
  message: string;
  recommendation?: string;
}

export interface RoutingProposal {
  proposalId: string;
  netId: string | null;
  kind: 'TTL_UART_BUS' | 'I2C' | 'PWM' | 'POWER_RAIL';
  protocol: string | null;
  controllerNodeId: string;
  controllerInterfaceId: string;
  peripheralEndpoints: {
    nodeId: string;
    interfaceId: string;
    assignedDeviceId: number | null;
    i2cAddress: number | null;
  }[];
  logicVoltageWindowV: [number, number] | null;
  status: 'compatible' | 'blocked' | 'conflict';
  reason: string;
}

export interface PowerRailSummary {
  netId: string;
  kind: 'power' | 'ground';
  nominalVoltageV: number | null;
  sourceNodeIds: string[];
  regulatorNodeIds: string[];
  distributionNodeIds: string[];
  sinkNodeIds: string[];
  continuousLoadMa: number | null;
  peakLoadMa: number | null;
  deratedCapacityMa: number | null;
  reflectedUpstreamPeakMa: number | null;
  wireLimitMa: number | null;
  fuseLimitMa: number | null;
  brownoutMarginV: number | null;
  status: DrcDisposition;
}

export interface MassPropertiesSummary {
  totalMassKg: number;
  centerOfMassWorldM: [number, number, number];
  inertiaWorldAtComKgM2: DrcInertiaTensor;
  principalMomentsKgM2: [number, number, number];
  nodeComWorldM: Record<string, [number, number, number]>;
  allPartsDrawingReviewed: boolean;
}

export interface BomLineItem {
  partId: string;
  version: string;
  name: string;
  category: string;
  status: 'draft' | 'documented';
  quantity: number;
  nodeIds: string[];
  unitCostUsd: number | null;
  costBasis: 'unknown' | 'estimate' | 'supplier_quote';
  lineTotalUsd: number | null;
  quotedSkus: number;
}

export interface BomSummary {
  lines: BomLineItem[];
  knownSubtotalUsd: number;
  pricedPartCount: number;
  unpricedPartCount: number;
  uniquePartCount: number;
  totalNodeCount: number;
  completePricing: boolean;
}

export interface DrcReport {
  schemaVersion: 'seedcore.drc.report.v1';
  scope: 'offline_proxy_authoring';
  physicalAcceptance: false;
  executionAuthority: 'none';
  catalogProvenance: 'verified_local_catalog' | 'synthetic_fixture';
  catalogDigest: string;
  assemblyDigest: string;
  electricalPlanDigest: string;
  disposition: DrcDisposition;
  counts: { conflict: number; blocked: number };
  findings: DrcFinding[];
  routingProposals: RoutingProposal[];
  servoAddressesByNet: Record<string, Record<string, number>>;
  powerRails: PowerRailSummary[];
  massProperties: MassPropertiesSummary;
  bom: BomSummary;
}

const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

/** Deterministic synchronous SHA-256 over UTF-8 text. */
export function sha256Hex(text: string): string {
  const bytes = new TextEncoder().encode(text);
  const bitLen = bytes.length * 8;
  const totalLen = (((bytes.length + 9 + 63) >> 6) << 6);
  const buf = new Uint8Array(totalLen);
  buf.set(bytes);
  buf[bytes.length] = 0x80;
  const view = new DataView(buf.buffer);
  view.setUint32(totalLen - 8, Math.floor(bitLen / 0x100000000), false);
  view.setUint32(totalLen - 4, bitLen >>> 0, false);
  const H = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ]);
  const W = new Uint32Array(64);
  const rotr = (x: number, n: number) => (x >>> n) | (x << (32 - n));
  for (let offset = 0; offset < totalLen; offset += 64) {
    for (let i = 0; i < 16; i++) W[i] = view.getUint32(offset + i * 4, false);
    for (let i = 16; i < 64; i++) {
      const s0 = rotr(W[i - 15], 7) ^ rotr(W[i - 15], 18) ^ (W[i - 15] >>> 3);
      const s1 = rotr(W[i - 2], 17) ^ rotr(W[i - 2], 19) ^ (W[i - 2] >>> 10);
      W[i] = (W[i - 16] + s0 + W[i - 7] + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, h] = H;
    for (let i = 0; i < 64; i++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const temp1 = (h + S1 + ch + K[i] + W[i]) >>> 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (S0 + maj) >>> 0;
      h = g; g = f; f = e; e = (d + temp1) >>> 0;
      d = c; c = b; b = a; a = (temp1 + temp2) >>> 0;
    }
    H[0] = (H[0] + a) >>> 0; H[1] = (H[1] + b) >>> 0;
    H[2] = (H[2] + c) >>> 0; H[3] = (H[3] + d) >>> 0;
    H[4] = (H[4] + e) >>> 0; H[5] = (H[5] + f) >>> 0;
    H[6] = (H[6] + g) >>> 0; H[7] = (H[7] + h) >>> 0;
  }
  return Array.from(H, word => word.toString(16).padStart(8, '0')).join('');
}

const lex = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

/** Default reserved/boot/USB/flash/PSRAM pins for ESP32-S3 family boards. */
export const ESP32_S3_RESERVED_PINS: ReadonlySet<string> = new Set([
  'GPIO0', 'GPIO3', 'GPIO45', 'GPIO46', // Boot / strapping pins
  'GPIO19', 'GPIO20', // Native USB D- / D+
  'GPIO26', 'GPIO27', 'GPIO28', 'GPIO29', 'GPIO30', 'GPIO31', 'GPIO32', // SPI flash
  'GPIO35', 'GPIO36', 'GPIO37', // Octal PSRAM / flash (WROOM-1-N8R8)
]);

/** Parse and verify a DRC catalog from raw `.sc-part.json` payloads. */
export function parseDrcCatalogFromRaw(input: {
  catalogSha256: string;
  catalogRawJson: string;
  partDocuments: { part_id: string; raw_json: string }[];
  provenance?: 'verified_local_catalog' | 'synthetic_fixture';
}): DrcCatalog {
  if (sha256Hex(input.catalogRawJson) !== input.catalogSha256) {
    throw new Error('DRC catalog SHA-256 mismatch');
  }
  const index = parseStrictJson(input.catalogRawJson) as {
    parts: { part_id: string; version: string; sha256: string }[];
  };
  if (
    !Array.isArray(index.parts) ||
    index.parts.length < 1 ||
    index.parts.length > 256 ||
    !Array.isArray(input.partDocuments) ||
    input.partDocuments.length !== index.parts.length
  ) {
    throw new Error('Invalid DRC catalog part count');
  }
  const pins = new Map(index.parts.map(p => [p.part_id, p]));
  if (pins.size !== index.parts.length) throw new Error('Duplicate catalog part_id');
  const seen = new Set<string>();
  const parts: DrcPart[] = input.partDocuments.map(doc => {
    if (seen.has(doc.part_id)) throw new Error('Duplicate DRC part document');
    seen.add(doc.part_id);
    const pin = pins.get(doc.part_id);
    const raw = parseStrictJson(doc.raw_json) as any;
    const digest = sha256Hex(doc.raw_json);
    if (
      !pin ||
      digest !== pin.sha256 ||
      raw.identity?.part_id !== pin.part_id ||
      raw.identity?.version !== pin.version ||
      raw.hal_and_safety?.execution_authority !== 'none' ||
      raw.hal_and_safety?.runtime_binding !== null
    ) {
      throw new Error(`DRC part pin or authority mismatch for ${doc.part_id}`);
    }
    return {
      partId: pin.part_id,
      version: pin.version,
      sha256: pin.sha256,
      name: String(raw.identity.name),
      category: raw.identity.category,
      status: raw.identity.status,
      bomCostUsd: raw.identity.bom_cost_usd,
      costBasis: raw.identity.cost_basis,
      supplierSkus: Array.isArray(raw.identity.supplier_skus) ? raw.identity.supplier_skus : [],
      mechanical: {
        basis: raw.mechanical.basis,
        sizeM: raw.mechanical.collision.size_m,
        massKg: raw.mechanical.mass_kg,
        centerOfMassM: raw.mechanical.center_of_mass_m,
        inertiaKgM2: raw.mechanical.inertia_kg_m2,
        snapPorts: raw.mechanical.snap_ports,
      },
      electrical: {
        ratingBasis: raw.electrical.rating_basis,
        minV: raw.electrical.min_v,
        maxV: raw.electrical.max_v,
        continuousMa: raw.electrical.continuous_ma,
        peakMa: raw.electrical.peak_ma,
        outputCapacityMa: raw.electrical.output_capacity_ma,
        busInterfaces: raw.electrical.bus_interfaces,
      },
      halAndSafety: {
        capabilities: raw.hal_and_safety.capabilities,
        runtimeBinding: null,
        qualification: raw.hal_and_safety.qualification,
        executionAuthority: 'none',
      },
    };
  });
  parts.sort((a, b) => lex(a.partId, b.partId));
  return {
    catalogDigest: input.catalogSha256,
    provenance: input.provenance ?? 'verified_local_catalog',
    parts,
  };
}

/** Rotation matrix R from unit quaternion [w, x, y, z] (active local-to-parent). */
export function quaternionToMatrix3(q: readonly [number, number, number, number]): [
  [number, number, number],
  [number, number, number],
  [number, number, number],
] {
  const [w, x, y, z] = q;
  const normSq = w * w + x * x + y * y + z * z;
  if (!Number.isFinite(normSq) || Math.abs(normSq - 1) > 1e-8) {
    throw new Error('Quaternion [w,x,y,z] must have unit norm');
  }
  return [
    [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
    [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
    [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
  ];
}

function matVec3(
  R: readonly [readonly number[], readonly number[], readonly number[]],
  v: readonly [number, number, number],
): [number, number, number] {
  return [
    R[0][0] * v[0] + R[0][1] * v[1] + R[0][2] * v[2],
    R[1][0] * v[0] + R[1][1] * v[1] + R[1][2] * v[2],
    R[2][0] * v[0] + R[2][1] * v[1] + R[2][2] * v[2],
  ];
}

function quatMul(
  a: readonly [number, number, number, number],
  b: readonly [number, number, number, number],
): [number, number, number, number] {
  const [w, x, y, z] = a;
  const [v, i, j, k] = b;
  return [
    w * v - x * i - y * j - z * k,
    w * i + x * v + y * k - z * j,
    w * j - x * k + y * v + z * i,
    w * k + x * j - y * i + z * v,
  ];
}

/** Compute structural world rest transforms from validated assembly. */
export function computeWorldTransforms(assembly: RobotAssembly): Record<string, RelativeTransform> {
  const valid = validateAssemblyStructure(assembly);
  const result: Record<string, RelativeTransform> = {
    [valid.root_node_id]: { position_m: [0, 0, 0], quaternion_wxyz: [1, 0, 0, 0] },
  };
  const children = new Map<string, typeof valid.mechanical_tree>();
  for (const edge of valid.mechanical_tree) {
    const list = children.get(edge.parent_node_id) ?? [];
    list.push(edge);
    children.set(edge.parent_node_id, list);
  }
  const queue = [valid.root_node_id];
  while (queue.length) {
    const parentId = queue.shift()!;
    const parentPose = result[parentId];
    const R = quaternionToMatrix3(parentPose.quaternion_wxyz);
    for (const edge of children.get(parentId) ?? []) {
      const offset = matVec3(R, edge.relative_transform.position_m);
      result[edge.child_node_id] = {
        position_m: [
          parentPose.position_m[0] + offset[0],
          parentPose.position_m[1] + offset[1],
          parentPose.position_m[2] + offset[2],
        ],
        quaternion_wxyz: quatMul(parentPose.quaternion_wxyz, edge.relative_transform.quaternion_wxyz),
      };
      queue.push(edge.child_node_id);
    }
  }
  return result;
}

/** Analytical eigenvalues (sorted ascending) for a symmetric 3x3 inertia tensor. */
export function symmetricEigenvalues3(tensor: DrcInertiaTensor): [number, number, number] {
  const { ixx, iyy, izz, ixy, ixz, iyz } = tensor;
  if ([ixx, iyy, izz, ixy, ixz, iyz].some(v => typeof v !== 'number' || !Number.isFinite(v))) {
    throw new Error('Inertia tensor contains non-finite numbers');
  }
  const p1 = ixy * ixy + ixz * ixz + iyz * iyz;
  if (p1 <= 1e-30) {
    return [ixx, iyy, izz].sort((a, b) => a - b) as [number, number, number];
  }
  const q = (ixx + iyy + izz) / 3;
  const p2 = (ixx - q) ** 2 + (iyy - q) ** 2 + (izz - q) ** 2 + 2 * p1;
  const p = Math.sqrt(p2 / 6);
  const b00 = (ixx - q) / p, b01 = ixy / p, b02 = ixz / p;
  const b11 = (iyy - q) / p, b12 = iyz / p, b22 = (izz - q) / p;
  const detB =
    b00 * (b11 * b22 - b12 * b12) -
    b01 * (b01 * b22 - b12 * b02) +
    b02 * (b01 * b12 - b11 * b02);
  const r = Math.max(-1, Math.min(1, detB / 2));
  const phi = Math.acos(r) / 3;
  const eig3 = q + 2 * p * Math.cos(phi);
  const eig1 = q + 2 * p * Math.cos(phi + (2 * Math.PI) / 3);
  const eig2 = 3 * q - eig1 - eig3;
  return [eig1, eig2, eig3].sort((a, b) => a - b) as [number, number, number];
}

/** Validate physical positive-definiteness and triangle inequality of a 3x3 inertia tensor. */
export function isValidInertiaTensor(tensor: DrcInertiaTensor): {
  valid: boolean;
  principalMoments: [number, number, number];
  reason?: string;
} {
  try {
    const moments = symmetricEigenvalues3(tensor);
    if (moments[0] <= 0) {
      return { valid: false, principalMoments: moments, reason: 'Inertia tensor is not positive definite' };
    }
    const tol = Math.max(1e-15, moments[2] * 1e-8);
    if (moments[2] > moments[0] + moments[1] + tol) {
      return {
        valid: false,
        principalMoments: moments,
        reason: 'Principal moments violate rigid-body triangle inequality',
      };
    }
    return { valid: true, principalMoments: moments };
  } catch (error) {
    return {
      valid: false,
      principalMoments: [0, 0, 0],
      reason: error instanceof Error ? error.message : 'Invalid inertia tensor',
    };
  }
}

/** Rotate a symmetric 3x3 inertia tensor into world orientation: R * I * R^T (retaining off-diagonals). */
export function rotateInertiaTensor(
  tensor: DrcInertiaTensor,
  quaternionWxyz: readonly [number, number, number, number],
): DrcInertiaTensor {
  const R = quaternionToMatrix3(quaternionWxyz);
  const I = [
    [tensor.ixx, tensor.ixy, tensor.ixz],
    [tensor.ixy, tensor.iyy, tensor.iyz],
    [tensor.ixz, tensor.iyz, tensor.izz],
  ];
  const RI: number[][] = [
    [0, 0, 0],
    [0, 0, 0],
    [0, 0, 0],
  ];
  for (let r = 0; r < 3; r++) {
    for (let c = 0; c < 3; c++) {
      RI[r][c] = R[r][0] * I[0][c] + R[r][1] * I[1][c] + R[r][2] * I[2][c];
    }
  }
  const out: number[][] = [
    [0, 0, 0],
    [0, 0, 0],
    [0, 0, 0],
  ];
  for (let r = 0; r < 3; r++) {
    for (let c = 0; c < 3; c++) {
      out[r][c] = RI[r][0] * R[c][0] + RI[r][1] * R[c][1] + RI[r][2] * R[c][2];
    }
  }
  return {
    ixx: out[0][0],
    iyy: out[1][1],
    izz: out[2][2],
    ixy: 0.5 * (out[0][1] + out[1][0]),
    ixz: 0.5 * (out[0][2] + out[2][0]),
    iyz: 0.5 * (out[1][2] + out[2][1]),
  };
}

/** Shift an inertia tensor from node COM to target origin by displacement d = c_node - c_target. */
export function parallelAxisShift(
  tensor: DrcInertiaTensor,
  massKg: number,
  displacementM: readonly [number, number, number],
): DrcInertiaTensor {
  const [dx, dy, dz] = displacementM;
  return {
    ixx: tensor.ixx + massKg * (dy * dy + dz * dz),
    iyy: tensor.iyy + massKg * (dx * dx + dz * dz),
    izz: tensor.izz + massKg * (dx * dx + dy * dy),
    ixy: tensor.ixy - massKg * dx * dy,
    ixz: tensor.ixz - massKg * dx * dz,
    iyz: tensor.iyz - massKg * dy * dz,
  };
}

/**
 * Evaluate full CW-A04 DRC (CW-DRC-01 bus/ID/GPIO routing, CW-DRC-02 power rails,
 * CW-DRC-03 3D rotated/parallel-axis mass & inertia and unknown-aware BOM).
 */
export function evaluateAssemblyDrc(
  rawAssembly: RobotAssembly,
  catalog: DrcCatalog,
  options: DrcEvalOptions = {},
): DrcReport {
  const assembly = validateAssemblyStructure(rawAssembly);
  if (
    !catalog ||
    !Array.isArray(catalog.parts) ||
    catalog.parts.length < 1 ||
    catalog.parts.length > 256 ||
    !['verified_local_catalog', 'synthetic_fixture'].includes(catalog.provenance)
  ) {
    throw new Error('Invalid DRC catalog');
  }
  const partMap = new Map<string, DrcPart>();
  for (const part of catalog.parts) {
    if (partMap.has(part.partId)) throw new Error(`Duplicate catalog part_id: ${part.partId}`);
    partMap.set(part.partId, part);
  }
  const nodeMap = new Map<string, { node: RobotAssembly['nodes'][number]; index: number; part: DrcPart }>();
  assembly.nodes.forEach((node, index) => {
    const part = partMap.get(node.part_id);
    if (!part || part.version !== node.part_version || part.sha256 !== node.part_sha256) {
      throw new Error(`Assembly node ${node.node_id} part/version/sha256 pin mismatch`);
    }
    nodeMap.set(node.node_id, { node, index, part });
  });

  const findings: DrcFinding[] = [];
  let findingSeq = 0;
  const addFinding = (
    ruleId: DrcRuleId,
    category: DrcCategory,
    severity: 'blocked' | 'conflict',
    code: string,
    fieldRefs: string[],
    message: string,
    recommendation?: string,
  ) => {
    findings.push({
      id: `${ruleId.toLowerCase()}-${String(++findingSeq).padStart(3, '0')}`,
      ruleId,
      category,
      severity,
      code,
      fieldRefs: [...new Set(fieldRefs)],
      message,
      ...(recommendation ? { recommendation } : {}),
    });
  };

  // ============================================================================
  // CW-DRC-01: UART servo routing, I2C address/voltage/pull-up, and GPIO/pinout
  // ============================================================================
  const servoAddressesByNet: Record<string, Record<string, number>> = {};
  const maxServosPerBus = options.maxServosPerBus ?? 16;
  const usedPinsByNode = new Map<string, Map<string, string>>();
  const usedInterfaces = new Map<string, string>();
  const connectedActiveNodes = new Set<string>();
  const poweredNodes = new Set<string>();

  const checkNodePins = (
    nodeId: string,
    part: DrcPart,
    pins: string[],
    ownerRef: string,
  ) => {
    const reserved = new Set<string>(options.reservedPinsByPart?.[part.partId] ?? []);
    if (part.partId.startsWith('espressif.esp32-s3')) {
      ESP32_S3_RESERVED_PINS.forEach(pin => reserved.add(pin));
    }
    const nodePins = usedPinsByNode.get(nodeId) ?? new Map<string, string>();
    usedPinsByNode.set(nodeId, nodePins);
    for (const pin of pins) {
      const normalized = pin.toUpperCase();
      if (reserved.has(normalized) || reserved.has(pin)) {
        addFinding(
          'CW-DRC-01',
          'gpio_pinout',
          'conflict',
          'GPIO_RESERVED_PIN',
          [ownerRef, `part:${part.partId}#/electrical/bus_interfaces`],
          `Node '${nodeId}' (${part.partId}) uses reserved boot/USB/flash/PSRAM pin '${pin}'.`,
          'Assign reviewed general-purpose IO pins outside boot strapping, native USB (GPIO19/20), flash, and octal PSRAM ranges.',
        );
      }
      const prevOwner = nodePins.get(normalized);
      if (prevOwner && prevOwner !== ownerRef) {
        addFinding(
          'CW-DRC-01',
          'gpio_pinout',
          'conflict',
          'GPIO_PIN_CONFLICT',
          [prevOwner, ownerRef],
          `Pin '${pin}' on node '${nodeId}' is assigned to multiple interfaces or nets.`,
          'Allocate non-overlapping board pins per bus interface or use a reviewed multiplexer.',
        );
      } else {
        nodePins.set(normalized, ownerRef);
      }
    }
  };

  const netKindToBusKind: Record<RobotAssembly['electrical_nets'][number]['kind'], DrcBusInterface['kind']> = {
    TTL_UART_BUS: 'TTL_UART_BUS',
    I2C: 'I2C',
    PWM: 'PWM',
    power: 'POWER_RAIL',
    ground: 'POWER_RAIL',
  };

  assembly.electrical_nets.forEach((net, netIdx) => {
    const netRef = `/electrical_nets/${netIdx}`;
    const expectedBusKind = netKindToBusKind[net.kind];
    const resolvedEndpoints: {
      epIndex: number;
      epRef: string;
      nodeId: string;
      part: DrcPart;
      bus: DrcBusInterface;
      pins: string[];
    }[] = [];

    net.endpoints.forEach((ep, epIdx) => {
      const epRef = `${netRef}/endpoints/${epIdx}`;
      const entry = nodeMap.get(ep.node_id);
      if (!entry) return;
      const bus = entry.part.electrical.busInterfaces.find(b => b.interface_id === ep.interface_id);
      if (!bus) {
        addFinding(
          'CW-DRC-01',
          'gpio_pinout',
          'conflict',
          'INTERFACE_NOT_FOUND',
          [epRef],
          `Node '${ep.node_id}' does not expose electrical interface '${ep.interface_id}'.`,
        );
        return;
      }
      if (bus.kind !== expectedBusKind) {
        addFinding(
          'CW-DRC-01',
          'gpio_pinout',
          'conflict',
          'NET_INTERFACE_KIND_MISMATCH',
          [epRef, `${netRef}/kind`],
          `Net '${net.net_id}' (${net.kind}) is incompatible with interface '${ep.node_id}:${ep.interface_id}' (${bus.kind}).`,
        );
      }
      const pins = ep.pins && ep.pins.length > 0 ? ep.pins : bus.pins;
      if (pins.length === 0) {
        addFinding(
          'CW-DRC-01',
          'gpio_pinout',
          'blocked',
          'GPIO_PINS_UNASSIGNED',
          [epRef, `part:${entry.part.partId}#/electrical/bus_interfaces`],
          `Endpoint '${ep.node_id}:${ep.interface_id}' on net '${net.net_id}' has no reviewed pin assignments.`,
          'Freeze board/connector pin numbers in CW-D01 before claiming physical routing readiness.',
        );
      } else if (net.kind !== 'power' && net.kind !== 'ground') {
        checkNodePins(ep.node_id, entry.part, pins, epRef);
      }
      const ifaceKey = `${ep.node_id}:${ep.interface_id}`;
      if (net.kind !== 'power' && net.kind !== 'ground') {
        const previousNet = usedInterfaces.get(ifaceKey);
        if (previousNet && previousNet !== net.net_id) {
          addFinding(
            'CW-DRC-01',
            'gpio_pinout',
            'conflict',
            'INTERFACE_REUSED_ACROSS_NETS',
            [epRef],
            `Signal interface '${ifaceKey}' is bound to both '${previousNet}' and '${net.net_id}'.`,
          );
        }
        usedInterfaces.set(ifaceKey, net.net_id);
        connectedActiveNodes.add(ep.node_id);
      } else {
        poweredNodes.add(ep.node_id);
      }
      resolvedEndpoints.push({ epIndex: epIdx, epRef, nodeId: ep.node_id, part: entry.part, bus, pins });
    });

    if (net.kind === 'TTL_UART_BUS') {
      const controllers = resolvedEndpoints.filter(e => e.bus.role === 'controller');
      const peripherals = resolvedEndpoints.filter(e => e.bus.role === 'peripheral');
      if (controllers.length !== 1 || peripherals.length === 0) {
        addFinding(
          'CW-DRC-01',
          'uart_routing',
          'conflict',
          'UART_CONTROLLER_TOPOLOGY',
          [netRef],
          `TTL UART bus '${net.net_id}' requires exactly 1 controller and at least 1 peripheral (found ${controllers.length} controllers, ${peripherals.length} peripherals).`,
        );
      }
      if (peripherals.length > maxServosPerBus) {
        addFinding(
          'CW-DRC-01',
          'uart_routing',
          'conflict',
          'UART_BUS_CAPACITY_EXCEEDED',
          [netRef],
          `TTL UART bus '${net.net_id}' attaches ${peripherals.length} servos, exceeding reviewed controller capacity (${maxServosPerBus}).`,
        );
      }
      const protocols = new Set(resolvedEndpoints.map(e => e.bus.protocol).filter((p): p is string => Boolean(p)));
      if (protocols.size > 1) {
        addFinding(
          'CW-DRC-01',
          'uart_routing',
          'conflict',
          'UART_PROTOCOL_MISMATCH',
          resolvedEndpoints.map(e => e.epRef),
          `TTL UART bus '${net.net_id}' mixes incompatible servo/bus protocols: ${[...protocols].sort(lex).join(', ')}.`,
          'Group Feetech TTL and Dynamixel or RS-485 actuators onto separate compatible bus drivers.',
        );
      } else if (resolvedEndpoints.some(e => !e.bus.protocol)) {
        addFinding(
          'CW-DRC-01',
          'uart_routing',
          'blocked',
          'UART_PROTOCOL_UNKNOWN',
          resolvedEndpoints.filter(e => !e.bus.protocol).map(e => e.epRef),
          `TTL UART bus '${net.net_id}' has endpoints with unspecified bus protocol (null).`,
          'Specify the exact half-duplex protocol (e.g. feetech_sts_ttl) in the reviewed component revision.',
        );
      }

      // Logic voltage window check
      const knownLogic = resolvedEndpoints.filter(
        e => e.bus.logic_min_v !== null && e.bus.logic_max_v !== null,
      );
      if (knownLogic.length < resolvedEndpoints.length) {
        addFinding(
          'CW-DRC-01',
          'uart_routing',
          'blocked',
          'UART_LOGIC_VOLTAGE_UNKNOWN',
          resolvedEndpoints.filter(e => e.bus.logic_min_v === null || e.bus.logic_max_v === null).map(e => e.epRef),
          `TTL UART bus '${net.net_id}' has endpoints with unknown logic voltage bounds.`,
          'Verify UART transceiver/buffer logic levels (e.g. 3.3 V MCU vs 5 V TTL servo bus) in CW-D01.',
        );
      } else if (knownLogic.length > 0) {
        const low = Math.max(...knownLogic.map(e => e.bus.logic_min_v!));
        const high = Math.min(...knownLogic.map(e => e.bus.logic_max_v!));
        if (low > high) {
          addFinding(
            'CW-DRC-01',
            'uart_routing',
            'conflict',
            'UART_LOGIC_VOLTAGE_MISMATCH',
            knownLogic.map(e => e.epRef),
            `TTL UART bus '${net.net_id}' endpoints have disjoint logic voltage windows (max min_v ${low} V > min max_v ${high} V).`,
            'Add a reviewed half-duplex level-shifting buffer circuit between controller and servo bus.',
          );
        }
      }

      // Deterministic unique Servo ID assignment & verification within reviewed protocol range
      const proto = protocols.size === 1 ? [...protocols][0] : 'default';
      const [minId, maxId] = options.servoIdRangeByProtocol?.[proto] ?? [1, 253];
      const assignedOnNet: Record<string, number> = {};
      const seenIds = new Map<number, string>();
      const sortedPeripherals = [...peripherals].sort(
        (a, b) => lex(a.nodeId, b.nodeId) || lex(a.bus.interface_id, b.bus.interface_id),
      );
      let nextAutoId = minId;
      for (const p of sortedPeripherals) {
        const keySpecific = `${p.nodeId}:${p.bus.interface_id}`;
        const explicitId = options.servoIds?.[keySpecific] ?? options.servoIds?.[p.nodeId];
        let id: number;
        if (explicitId !== undefined) {
          id = explicitId;
        } else {
          while (seenIds.has(nextAutoId)) nextAutoId++;
          id = nextAutoId++;
        }
        if (!Number.isSafeInteger(id) || id < minId || id > maxId) {
          addFinding(
            'CW-DRC-01',
            'uart_routing',
            'conflict',
            'UART_ID_OUT_OF_RANGE',
            [p.epRef],
            `Servo endpoint '${keySpecific}' on '${net.net_id}' has ID ${id} outside reviewed range [${minId}, ${maxId}].`,
          );
        } else if (seenIds.has(id)) {
          addFinding(
            'CW-DRC-01',
            'uart_routing',
            'conflict',
            'UART_DUPLICATE_SERVO_ID',
            [seenIds.get(id)!, p.epRef],
            `Duplicate servo ID ${id} on TTL UART bus '${net.net_id}' between '${seenIds.get(id)}' and '${p.nodeId}'.`,
            'Assign unique servo IDs per bus segment before energizing the bus.',
          );
        } else {
          seenIds.set(id, p.epRef);
          assignedOnNet[p.nodeId] = id;
        }
      }
      servoAddressesByNet[net.net_id] = assignedOnNet;
    }

    if (net.kind === 'I2C') {
      const controllers = resolvedEndpoints.filter(e => e.bus.role === 'controller');
      const peripherals = resolvedEndpoints.filter(e => e.bus.role === 'peripheral');
      if (controllers.length !== 1 || peripherals.length === 0) {
        addFinding(
          'CW-DRC-01',
          'i2c_routing',
          'conflict',
          'I2C_CONTROLLER_TOPOLOGY',
          [netRef],
          `I2C bus '${net.net_id}' requires 1 controller and at least 1 peripheral.`,
        );
      }
      const seenAddr = new Map<number, string>();
      const hasMux = Boolean(options.i2cMuxByNet?.[net.net_id]);
      for (const p of peripherals) {
        const addr = p.bus.i2c_address;
        if (addr === null || addr === undefined) {
          addFinding(
            'CW-DRC-01',
            'i2c_routing',
            'blocked',
            'I2C_ADDRESS_UNKNOWN',
            [p.epRef, `part:${p.part.partId}#/electrical/bus_interfaces`],
            `I2C peripheral '${p.nodeId}:${p.bus.interface_id}' on '${net.net_id}' has no declared 7-bit I2C address.`,
          );
        } else if (addr < 8 || addr > 119) {
          addFinding(
            'CW-DRC-01',
            'i2c_routing',
            'conflict',
            'I2C_ADDRESS_RESERVED',
            [p.epRef],
            `I2C peripheral '${p.nodeId}' uses reserved 7-bit address 0x${addr.toString(16)} (${addr}).`,
          );
        } else if (seenAddr.has(addr) && !hasMux) {
          addFinding(
            'CW-DRC-01',
            'i2c_routing',
            'conflict',
            'I2C_ADDRESS_COLLISION',
            [seenAddr.get(addr)!, p.epRef],
            `I2C address collision at 0x${addr.toString(16).toUpperCase()} (${addr}) on bus '${net.net_id}' without a reviewed I2C multiplexer.`,
            'Select an alternate jumper address or insert a reviewed I2C mux.',
          );
        } else {
          seenAddr.set(addr, p.epRef);
        }
      }
      const knownLogic = resolvedEndpoints.filter(
        e => e.bus.logic_min_v !== null && e.bus.logic_max_v !== null,
      );
      if (knownLogic.length < resolvedEndpoints.length) {
        addFinding(
          'CW-DRC-01',
          'i2c_routing',
          'blocked',
          'I2C_LOGIC_VOLTAGE_UNKNOWN',
          resolvedEndpoints.filter(e => e.bus.logic_min_v === null || e.bus.logic_max_v === null).map(e => e.epRef),
          `I2C bus '${net.net_id}' has endpoints with unknown logic voltage bounds.`,
        );
      } else {
        const low = Math.max(...knownLogic.map(e => e.bus.logic_min_v!));
        const high = Math.min(...knownLogic.map(e => e.bus.logic_max_v!));
        const pullUpV = options.i2cPullUpVoltageByNet?.[net.net_id] ?? net.nominal_voltage_v ?? null;
        if (low > high) {
          addFinding(
            'CW-DRC-01',
            'i2c_routing',
            'conflict',
            'I2C_VOLTAGE_MISMATCH',
            knownLogic.map(e => e.epRef),
            `I2C bus '${net.net_id}' endpoints have incompatible logic voltage windows ([${low} V, ${high} V]).`,
          );
        } else if (pullUpV === null) {
          addFinding(
            'CW-DRC-01',
            'i2c_routing',
            'blocked',
            'I2C_PULLUP_UNKNOWN',
            [netRef],
            `I2C bus '${net.net_id}' has no reviewed pull-up voltage specified.`,
            'Specify I2C pull-up resistance and logic rail voltage in CW-D01.',
          );
        } else if (pullUpV < low || pullUpV > high) {
          addFinding(
            'CW-DRC-01',
            'i2c_routing',
            'conflict',
            'I2C_PULLUP_MISMATCH',
            [netRef, ...knownLogic.map(e => e.epRef)],
            `I2C pull-up voltage ${pullUpV} V on '${net.net_id}' falls outside endpoint logic window [${low} V, ${high} V].`,
          );
        }
      }
    }
  });

  // Generate deterministic routing proposals for declared & unconnected bus interfaces
  const routingProposals: RoutingProposal[] = [];
  const controllersByKind = new Map<
    'TTL_UART_BUS' | 'I2C' | 'PWM',
    { nodeId: string; part: DrcPart; bus: DrcBusInterface }[]
  >();
  const unconnectedPeripherals: {
    nodeId: string;
    nodeIndex: number;
    part: DrcPart;
    bus: DrcBusInterface;
  }[] = [];

  assembly.nodes.forEach((node, idx) => {
    const entry = nodeMap.get(node.node_id)!;
    for (const bus of entry.part.electrical.busInterfaces) {
      if (bus.kind === 'TTL_UART_BUS' || bus.kind === 'I2C' || bus.kind === 'PWM') {
        if (bus.role === 'controller') {
          const list = controllersByKind.get(bus.kind) ?? [];
          list.push({ nodeId: node.node_id, part: entry.part, bus });
          controllersByKind.set(bus.kind, list);
        } else if (bus.role === 'peripheral') {
          const ifaceKey = `${node.node_id}:${bus.interface_id}`;
          if (!usedInterfaces.has(ifaceKey)) {
            unconnectedPeripherals.push({ nodeId: node.node_id, nodeIndex: idx, part: entry.part, bus });
          }
        }
      }
    }
  });

  // Record existing signal nets as routing proposals first
  assembly.electrical_nets.forEach(net => {
    if (net.kind !== 'TTL_UART_BUS' && net.kind !== 'I2C' && net.kind !== 'PWM') return;
    const resolved = net.endpoints
      .map(ep => {
        const entry = nodeMap.get(ep.node_id);
        const bus = entry?.part.electrical.busInterfaces.find(b => b.interface_id === ep.interface_id);
        return entry && bus ? { nodeId: ep.node_id, part: entry.part, bus } : null;
      })
      .filter((x): x is NonNullable<typeof x> => x !== null);
    const controller = resolved.find(r => r.bus.role === 'controller');
    const peripherals = resolved.filter(r => r.bus.role === 'peripheral');
    if (!controller) return;
    const allKnownV = resolved.every(r => r.bus.logic_min_v !== null && r.bus.logic_max_v !== null);
    const low = allKnownV ? Math.max(...resolved.map(r => r.bus.logic_min_v!)) : null;
    const high = allKnownV ? Math.min(...resolved.map(r => r.bus.logic_max_v!)) : null;
    const windowV: [number, number] | null = low !== null && high !== null && low <= high ? [low, high] : null;
    const netConflict = findings.some(f => f.severity === 'conflict' && f.fieldRefs.some(ref => ref.startsWith(`/electrical_nets/`)));
    const netBlocked = findings.some(f => f.severity === 'blocked' && f.fieldRefs.some(ref => ref.startsWith(`/electrical_nets/`)));
    routingProposals.push({
      proposalId: `proposal_${net.net_id}`,
      netId: net.net_id,
      kind: net.kind,
      protocol: controller.bus.protocol,
      controllerNodeId: controller.nodeId,
      controllerInterfaceId: controller.bus.interface_id,
      peripheralEndpoints: peripherals.map(p => ({
        nodeId: p.nodeId,
        interfaceId: p.bus.interface_id,
        assignedDeviceId: servoAddressesByNet[net.net_id]?.[p.nodeId] ?? null,
        i2cAddress: p.bus.i2c_address,
      })),
      logicVoltageWindowV: windowV,
      status: netConflict ? 'conflict' : netBlocked ? 'blocked' : 'compatible',
      reason: netConflict
        ? 'Active net has protocol, address, voltage, or pin conflicts.'
        : netBlocked
          ? 'Active net structurally valid; protocol, logic voltage, or pin qualification remains open.'
          : 'Reviewed compatible bus routing.',
    });
  });

  // Propose deterministic groupings for any unconnected peripherals
  for (const p of unconnectedPeripherals.sort((a, b) => lex(a.nodeId, b.nodeId) || lex(a.bus.interface_id, b.bus.interface_id))) {
    addFinding(
      'CW-DRC-01',
      p.bus.kind === 'I2C' ? 'i2c_routing' : 'uart_routing',
      'blocked',
      'SIGNAL_INTERFACE_UNCONNECTED',
      [`/nodes/${p.nodeIndex}/node_id`, `part:${p.part.partId}#/electrical/bus_interfaces`],
      `Peripheral interface '${p.nodeId}:${p.bus.interface_id}' (${p.bus.kind}) is not connected to any electrical net.`,
      'Connect the peripheral to a compatible controller bus in electrical_nets.',
    );
    const candidates = (controllersByKind.get(p.bus.kind as 'TTL_UART_BUS' | 'I2C' | 'PWM') ?? []).filter(
      c => !c.bus.protocol || !p.bus.protocol || c.bus.protocol === p.bus.protocol,
    );
    if (candidates.length > 0) {
      const chosen = candidates.sort((a, b) => lex(a.nodeId, b.nodeId))[0];
      routingProposals.push({
        proposalId: `proposal_${chosen.nodeId}_${p.nodeId}_${p.bus.interface_id}`,
        netId: null,
        kind: p.bus.kind as 'TTL_UART_BUS' | 'I2C' | 'PWM',
        protocol: chosen.bus.protocol ?? p.bus.protocol,
        controllerNodeId: chosen.nodeId,
        controllerInterfaceId: chosen.bus.interface_id,
        peripheralEndpoints: [
          {
            nodeId: p.nodeId,
            interfaceId: p.bus.interface_id,
            assignedDeviceId: p.bus.kind === 'TTL_UART_BUS' ? 1 : null,
            i2cAddress: p.bus.i2c_address,
          },
        ],
        logicVoltageWindowV:
          chosen.bus.logic_min_v !== null &&
          chosen.bus.logic_max_v !== null &&
          p.bus.logic_min_v !== null &&
          p.bus.logic_max_v !== null
            ? [Math.max(chosen.bus.logic_min_v, p.bus.logic_min_v), Math.min(chosen.bus.logic_max_v, p.bus.logic_max_v)]
            : null,
        status: 'blocked',
        reason: `Unconnected peripheral; candidate controller '${chosen.nodeId}:${chosen.bus.interface_id}' requires net binding and reviewed ratings.`,
      });
    }
  }

  // ============================================================================
  // CW-DRC-02: Power rails, conversion efficiency, derating, brownout & wiring
  // ============================================================================
  const brownoutMarginTargetV = options.brownoutMarginV ?? 0.3;
  const becDeratingFactor = options.becDeratingFactor ?? 0.8;
  const becEfficiency = options.becEfficiency ?? 0.85;
  const distributionSet = new Set(options.distributionNodeIds ?? []);

  if (options.claimedLoadAssertions?.mcuCountedTimes && options.claimedLoadAssertions.mcuCountedTimes > 1) {
    addFinding(
      'CW-DRC-02',
      'power_rail',
      'conflict',
      'POWER_MCU_DOUBLE_COUNTED',
      ['/electrical_nets'],
      `MCU consumption was counted ${options.claimedLoadAssertions.mcuCountedTimes} times across buses; MCU load must be included once on its supply rail.`,
    );
  }
  if (options.claimedLoadAssertions?.summedUnlikeVoltageCurrents) {
    addFinding(
      'CW-DRC-02',
      'power_rail',
      'conflict',
      'POWER_SUMMED_UNLIKE_VOLTAGES',
      ['/electrical_nets'],
      'Currents (mA) at unlike rail voltages were summed directly without voltage/efficiency power conversion.',
      'Convert regulated rail power P_out = V_out * I_out / efficiency before reflecting current to an upstream rail.',
    );
  }

  // Check active nodes for unknown electrical ratings or missing power nets
  assembly.nodes.forEach((node, idx) => {
    const { part } = nodeMap.get(node.node_id)!;
    const nodeRef = `/nodes/${idx}`;
    if (part.electrical.ratingBasis === 'unknown') {
      addFinding(
        'CW-DRC-02',
        'power_rail',
        'blocked',
        'POWER_UNKNOWN_RATING',
        [nodeRef, `part:${part.partId}#/electrical/rating_basis`],
        `Node '${node.node_id}' (${part.partId}) has rating_basis='unknown'; missing electrical ratings block physical readiness and never count as zero load.`,
        'Complete CW-D01 datasheet/harness qualification for voltage and current ratings.',
      );
    }
    const isActiveConsumer =
      part.category === 'mcu' || part.category === 'actuator' || part.category === 'sensor';
    if (isActiveConsumer && !poweredNodes.has(node.node_id)) {
      addFinding(
        'CW-DRC-02',
        'power_rail',
        'blocked',
        'POWER_RAIL_UNCONNECTED',
        [nodeRef],
        `Active component '${node.node_id}' (${part.partId}) is not connected to a reviewed power rail net.`,
        'Add power/ground rail nets with reviewed source/BEC capacity and fuse ratings.',
      );
    }
  });

  const powerRails: PowerRailSummary[] = [];
  const powerNets = assembly.electrical_nets
    .map((net, idx) => ({ net, idx }))
    .filter(item => item.net.kind === 'power' || item.net.kind === 'ground');

  // Track downstream regulated power rails fed by a BEC/regulator so upstream battery rails reflect converted watts
  const regulatorDownstreamPeakWatts = new Map<string, { watts: number; vOut: number }>();
  const regulatorDownstreamContWatts = new Map<string, { watts: number; vOut: number }>();

  // First pass: evaluate regulated / downstream rails
  for (const { net, idx } of powerNets) {
    if (net.kind !== 'power') continue;
    const netRef = `/electrical_nets/${idx}`;
    const sources: { nodeId: string; part: DrcPart; bus: DrcBusInterface }[] = [];
    const sinks: { nodeId: string; part: DrcPart; bus: DrcBusInterface }[] = [];
    for (const ep of net.endpoints) {
      const entry = nodeMap.get(ep.node_id);
      const bus = entry?.part.electrical.busInterfaces.find(b => b.interface_id === ep.interface_id);
      if (!entry || !bus) continue;
      if (bus.role === 'source') sources.push({ nodeId: ep.node_id, part: entry.part, bus });
      else if (bus.role === 'sink') sinks.push({ nodeId: ep.node_id, part: entry.part, bus });
    }
    const regulators = sources.filter(s =>
      s.part.electrical.busInterfaces.some(b => b.kind === 'POWER_RAIL' && b.role === 'sink'),
    );
    if (regulators.length > 0 && net.nominal_voltage_v) {
      const uniqueSinks = new Map(sinks.map(s => [s.nodeId, s]));
      let contMa = 0, peakMa = 0, known = true;
      for (const s of uniqueSinks.values()) {
        if (s.part.electrical.continuousMa === null || s.part.electrical.peakMa === null) {
          known = false;
        } else {
          contMa += s.part.electrical.continuousMa;
          peakMa += s.part.electrical.peakMa;
        }
      }
      if (known) {
        for (const reg of regulators) {
          regulatorDownstreamPeakWatts.set(reg.nodeId, {
            watts: (net.nominal_voltage_v * (peakMa / 1000)) / becEfficiency,
            vOut: net.nominal_voltage_v,
          });
          regulatorDownstreamContWatts.set(reg.nodeId, {
            watts: (net.nominal_voltage_v * (contMa / 1000)) / becEfficiency,
            vOut: net.nominal_voltage_v,
          });
        }
      }
    }
    void netRef;
  }

  // Second pass: full rail evaluation
  for (const { net, idx } of powerNets) {
    const netRef = `/electrical_nets/${idx}`;
    const sources: { nodeId: string; part: DrcPart; bus: DrcBusInterface; epRef: string }[] = [];
    const sinks: { nodeId: string; part: DrcPart; bus: DrcBusInterface; epRef: string }[] = [];
    const distNodes: string[] = [];

    net.endpoints.forEach((ep, epIdx) => {
      const epRef = `${netRef}/endpoints/${epIdx}`;
      const entry = nodeMap.get(ep.node_id);
      if (!entry) return;
      if (distributionSet.has(ep.node_id)) distNodes.push(ep.node_id);
      const bus = entry.part.electrical.busInterfaces.find(b => b.interface_id === ep.interface_id);
      if (!bus) return;
      if (bus.role === 'source') sources.push({ nodeId: ep.node_id, part: entry.part, bus, epRef });
      if (bus.role === 'sink') sinks.push({ nodeId: ep.node_id, part: entry.part, bus, epRef });
    });

    if (net.kind === 'ground') {
      powerRails.push({
        netId: net.net_id,
        kind: 'ground',
        nominalVoltageV: 0,
        sourceNodeIds: sources.map(s => s.nodeId),
        regulatorNodeIds: [],
        distributionNodeIds: distNodes,
        sinkNodeIds: sinks.map(s => s.nodeId),
        continuousLoadMa: 0,
        peakLoadMa: 0,
        deratedCapacityMa: null,
        reflectedUpstreamPeakMa: null,
        wireLimitMa: options.wireLimitMaByNet?.[net.net_id] ?? null,
        fuseLimitMa: options.fuseLimitMaByNet?.[net.net_id] ?? null,
        brownoutMarginV: null,
        status: 'pass',
      });
      continue;
    }

    let railStatus: DrcDisposition = 'pass';
    const markStatus = (s: 'blocked' | 'conflict') => {
      if (s === 'conflict') railStatus = 'conflict';
      else if (railStatus === 'pass') railStatus = 'blocked';
    };

    const realSources = sources.filter(s => !distributionSet.has(s.nodeId));
    if (realSources.length === 0) {
      markStatus(distNodes.length > 0 ? 'conflict' : 'blocked');
      addFinding(
        'CW-DRC-02',
        'power_rail',
        distNodes.length > 0 ? 'conflict' : 'blocked',
        distNodes.length > 0 ? 'POWER_DISTRIBUTION_NOT_SOURCE' : 'POWER_SOURCE_MISSING',
        [netRef],
        distNodes.length > 0
          ? `Power rail '${net.net_id}' relies on distribution node(s) (${distNodes.join(', ')}) without a qualified battery or BEC source.`
          : `Power rail '${net.net_id}' has no power source endpoint.`,
        'A distribution board improves routing/fusing but does not generate power; connect a higher-rated battery or BEC source.',
      );
    }

    const regulators = realSources.filter(s =>
      s.part.electrical.busInterfaces.some(b => b.kind === 'POWER_RAIL' && b.role === 'sink'),
    );

    // Count each sink node ONCE on this rail (prevent MCU or multi-pin double-counting)
    const uniqueSinks = new Map<string, (typeof sinks)[number]>();
    for (const s of sinks) {
      if (!uniqueSinks.has(s.nodeId)) uniqueSinks.set(s.nodeId, s);
    }

    const nominalV = net.nominal_voltage_v ?? null;
    if (nominalV === null) {
      markStatus('blocked');
      addFinding(
        'CW-DRC-02',
        'power_rail',
        'blocked',
        'POWER_NOMINAL_VOLTAGE_UNKNOWN',
        [`${netRef}/nominal_voltage_v`],
        `Power rail '${net.net_id}' has null nominal_voltage_v.`,
      );
    }

    let contLoadMa: number | null = 0;
    let peakLoadMa: number | null = 0;
    let reflectedUpstreamPeakMa: number | null = null;
    let minBrownoutMarginV: number | null = null;
    const lineDropV = options.lineDropVByNet?.[net.net_id] ?? 0;

    for (const sink of uniqueSinks.values()) {
      const el = sink.part.electrical;
      // If sink is itself a regulator feeding a downstream rail at a different voltage,
      // reflect its downstream watts into this upstream rail rather than summing mA across unlike voltages!
      const downstreamPeak = regulatorDownstreamPeakWatts.get(sink.nodeId);
      const downstreamCont = regulatorDownstreamContWatts.get(sink.nodeId);
      if (downstreamPeak && downstreamCont && nominalV !== null) {
        if (downstreamPeak.vOut !== nominalV && el.peakMa !== null && el.peakMa > 0) {
          addFinding(
            'CW-DRC-02',
            'power_rail',
            'conflict',
            'POWER_SUMMED_UNLIKE_VOLTAGES',
            [sink.epRef],
            `Regulator '${sink.nodeId}' converts ${nominalV} V to ${downstreamPeak.vOut} V; raw output mA cannot be summed directly onto the ${nominalV} V rail.`,
            'Use efficiency-adjusted power conversion I_in = (V_out * I_out) / (eta * V_in).',
          );
          markStatus('conflict');
        }
        const upstreamMinV = Math.max(0.1, (el.minV ?? nominalV) - lineDropV);
        const reflectedPeak = (downstreamPeak.watts / upstreamMinV) * 1000;
        const reflectedCont = (downstreamCont.watts / upstreamMinV) * 1000;
        reflectedUpstreamPeakMa = (reflectedUpstreamPeakMa ?? 0) + reflectedPeak;
        if (contLoadMa !== null) contLoadMa += reflectedCont;
        if (peakLoadMa !== null) peakLoadMa += reflectedPeak;
      } else if (el.ratingBasis === 'unknown' || el.continuousMa === null || el.peakMa === null) {
        contLoadMa = null;
        peakLoadMa = null;
        markStatus('blocked');
        addFinding(
          'CW-DRC-02',
          'power_rail',
          'blocked',
          'POWER_SINK_LOAD_UNKNOWN',
          [sink.epRef, `part:${sink.part.partId}#/electrical`],
          `Sink '${sink.nodeId}' on rail '${net.net_id}' has unknown continuous/peak current ratings.`,
        );
      } else {
        if (contLoadMa !== null) contLoadMa += el.continuousMa;
        if (peakLoadMa !== null) peakLoadMa += el.peakMa;
      }

      if (nominalV !== null && el.minV !== null && el.maxV !== null) {
        const effectiveV = nominalV - lineDropV;
        if (nominalV > el.maxV || effectiveV < el.minV) {
          markStatus('conflict');
          addFinding(
            'CW-DRC-02',
            'power_rail',
            'conflict',
            'POWER_VOLTAGE_MISMATCH',
            [sink.epRef, `${netRef}/nominal_voltage_v`],
            `Rail '${net.net_id}' (${nominalV} V nominal, ${effectiveV.toFixed(2)} V under drop) violates '${sink.nodeId}' operating window [${el.minV} V, ${el.maxV} V].`,
          );
        } else {
          const margin = effectiveV - el.minV;
          minBrownoutMarginV = minBrownoutMarginV === null ? margin : Math.min(minBrownoutMarginV, margin);
          if (margin + 1e-9 < brownoutMarginTargetV) {
            markStatus('conflict');
            addFinding(
              'CW-DRC-02',
              'power_rail',
              'conflict',
              'POWER_BROWNOUT_MARGIN',
              [sink.epRef, `${netRef}/nominal_voltage_v`],
              `Rail '${net.net_id}' has insufficient brownout margin (${margin.toFixed(2)} V < ${brownoutMarginTargetV.toFixed(2)} V required) at sink '${sink.nodeId}'.`,
              'Increase regulated rail setpoint within device limits, reduce harness drop, or separate high-stall servo loads from the MCU rail.',
            );
          }
        }
      }
    }

    let deratedCapacityMa: number | null = null;
    for (const src of realSources) {
      const cap = src.part.electrical.outputCapacityMa;
      if (cap === null || src.part.electrical.ratingBasis === 'unknown') {
        deratedCapacityMa = null;
        markStatus('blocked');
        addFinding(
          'CW-DRC-02',
          'power_rail',
          'blocked',
          'POWER_SOURCE_CAPACITY_UNKNOWN',
          [src.epRef, `part:${src.part.partId}#/electrical/output_capacity_ma`],
          `Source '${src.nodeId}' on rail '${net.net_id}' has unknown output_capacity_ma.`,
        );
      } else {
        const factor = regulators.some(r => r.nodeId === src.nodeId) ? becDeratingFactor : 1.0;
        deratedCapacityMa = (deratedCapacityMa ?? 0) + cap * factor;
      }
    }

    if (peakLoadMa !== null && deratedCapacityMa !== null && peakLoadMa > deratedCapacityMa) {
      markStatus('conflict');
      const isBec = regulators.length > 0;
      addFinding(
        'CW-DRC-02',
        'power_rail',
        'conflict',
        isBec ? 'POWER_OVERLOAD_BEC' : 'POWER_OVERLOAD_SOURCE',
        [netRef, ...realSources.map(s => s.epRef)],
        `Peak load ${peakLoadMa.toFixed(0)} mA on rail '${net.net_id}' exceeds derated ${isBec ? 'BEC' : 'source'} capacity ${deratedCapacityMa.toFixed(0)} mA.`,
        distNodes.length > 0 || distributionSet.size > 0
          ? 'A distribution board does not increase source/BEC capacity; select a higher-rated BEC/battery or reduce simultaneous stall load.'
          : 'Select a higher-rated regulator/source or reduce simultaneous actuator stall load.',
      );
    }

    const wireLimitMa = options.wireLimitMaByNet?.[net.net_id] ?? null;
    const fuseLimitMa = options.fuseLimitMaByNet?.[net.net_id] ?? null;
    if (peakLoadMa !== null && wireLimitMa !== null && peakLoadMa > wireLimitMa) {
      markStatus('conflict');
      addFinding(
        'CW-DRC-02',
        'power_rail',
        'conflict',
        'POWER_OVERLOAD_WIRE_FUSE',
        [netRef],
        `Peak load ${peakLoadMa.toFixed(0)} mA on rail '${net.net_id}' exceeds harness wire rating (${wireLimitMa} mA).`,
        'Upgrade harness wire gauge or split loads across separately fused branches.',
      );
    }
    if (peakLoadMa !== null && fuseLimitMa !== null && peakLoadMa > fuseLimitMa) {
      markStatus('conflict');
      addFinding(
        'CW-DRC-02',
        'power_rail',
        'conflict',
        'POWER_OVERLOAD_WIRE_FUSE',
        [netRef],
        `Peak load ${peakLoadMa.toFixed(0)} mA on rail '${net.net_id}' exceeds fuse rating (${fuseLimitMa} mA).`,
      );
    }

    powerRails.push({
      netId: net.net_id,
      kind: 'power',
      nominalVoltageV: nominalV,
      sourceNodeIds: realSources.map(s => s.nodeId),
      regulatorNodeIds: regulators.map(r => r.nodeId),
      distributionNodeIds: distNodes,
      sinkNodeIds: [...uniqueSinks.keys()],
      continuousLoadMa: contLoadMa,
      peakLoadMa,
      deratedCapacityMa,
      reflectedUpstreamPeakMa,
      wireLimitMa,
      fuseLimitMa,
      brownoutMarginV: minBrownoutMarginV,
      status: railStatus,
    });
  }

  // ============================================================================
  // CW-DRC-03: 3D Rotated/Parallel-Axis Mass & Inertia + Unknown-Aware BOM
  // ============================================================================
  const worldPoses = computeWorldTransforms(assembly);
  let totalMassKg = 0;
  const weightedCom: [number, number, number] = [0, 0, 0];
  const nodeComWorldM: Record<string, [number, number, number]> = {};
  let allPartsDrawingReviewed = true;

  assembly.nodes.forEach((node, idx) => {
    const { part } = nodeMap.get(node.node_id)!;
    const nodeRef = `/nodes/${idx}`;
    const m = part.mechanical.massKg;
    if (typeof m !== 'number' || !Number.isFinite(m) || m <= 0 || m > 100) {
      addFinding(
        'CW-DRC-03',
        'mechanics_mass',
        'conflict',
        'MASS_INVALID',
        [nodeRef, `part:${part.partId}#/mechanical/mass_kg`],
        `Node '${node.node_id}' (${part.partId}) has invalid mass_kg (${m}).`,
      );
    }
    const comLocal = part.mechanical.centerOfMassM;
    const size = part.mechanical.sizeM;
    if (
      comLocal.some(v => !Number.isFinite(v)) ||
      comLocal.some((v, axis) => Math.abs(v) > size[axis] * 2)
    ) {
      addFinding(
        'CW-DRC-03',
        'mechanics_mass',
        'conflict',
        'MASS_COM_ORIGIN_OR_UNITS_INVALID',
        [nodeRef, `part:${part.partId}#/mechanical/center_of_mass_m`],
        `Node '${node.node_id}' (${part.partId}) center_of_mass_m [${comLocal.join(', ')}] lies outside plausible part-frame meter bounds (possible mm vs m unit or wrong origin error).`,
      );
    }
    const inertiaCheck = isValidInertiaTensor(part.mechanical.inertiaKgM2);
    if (!inertiaCheck.valid) {
      addFinding(
        'CW-DRC-03',
        'mechanics_mass',
        'conflict',
        'MASS_INERTIA_INVALID',
        [nodeRef, `part:${part.partId}#/mechanical/inertia_kg_m2`],
        `Node '${node.node_id}' (${part.partId}) inertia tensor is invalid: ${inertiaCheck.reason}.`,
      );
    }
    if (
      part.mechanical.basis !== 'drawing_reviewed' ||
      part.mechanical.snapPorts.some(p => p.qualification !== 'drawing_reviewed')
    ) {
      allPartsDrawingReviewed = false;
    }

    const pose = worldPoses[node.node_id];
    const R = quaternionToMatrix3(pose.quaternion_wxyz);
    const rotatedCom = matVec3(R, comLocal);
    const comWorld: [number, number, number] = [
      pose.position_m[0] + rotatedCom[0],
      pose.position_m[1] + rotatedCom[1],
      pose.position_m[2] + rotatedCom[2],
    ];
    nodeComWorldM[node.node_id] = comWorld;
    if (m > 0 && Number.isFinite(m)) {
      totalMassKg += m;
      weightedCom[0] += m * comWorld[0];
      weightedCom[1] += m * comWorld[1];
      weightedCom[2] += m * comWorld[2];
    }
  });

  const centerOfMassWorldM: [number, number, number] =
    totalMassKg > 0
      ? [weightedCom[0] / totalMassKg, weightedCom[1] / totalMassKg, weightedCom[2] / totalMassKg]
      : [0, 0, 0];

  const totalInertia: DrcInertiaTensor = { ixx: 0, iyy: 0, izz: 0, ixy: 0, ixz: 0, iyz: 0 };
  for (const node of assembly.nodes) {
    const { part } = nodeMap.get(node.node_id)!;
    const pose = worldPoses[node.node_id];
    const rotated = rotateInertiaTensor(part.mechanical.inertiaKgM2, pose.quaternion_wxyz);
    const comNode = nodeComWorldM[node.node_id];
    const d: [number, number, number] = [
      comNode[0] - centerOfMassWorldM[0],
      comNode[1] - centerOfMassWorldM[1],
      comNode[2] - centerOfMassWorldM[2],
    ];
    const shifted = parallelAxisShift(rotated, part.mechanical.massKg, d);
    totalInertia.ixx += shifted.ixx;
    totalInertia.iyy += shifted.iyy;
    totalInertia.izz += shifted.izz;
    totalInertia.ixy += shifted.ixy;
    totalInertia.ixz += shifted.ixz;
    totalInertia.iyz += shifted.iyz;
  }

  const totalInertiaCheck = isValidInertiaTensor(totalInertia);
  if (!totalInertiaCheck.valid) {
    addFinding(
      'CW-DRC-03',
      'mechanics_mass',
      'conflict',
      'MASS_TOTAL_INERTIA_INVALID',
      ['/nodes'],
      `Aggregated assembly inertia tensor is invalid: ${totalInertiaCheck.reason}.`,
    );
  }

  if (!allPartsDrawingReviewed) {
    addFinding(
      'CW-DRC-03',
      'mechanics_mass',
      'blocked',
      'MECHANICAL_PROXY_UNQUALIFIED',
      assembly.nodes
        .map((n, i) => ({ n, i, p: nodeMap.get(n.node_id)!.part }))
        .filter(x => x.p.mechanical.basis !== 'drawing_reviewed')
        .map(x => `/nodes/${x.i}/part_id`),
      'Assembly uses simulation_proxy geometry or illustrative snap ports; physical fit and clearance remain unqualified.',
      'Replace proxy geometry with drawing-reviewed CAD and tolerances in CW-D01 before physical qualification.',
    );
  }

  // Unknown-Aware BOM calculation
  const bomGroups = new Map<string, { part: DrcPart; nodeIds: string[]; nodeRefs: string[] }>();
  assembly.nodes.forEach((node, idx) => {
    const { part } = nodeMap.get(node.node_id)!;
    const group = bomGroups.get(part.partId) ?? { part, nodeIds: [], nodeRefs: [] };
    group.nodeIds.push(node.node_id);
    group.nodeRefs.push(`/nodes/${idx}`);
    bomGroups.set(part.partId, group);
  });

  const bomLines: BomLineItem[] = [];
  let knownSubtotalUsd = 0;
  let pricedPartCount = 0;
  let unpricedPartCount = 0;

  for (const { part, nodeIds, nodeRefs } of [...bomGroups.values()].sort((a, b) => lex(a.part.partId, b.part.partId))) {
    const qty = nodeIds.length;
    const cost = part.bomCostUsd;
    const basis = part.costBasis;
    const datedSkus = part.supplierSkus.filter(s => Boolean(s.quoted_on)).length;

    if ((basis === 'unknown') !== (cost === null)) {
      addFinding(
        'CW-DRC-03',
        'bom_cost',
        'conflict',
        'BOM_COST_BASIS_CONFLICT',
        [...nodeRefs, `part:${part.partId}#/identity/bom_cost_usd`],
        `Part '${part.partId}' has inconsistent cost_basis='${basis}' and bom_cost_usd=${String(cost)} (unknown price must never be treated as $0 free).`,
      );
    } else if (basis !== 'unknown' && cost !== null && cost <= 0) {
      addFinding(
        'CW-DRC-03',
        'bom_cost',
        'conflict',
        'BOM_ZERO_OR_NEGATIVE_PRICE',
        [...nodeRefs, `part:${part.partId}#/identity/bom_cost_usd`],
        `Part '${part.partId}' declares non-positive unit price ($${cost}); unknown prices must remain null rather than $0.`,
      );
    } else if (basis === 'supplier_quote' && datedSkus === 0) {
      addFinding(
        'CW-DRC-03',
        'bom_cost',
        'conflict',
        'BOM_QUOTE_MISSING_DATE',
        [...nodeRefs, `part:${part.partId}#/identity/supplier_skus`],
        `Part '${part.partId}' claims cost_basis='supplier_quote' without a dated supplier SKU.`,
      );
    }

    const validPriced = basis !== 'unknown' && typeof cost === 'number' && Number.isFinite(cost) && cost > 0;
    const lineTotal = validPriced ? Math.round(cost * qty * 100) / 100 : null;
    if (lineTotal !== null) {
      knownSubtotalUsd = Math.round((knownSubtotalUsd + lineTotal) * 100) / 100;
      pricedPartCount += qty;
    } else {
      unpricedPartCount += qty;
    }

    bomLines.push({
      partId: part.partId,
      version: part.version,
      name: part.name,
      category: part.category,
      status: part.status,
      quantity: qty,
      nodeIds: [...nodeIds].sort(lex),
      unitCostUsd: validPriced ? cost : null,
      costBasis: basis,
      lineTotalUsd: lineTotal,
      quotedSkus: datedSkus,
    });
  }

  if (unpricedPartCount > 0) {
    addFinding(
      'CW-DRC-03',
      'bom_cost',
      'blocked',
      'BOM_UNPRICED_PARTS',
      assembly.nodes
        .map((n, i) => ({ n, i, p: nodeMap.get(n.node_id)!.part }))
        .filter(x => x.p.bomCostUsd === null || x.p.costBasis === 'unknown')
        .map(x => `/nodes/${x.i}/part_id`),
      `BOM has ${unpricedPartCount} unpriced component instance(s) across ${bomLines.filter(l => l.lineTotalUsd === null).length} part family(ies); known subtotal is $${knownSubtotalUsd.toFixed(2)} (unpriced items are excluded, never counted as $0).`,
      'Record dated supplier quotations in CW-D01 before publishing a complete BOM subtotal.',
    );
  }

  const assemblyDigest = sha256Hex(canonicalAssemblyString(assembly));
  const electricalPlanDigest = sha256Hex(
    canonicalAssemblyString({
      assembly_digest: assemblyDigest,
      electrical_nets: assembly.electrical_nets,
      routing_proposals: routingProposals.map(p => ({
        proposal_id: p.proposalId,
        net_id: p.netId,
        kind: p.kind,
        protocol: p.protocol,
        controller_node_id: p.controllerNodeId,
        controller_interface_id: p.controllerInterfaceId,
        peripheral_endpoints: p.peripheralEndpoints.map(ep => ({
          node_id: ep.nodeId,
          interface_id: ep.interfaceId,
          assigned_device_id: ep.assignedDeviceId,
          i2c_address: ep.i2cAddress,
        })),
        status: p.status,
      })),
      servo_addresses_by_net: servoAddressesByNet,
    }),
  );

  const conflictCount = findings.filter(f => f.severity === 'conflict').length;
  const blockedCount = findings.filter(f => f.severity === 'blocked').length;
  const disposition: DrcDisposition =
    conflictCount > 0 ? 'conflict' : blockedCount > 0 ? 'blocked' : 'pass';

  return {
    schemaVersion: 'seedcore.drc.report.v1',
    scope: 'offline_proxy_authoring',
    physicalAcceptance: false,
    executionAuthority: 'none',
    catalogProvenance: catalog.provenance,
    catalogDigest: catalog.catalogDigest,
    assemblyDigest,
    electricalPlanDigest,
    disposition,
    counts: { conflict: conflictCount, blocked: blockedCount },
    findings,
    routingProposals,
    servoAddressesByNet,
    powerRails,
    massProperties: {
      totalMassKg,
      centerOfMassWorldM,
      inertiaWorldAtComKgM2: totalInertia,
      principalMomentsKgM2: totalInertiaCheck.principalMoments,
      nodeComWorldM,
      allPartsDrawingReviewed,
    },
    bom: {
      lines: bomLines,
      knownSubtotalUsd,
      pricedPartCount,
      unpricedPartCount,
      uniquePartCount: bomLines.length,
      totalNodeCount: assembly.nodes.length,
      completePricing: unpricedPartCount === 0 && conflictCount === 0,
    },
  };
}

/**
 * Helper to verify that discarding off-diagonal inertia terms or skipping parallel-axis
 * shifts produces a detectable discrepancy on rotated/offset multi-body assemblies.
 */
export function verifyInertiaAggregationFidelity(
  assembly: RobotAssembly,
  catalog: DrcCatalog,
): {
  fullTensor: DrcInertiaTensor;
  diagonalOnlyNaivelySummed: DrcInertiaTensor;
  offDiagonalMagnitude: number;
  parallelAxisShiftMagnitude: number;
} {
  const report = evaluateAssemblyDrc(assembly, catalog);
  const full = report.massProperties.inertiaWorldAtComKgM2;
  const naive: DrcInertiaTensor = { ixx: 0, iyy: 0, izz: 0, ixy: 0, ixz: 0, iyz: 0 };
  const partMap = new Map(catalog.parts.map(p => [p.partId, p]));
  for (const node of assembly.nodes) {
    const part = partMap.get(node.part_id)!;
    naive.ixx += part.mechanical.inertiaKgM2.ixx;
    naive.iyy += part.mechanical.inertiaKgM2.iyy;
    naive.izz += part.mechanical.inertiaKgM2.izz;
  }
  const offDiagonalMagnitude = Math.hypot(full.ixy, full.ixz, full.iyz);
  const parallelAxisShiftMagnitude = Math.hypot(
    full.ixx - naive.ixx,
    full.iyy - naive.iyy,
    full.izz - naive.izz,
  );
  return {
    fullTensor: full,
    diagonalOnlyNaivelySummed: naive,
    offDiagonalMagnitude,
    parallelAxisShiftMagnitude,
  };
}
