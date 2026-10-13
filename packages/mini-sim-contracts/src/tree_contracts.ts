// SIM-3 Kinematic Tree Contracts & Compiler
// Multi-link serial chains (1-link, 2-link, 3-link), forward kinematics 3D points, and Wasm buffer packing.

namespace MiniSimContracts {
  export namespace Tree {
    export const SCHEMA = 'seedcore.mini-sim.tree-model.v1';
    export const PROTOCOL = 'seedcore.mini-lab.worker.v3';

    export interface TreeLink {
      name: string;
      length: number;    // meters (> 0)
      mass: number;      // kg (> 0)
      com: number;       // COM distance from joint (>= 0, <= length)
      inertia: number;   // moment of inertia about COM (> 0)
      damping: number;   // viscous damping (>= 0)
      jointLimits?: readonly [number, number]; // metadata [min, max]; stops are not simulated
    }

    export interface TreeModelInput {
      schema?: typeof SCHEMA;
      modelId: string;
      numLinks: number; // 1, 2, or 3
      links: TreeLink[];
      gravity: number;
      encoders?: Array<'joint_pos' | 'joint_vel' | 'tip_pos' | 'energy'>;
    }

    export interface CompiledTreeModel {
      schema: typeof SCHEMA;
      modelId: string;
      modelDigest: string; // sha256:...
      numLinks: number;
      nq: number;
      nv: number;
      links: ReadonlyArray<Readonly<TreeLink>>;
      gravity: number;
      encoders: ReadonlyArray<string>;
    }

    export interface Point3D {
      x: number;
      y: number;
      z: number;
    }

    export interface TreePose3D {
      origin: Point3D;
      joints: Point3D[];
      tip: Point3D;
    }

  export function validateTreeModel(m: unknown): m is TreeModelInput {
    if (!m || typeof m !== 'object' || Array.isArray(m)) return false;
    const model = m as Record<string, unknown>;
    if (Object.keys(model).some(key => !['schema', 'modelId', 'numLinks', 'links', 'gravity', 'encoders'].includes(key))) return false;
    if (model.schema !== undefined && model.schema !== SCHEMA) return false;
    if (typeof model.modelId !== 'string' || model.modelId.length === 0 || model.modelId.length > 64) return false;
    if (!Number.isInteger(model.numLinks) || (model.numLinks as number) < 1 || (model.numLinks as number) > 3) return false;
    if (!Array.isArray(model.links) || model.links.length !== model.numLinks) return false;
    if (typeof model.gravity !== 'number' || !Number.isFinite(model.gravity) || model.gravity < 0 || model.gravity > 50) return false;
    if (model.encoders !== undefined) {
      if (!Array.isArray(model.encoders) || model.encoders.length > 4 ||
          new Set(model.encoders).size !== model.encoders.length) return false;
      for (const encoder of model.encoders) {
        if (!['joint_pos', 'joint_vel', 'tip_pos', 'energy'].includes(encoder)) return false;
      }
    }

    for (const link of model.links as TreeLink[]) {
      if (!link || typeof link !== 'object' || Array.isArray(link)) return false;
      if (Object.keys(link).some(key => !['name', 'length', 'mass', 'com', 'inertia', 'damping', 'jointLimits'].includes(key))) return false;
      if (typeof link.name !== 'string' || link.name.length === 0 || link.name.length > 32) return false;
      if (typeof link.length !== 'number' || !Number.isFinite(link.length) || link.length <= 0 || link.length > 10) return false;
      if (typeof link.mass !== 'number' || !Number.isFinite(link.mass) || link.mass <= 0 || link.mass > 100) return false;
      if (typeof link.com !== 'number' || !Number.isFinite(link.com) || link.com < 0 || link.com > link.length) return false;
      if (typeof link.inertia !== 'number' || !Number.isFinite(link.inertia) || link.inertia <= 0 || link.inertia > 100) return false;
      if (typeof link.damping !== 'number' || !Number.isFinite(link.damping) || link.damping < 0 || link.damping > 100) return false;
      if (link.jointLimits !== undefined) {
        if (!Array.isArray(link.jointLimits) || link.jointLimits.length !== 2) return false;
        if (!Number.isFinite(link.jointLimits[0]) || !Number.isFinite(link.jointLimits[1]) || link.jointLimits[0] >= link.jointLimits[1]) return false;
      }
    }
    return true;
  }

  export function compileTreeModel(input: TreeModelInput): CompiledTreeModel {
    if (!validateTreeModel(input)) {
      throw new Error('Invalid TreeModel input');
    }

    const canonical = {
      schema: SCHEMA,
      modelId: input.modelId,
      numLinks: input.numLinks,
      links: input.links.map(l => ({
        name: l.name,
        length: l.length,
        mass: l.mass,
        com: l.com,
        inertia: l.inertia,
        damping: l.damping,
        jointLimits: l.jointLimits ? Object.freeze([...l.jointLimits] as [number, number]) : undefined
      })),
      gravity: input.gravity,
      encoders: input.encoders || ['joint_pos', 'joint_vel', 'tip_pos', 'energy']
    };

    const canonicalJson = JSON.stringify(canonical);
    const modelDigest = sha256Bytes(new TextEncoder().encode(canonicalJson));

    return Object.freeze({
      schema: SCHEMA,
      modelId: input.modelId,
      modelDigest,
      numLinks: input.numLinks,
      nq: input.numLinks,
      nv: input.numLinks,
      links: Object.freeze(canonical.links.map(l => Object.freeze(l))),
      gravity: canonical.gravity,
      encoders: Object.freeze([...canonical.encoders])
    });
  }

  export function forwardKinematics3D(model: CompiledTreeModel, q: number[]): TreePose3D {
    validateVector(q, model.numLinks, 'q');
    const joints: Point3D[] = [];
    let phi = 0;
    let x = 0;
    let y = 0;

    const origin: Point3D = { x: 0, y: 0, z: 0 };

    for (let i = 0; i < model.numLinks; i++) {
      phi += q[i];
      x += model.links[i].length * Math.cos(phi);
      y += model.links[i].length * Math.sin(phi);
      joints.push({ x, y, z: 0 });
    }

    const tip = joints[joints.length - 1];
    return { origin, joints, tip };
  }

  export function packTreeBuffer(
    model: CompiledTreeModel,
    q: number[],
    v: number[],
    t: number,
    tau: number[],
    dt: number,
    target: number[],
    tauMax: number,
    motors: boolean
  ): Float64Array {
    validateVector(q, model.numLinks, 'q');
    validateVector(v, model.numLinks, 'v', true);
    validateVector(tau, model.numLinks, 'tau', true);
    validateVector(target, model.numLinks, 'target', true);
    if (!Number.isFinite(t) || t < 0 || !Number.isFinite(dt) || dt < 0 || dt > 1 / 120 ||
        !Number.isFinite(tauMax) || tauMax < 0 || tauMax > 100 || typeof motors !== 'boolean') {
      throw new Error('Invalid tree time or control input');
    }
    const buf = new Float64Array(64);
    buf[0] = model.numLinks;
    for (let i = 0; i < model.numLinks; i++) {
      buf[1 + i] = model.links[i].length;
      buf[4 + i] = model.links[i].mass;
      buf[7 + i] = model.links[i].com;
      buf[10 + i] = model.links[i].inertia;
      buf[13 + i] = model.links[i].damping;
    }
    buf[16] = model.gravity;

    for (let i = 0; i < model.numLinks; i++) {
      buf[17 + i] = q[i];
      buf[20 + i] = v.length === 0 ? 0 : v[i];
      buf[24 + i] = tau.length === 0 ? 0 : tau[i];
      buf[28 + i] = target.length === 0 ? 0 : target[i];
    }
    buf[23] = t;
    buf[27] = dt;
    buf[31] = tauMax;
    buf[32] = motors ? 1.0 : 0.0;

    return buf;
  }

  function validateVector(values: number[], n: number, name: string, allowEmpty = false): void {
    if (!Array.isArray(values) || (values.length !== n && !(allowEmpty && values.length === 0))) {
      throw new Error(`${name} dimension mismatch`);
    }
    for (const value of values) {
      if (!Number.isFinite(value)) throw new Error(`Invalid ${name} component`);
    }
  }
}
}
