import loadMujoco, { type MainModule, type MjData, type MjModel } from '@mujoco/mujoco';
import { readCwS01Xml } from './mujocoXml.js';
import {
  CW_S01_COMPILER,
  CW_S01_SUBSET,
  SIMULATION_READINESS_POLICY,
  assertCompiledModelCurrent,
  type CompiledMjcf,
  type CurrentModelBinding,
} from './compiler.js';
import {
  CwS02Error,
  MUJOCO_WASM_BYTES,
  MUJOCO_WASM_ENGINE,
  MUJOCO_WASM_PROFILE,
  MUJOCO_WASM_SHA256,
  MUJOCO_WASM_VERSION,
  verifyPinnedMujocoWasmBytes,
  type CwS02BodyFrameSnapshot,
  type CwS02ForwardSnapshot,
  type CwS02ModelInspection,
} from './mujocoAsset.js';

export type MujocoMainModule = MainModule;
export type { MjModel, MjData };

const cachedModuleBySha = new Map<string, Promise<MainModule>>();

/** Instantiate @mujoco/mujoco@3.15.0 only after verifying exact pinned Wasm bytes. */
export async function loadVerifiedMujocoModule(
  wasmBytes: BufferSource,
  expectedBytes: number = MUJOCO_WASM_BYTES,
  expectedSha256: string = MUJOCO_WASM_SHA256,
): Promise<MainModule> {
  const verified = await verifyPinnedMujocoWasmBytes(wasmBytes, expectedBytes, expectedSha256);
  let pending = cachedModuleBySha.get(expectedSha256);
  if (!pending) {
    pending = loadMujoco({ wasmBinary: verified }).catch(error => {
      cachedModuleBySha.delete(expectedSha256);
      throw new CwS02Error('ENGINE_COMPILE_FAILED', String(error));
    });
    cachedModuleBySha.set(expectedSha256, pending);
  }
  return pending;
}

export class MujocoModelSession {
  private disposed = false;
  readonly bodyIds: Readonly<Record<string, number>>;
  readonly jointIds: Readonly<Record<string, number>>;
  readonly actuatorIds: Readonly<Record<string, number>>;
  readonly actuatorCtrlRanges: readonly (readonly [number, number])[];
  readonly jointRanges: readonly (readonly [number, number])[];
  readonly actuatorForceRanges: readonly (readonly [number, number])[];
  readonly jointActuatorForceRanges: readonly (readonly [number, number])[];

  constructor(
    readonly mujoco: MainModule,
    readonly artifact: CompiledMjcf,
    readonly binding: CurrentModelBinding,
    readonly model: MjModel,
    readonly data: MjData,
    readonly wasmSha256: string = MUJOCO_WASM_SHA256,
    readonly wasmBytes: number = MUJOCO_WASM_BYTES,
  ) {
    const manifest = artifact.manifest;
    const declared = readCwS01Xml(artifact.xml);
    const declaredJoints = declared.filter(e => e.tag === 'joint');
    const declaredActuators = declared.filter(e => e.tag === 'position' || e.tag === 'motor');
    const nJoints = manifest.joints.length;
    const nBodies = manifest.bodies.length;
    if (
      model.nbody !== nBodies + 1 ||
      model.njnt !== nJoints ||
      model.nq !== nJoints ||
      model.nv !== nJoints ||
      model.nu !== nJoints || model.na !== 0 || model.ngeom !== nBodies ||
      declaredJoints.length !== nJoints || declaredActuators.length !== nJoints ||
      manifest.bodies.some((b, i) => b.parentNodeId !== (i === 0 ? null : manifest.bodies[i-1].nodeId)) ||
      manifest.joints.some(j => j.childNodeId === manifest.bodies[0].nodeId)
    ) {
      const actual = `${model.nbody}/${model.njnt}/${model.nq}/${model.nv}/${model.nu}`;
      this.dispose();
      throw new CwS02Error('MODEL_TOPOLOGY_MISMATCH', `Compiled MuJoCo topology (${actual}) disagrees with manifest (${nBodies + 1}/${nJoints})`);
    }
    const actualDt = model.opt.timestep;
    if (Math.abs(actualDt - manifest.options.timestepSeconds) > 1e-12) {
      this.dispose();
      throw new CwS02Error(
        'MODEL_TOPOLOGY_MISMATCH',
        `Compiled MuJoCo timestep ${actualDt} disagrees with manifest ${manifest.options.timestepSeconds}`,
      );
    }

    const bodyIds: Record<string, number> = Object.create(null);
    for (let i = 0; i < nBodies; i++) {
      const b = manifest.bodies[i];
      const id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY.value, b.bodyName);
      if (id !== i + 1) {
        this.dispose();
        throw new CwS02Error('MODEL_TOPOLOGY_MISMATCH', `Body ${b.bodyName} resolved to ${id}, expected ${i + 1}`);
      }
      const parentId = b.parentNodeId === null ? 0 : bodyIds[b.parentNodeId];
      if (model.body_parentid[id] !== parentId) throw new CwS02Error('MODEL_TOPOLOGY_MISMATCH', 'Body parent differs from manifest');
      bodyIds[b.nodeId] = id;
    }

    const jointIds: Record<string, number> = Object.create(null);
    const actuatorIds: Record<string, number> = Object.create(null);
    const jointRanges: [number, number][] = [];
    const actuatorCtrlRanges: [number, number][] = [];
    const actuatorForceRanges: [number, number][] = [];
    const jointActuatorForceRanges: [number, number][] = [];
    const expectedGain = manifest.options.actuatorMode === 'position' ? (manifest.options.positionGain ?? 10) : 1;

    for (let i = 0; i < nJoints; i++) {
      const j = manifest.joints[i];
      const jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT.value, j.jointName);
      const aid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR.value, j.actuatorName);
      if (jid !== i || aid !== i) {
        this.dispose();
        throw new CwS02Error(
          'MODEL_TOPOLOGY_MISMATCH',
          `Joint/actuator ${j.jointName}/${j.actuatorName} resolved to ${jid}/${aid}, expected ${i}`,
        );
      }
      if (
        model.jnt_type[i] !== mujoco.mjtJoint.mjJNT_HINGE.value ||
        Math.abs(model.qpos0[i] - j.restAngleRad) > 1e-12 ||
        model.actuator_trnid[2 * i] !== i ||
        model.jnt_bodyid[i] !== bodyIds[j.childNodeId] ||
        !model.jnt_limited[i] || !model.jnt_actfrclimited[i] ||
        !model.actuator_ctrllimited[i] ||
        !model.actuator_forcelimited[i] ||
        Math.abs(model.actuator_gainprm[10 * i] - expectedGain) > 1e-12
      ) {
        this.dispose();
        throw new CwS02Error('MODEL_TOPOLOGY_MISMATCH', `Joint/actuator parameters mismatch at index ${i}`);
      }
      const jRange: [number, number] = [model.jnt_range[2 * i], model.jnt_range[2 * i + 1]];
      const cRange: [number, number] = [model.actuator_ctrlrange[2 * i], model.actuator_ctrlrange[2 * i + 1]];
      const fRange: [number, number] = [model.actuator_forcerange[2 * i], model.actuator_forcerange[2 * i + 1]];
      const jfRange: [number, number] = [model.jnt_actfrcrange[2 * i], model.jnt_actfrcrange[2 * i + 1]];
      const dj = declaredJoints[i]?.attrs, da = declaredActuators[i]?.attrs;
      if (!dj || !da || declaredActuators[i].tag !== (manifest.options.actuatorMode === 'position' ? 'position' : 'motor') ||
          dj.name !== j.jointName || da.name !== j.actuatorName || da.joint !== j.jointName ||
          [[jRange,dj.range],[cRange,da.ctrlrange],[fRange,da.forcerange],[jfRange,dj.actuatorfrcrange]].some(([actual, raw]) =>
            (actual as number[]).some((v, k) => v !== Number((raw as string).split(' ')[k])))) {
        throw new CwS02Error('MODEL_TOPOLOGY_MISMATCH', 'Compiled ranges or actuator mode differ from pinned XML declarations');
      }
      if (!(jRange[0] < jRange[1]) || !(cRange[0] < cRange[1]) || !(fRange[0] < fRange[1])) {
        this.dispose();
        throw new CwS02Error('MODEL_TOPOLOGY_MISMATCH', `Invalid range bounds at joint/actuator ${i}`);
      }
      jointIds[j.jointId] = jid;
      actuatorIds[j.actuatorName] = aid;
      jointRanges.push(jRange);
      actuatorCtrlRanges.push(cRange);
      actuatorForceRanges.push(fRange);
      jointActuatorForceRanges.push(jfRange);
    }

    this.bodyIds = Object.freeze(bodyIds);
    this.jointIds = Object.freeze(jointIds);
    this.actuatorIds = Object.freeze(actuatorIds);
    this.jointRanges = Object.freeze(jointRanges.map(r => Object.freeze(r))) as readonly (readonly [number, number])[];
    this.actuatorCtrlRanges = Object.freeze(actuatorCtrlRanges.map(r => Object.freeze(r))) as readonly (readonly [number, number])[];
    this.actuatorForceRanges = Object.freeze(actuatorForceRanges.map(r => Object.freeze(r))) as readonly (readonly [number, number])[];
    this.jointActuatorForceRanges = Object.freeze(jointActuatorForceRanges.map(r => Object.freeze(r))) as readonly (readonly [number, number])[];
    this.resetToHome();
  }

  assertOpen(): void {
    if (this.disposed) {
      throw new CwS02Error('SESSION_DISPOSED', 'MuJoCo model session has already been disposed');
    }
  }

  get isDisposed(): boolean {
    return this.disposed;
  }

  resetToHome(): void {
    this.assertOpen();
    this.mujoco.mj_resetData(this.model, this.data);
    this.data.qpos.set(this.model.qpos0);
    this.data.qvel.fill(0);
    this.data.act.fill(0);
    this.data.ctrl.fill(0);
    this.data.qfrc_applied.fill(0);
    this.data.xfrc_applied.fill(0);
    this.mujoco.mj_forward(this.model, this.data);
  }

  inspectModel(): CwS02ModelInspection {
    this.assertOpen();
    const nbody = this.model.nbody;
    const bodyInertia: [number, number, number][] = [];
    for (let b = 0; b < nbody; b++) {
      bodyInertia.push([
        this.model.body_inertia[3 * b],
        this.model.body_inertia[3 * b + 1],
        this.model.body_inertia[3 * b + 2],
      ]);
    }
    const actuatorGain0: number[] = [];
    for (let i = 0; i < this.model.nu; i++) {
      actuatorGain0.push(this.model.actuator_gainprm[10 * i]);
    }
    return {
      profile: MUJOCO_WASM_PROFILE,
      engine: MUJOCO_WASM_ENGINE,
      engineVersion: MUJOCO_WASM_VERSION,
      wasmBytes: this.wasmBytes,
      wasmSha256: this.wasmSha256,
      scope: 'offline_simulation_only',
      physicalAcceptance: false,
      executionAuthority: 'none',
      planarFallbackUsed: false,
      modelDigest: this.artifact.modelDigest,
      nq: this.model.nq,
      nv: this.model.nv,
      nu: this.model.nu,
      nbody: this.model.nbody,
      njnt: this.model.njnt,
      timestepSeconds: this.model.opt.timestep,
      bodyIds: { ...this.bodyIds },
      jointIds: { ...this.jointIds },
      actuatorIds: { ...this.actuatorIds },
      bodyMass: Array.from(this.model.body_mass),
      bodySubtreeMass: Array.from(this.model.body_subtreemass),
      bodyInertia,
      qpos0: Array.from(this.model.qpos0),
      jointRanges: this.jointRanges.map(r => [r[0], r[1]]),
      actuatorCtrlRanges: this.actuatorCtrlRanges.map(r => [r[0], r[1]]),
      actuatorForceRanges: this.actuatorForceRanges.map(r => [r[0], r[1]]),
      jointActuatorForceRanges: this.jointActuatorForceRanges.map(r => [r[0], r[1]]),
      actuatorGain0,
    };
  }

  evaluateForwardKinematics(qpos: readonly number[]): CwS02ForwardSnapshot {
    this.assertOpen();
    if (!Array.isArray(qpos) || qpos.length !== this.model.nq || !qpos.every(v => typeof v === 'number' && Number.isFinite(v))) {
      throw new CwS02Error('CONTROL_VETOED', 'FK state vector must match nq and contain only finite numbers', 'CONTROL_NONFINITE');
    }
    this.mujoco.mj_resetData(this.model, this.data);
    for (let i = 0; i < this.model.nq; i++) {
      this.data.qpos[i] = qpos[i];
    }
    this.data.qvel.fill(0);
    this.data.act.fill(0);
    this.data.ctrl.fill(0);
    this.data.qfrc_applied.fill(0);
    this.data.xfrc_applied.fill(0);
    this.mujoco.mj_forward(this.model, this.data);

    const rootNodeId = this.artifact.manifest.bodies[0].nodeId;
    const rootBid = this.bodyIds[rootNodeId];
    const rootSubtreeCom: [number, number, number] = [
      this.data.subtree_com[3 * rootBid],
      this.data.subtree_com[3 * rootBid + 1],
      this.data.subtree_com[3 * rootBid + 2],
    ];

    const bodies: CwS02BodyFrameSnapshot[] = this.artifact.manifest.bodies.map(b => {
      const bid = this.bodyIds[b.nodeId];
      return {
        nodeId: b.nodeId,
        bodyName: b.bodyName,
        bodyId: bid,
        xpos: [this.data.xpos[3 * bid], this.data.xpos[3 * bid + 1], this.data.xpos[3 * bid + 2]],
        xquat: [
          this.data.xquat[4 * bid],
          this.data.xquat[4 * bid + 1],
          this.data.xquat[4 * bid + 2],
          this.data.xquat[4 * bid + 3],
        ],
        xmat: Array.from(this.data.xmat.subarray(9 * bid, 9 * bid + 9)),
        xipos: [this.data.xipos[3 * bid], this.data.xipos[3 * bid + 1], this.data.xipos[3 * bid + 2]],
        ximat: Array.from(this.data.ximat.subarray(9 * bid, 9 * bid + 9)),
        bodyMass: this.model.body_mass[bid],
        bodySubtreeMass: this.model.body_subtreemass[bid],
        bodyInertia: [
          this.model.body_inertia[3 * bid],
          this.model.body_inertia[3 * bid + 1],
          this.model.body_inertia[3 * bid + 2],
        ],
      };
    });

    return {
      qpos: Array.from(this.data.qpos),
      rootSubtreeCom,
      bodies,
    };
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    try {
      this.data.delete();
    } catch {}
    try {
      this.model.delete();
    } catch {}
  }
}

/** Validate and load a verified CompiledMjcf bundle into @mujoco/mujoco@3.15.0 without planar fallback. */
export function createMujocoModelSession(
  mujoco: MainModule,
  artifact: CompiledMjcf,
  binding: CurrentModelBinding,
): MujocoModelSession {
  artifact = structuredClone(artifact);
  binding = Object.freeze({ ...binding });
  const freeze = (value: any): void => { if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); } };
  freeze(artifact);
  try {
    assertCompiledModelCurrent(artifact, binding);
  } catch (error) {
    throw new CwS02Error('MODEL_BINDING_MISMATCH', error instanceof Error ? error.message : String(error));
  }
  const manifest = artifact.manifest;
  if (
    manifest.compiler !== CW_S01_COMPILER ||
    manifest.subset !== CW_S01_SUBSET ||
    !['position','torque'].includes(manifest.options.actuatorMode) ||
    !Number.isFinite(manifest.options.timestepSeconds) || manifest.options.timestepSeconds < 0.0001 || manifest.options.timestepSeconds > 0.01 ||
    manifest.readiness?.policy !== SIMULATION_READINESS_POLICY ||
    manifest.readiness.scope !== 'offline_simulation_only' ||
    manifest.readiness.blockingFindings.length !== 0 ||
    !manifest.readiness?.ready ||
    manifest.readiness.physicalAcceptance !== false ||
    manifest.readiness.executionAuthority !== 'none' ||
    manifest.bodies.length < 2 ||
    manifest.bodies.length > 32 ||
    manifest.joints.length < 1 ||
    manifest.joints.length > 3
  ) {
    throw new CwS02Error(
      'UNSUPPORTED_SUBSET',
      'CW-S02 requires a simulation-ready seedcore.cw-s01.model.v1 fixed_tabletop_serial_boxes_v1 bundle',
    );
  }
  readCwS01Xml(artifact.xml);
  if (mujoco.mj_versionString() !== MUJOCO_WASM_VERSION) throw new CwS02Error('ENGINE_COMPILE_FAILED', 'Loaded MuJoCo engine version differs from the pinned runtime');
  let model: MjModel | undefined;
  let data: MjData | undefined;
  try {
    model = mujoco.MjModel.from_xml_string(artifact.xml);
    if (!model) {
      throw new Error('MjModel.from_xml_string returned null');
    }
    data = new mujoco.MjData(model);
  } catch (error) {
    try {
      data?.delete();
    } catch {}
    try {
      model?.delete();
    } catch {}
    throw new CwS02Error('ENGINE_COMPILE_FAILED', error instanceof Error ? error.message : String(error));
  }
  try { return new MujocoModelSession(mujoco, artifact, binding, model, data); }
  catch (error) {
    // Constructor validation can throw before a session exists; release both handles.
    try { if (!data.isDeleted()) data.delete(); } catch {}
    try { if (!model.isDeleted()) model.delete(); } catch {}
    throw error;
  }
}
