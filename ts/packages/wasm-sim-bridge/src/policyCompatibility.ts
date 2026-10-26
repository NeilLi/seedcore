/** CW-S03 offline contract preflight. This module never loads or executes a policy. */
import { canonicalAssemblyString, parseStrictJson } from '@seedcore/contracts';
import { sha256Hex } from '@seedcore/drc-solver';

export const POLICY_PREFLIGHT = 'seedcore.cw-s03.policy-preflight.v1' as const;
export interface ObservationField { name: string; start: number; width: number; units: string }
export interface ObservationContract {
  layout: ObservationField[];
  normalization: 'embedded_in_onnx' | 'adapter' | 'none' | 'unknown';
  previousAction: 'raw_policy_action' | 'processed_action' | 'none' | 'unknown';
}
export interface TensorContract { name: string; shape: number[]; dtype: 'float32' | 'float64' | 'unknown' }
export interface PolicyContract {
  policyId: string;
  inspectedSha256: string | null;
  sourceRevision: string;
  licenseSpdx: string | null;
  expectedModelDigest: string;
  topology: 'fixed_base_serial' | 'floating_base';
  input: TensorContract;
  output: TensorContract;
  observation: ObservationContract;
  jointOrder: string[];
  homeRad: number[];
  actionScale: number;
  actionSemantics: 'home_plus_scaled_position' | 'torque' | 'unknown';
  requiredActuatorProfile: string | null;
  policyPeriodSeconds: number;
}
export interface PolicyModelContract {
  modelDigest: string;
  topology: 'fixed_base_serial' | 'floating_base';
  jointOrder: string[];
  actuatorProfile: string;
}
export interface PolicyAdapterContract {
  adapterId: string;
  implemented: boolean;
  modelDigest: string;
  supportedTopology: 'fixed_base_serial' | 'floating_base';
  input: TensorContract | null;
  output: TensorContract | null;
  observation: ObservationContract | null;
  jointOrder: string[];
  homeRad: number[];
  actionScale: number;
  actionSemantics: 'home_plus_scaled_position' | 'torque' | 'unknown';
  actuatorProfile: string;
  physicsTimestepSeconds: number;
  policyDecimation: number;
}
export type EvidenceStatus = 'verified' | 'missing' | 'failed' | 'not_run';
export interface PolicyEvidence {
  status: EvidenceStatus;
  kind: 'artifact_replay' | 'training_checkpoint' | 'runtime_pair' | 'operator_coverage' | 'browser_timing' | 'synthetic_fixture' | 'unavailable';
  policySha256: string | null;
  modelDigest: string | null;
  adapterDigest: string | null;
  sourceSha256: string | null;
}
export const POLICY_EVIDENCE_ROLES = ['artifactReplay', 'trainingReference', 'runtimePair', 'operatorCoverage', 'browserTiming'] as const;
export type EvidenceRole = typeof POLICY_EVIDENCE_ROLES[number];
export interface PolicyCompatibilityInput {
  schemaVersion: typeof POLICY_PREFLIGHT;
  provenance: 'verified_local_artifacts' | 'synthetic_fixture';
  /** Caller-retained pins, independent of the candidate metadata being assessed. */
  pins: { policySha256: string; modelDigest: string; adapterDigest: string };
  policy: PolicyContract;
  model: PolicyModelContract;
  adapter: PolicyAdapterContract;
  evidence: Record<EvidenceRole, PolicyEvidence>;
}
export interface PolicyCompatibilityFinding { code: string; field: string; message: string }
export interface PolicyCompatibilityReport {
  schemaVersion: 'seedcore.cw-s03.policy-preflight-report.v1';
  checker: typeof POLICY_PREFLIGHT;
  scope: 'offline_policy_compatibility_preflight';
  physicalAcceptance: false;
  executionAuthority: 'none';
  runtimeQualification: 'not_granted';
  provenance: PolicyCompatibilityInput['provenance'] | 'invalid_input';
  decision: 'contract_consistent' | 'blocked';
  inputDigest: string | null;
  pins: PolicyCompatibilityInput['pins'] | null;
  evidence: Record<EvidenceRole, EvidenceStatus> | null;
  findings: PolicyCompatibilityFinding[];
  reportDigest: string;
}
const hash = (value: unknown) => sha256Hex(canonicalAssemblyString(value));
export const computePolicyAdapterDigest = (adapter: PolicyAdapterContract): string => hash(adapter);

// Strict bounded JSON validation also applies to direct JS callers, not just CLI text.
function validateInput(value: unknown): PolicyCompatibilityInput {
  const text = canonicalAssemblyString(value);
  const input = parseStrictJson(text) as any;
  const fail = (path: string): never => { throw new Error(`Malformed or unsupported contract at ${path}`); };
  const record = (v: any, keys: string[], path: string) => {
    if (!v || typeof v !== 'object' || Array.isArray(v) || Object.keys(v).length !== keys.length || keys.some(k => !Object.hasOwn(v,k))) fail(path);
  };
  const str = (v: any, path: string) => { if (typeof v !== 'string' || v.trim().length < 1 || v.length > 256) fail(path); };
  const en = (v: any, values: readonly string[], path: string) => { if (!values.includes(v)) fail(path); };
  const num = (v: any, path: string) => { if (typeof v !== 'number' || !Number.isFinite(v) || Math.abs(v) > 1e9) fail(path); };
  const digest = (v: any, path: string, nullable = false) => { if (nullable && v === null) return; if (typeof v !== 'string' || !/^[a-f0-9]{64}$/.test(v)) fail(path); };
  const array = (v: any, path: string, limit = 256): any[] => { if (!Array.isArray(v) || v.length > limit) fail(path); return v; };
  const strings = (v: any, path: string) => { const values = array(v,path); values.forEach(v => str(v,path)); if (new Set(values).size !== values.length) fail(path); };
  const nums = (v: any, path: string) => array(v,path).forEach(v => num(v,path));
  const tensor = (v: any, path: string) => {
    record(v,['name','shape','dtype'],path);str(v.name,path);en(v.dtype,['float32','float64','unknown'],path);
    const shape = array(v.shape,path,2);
    if (shape.length !== 2 || shape.some(n => !Number.isSafeInteger(n) || n < 1 || n > 256)) fail(path);
  };
  const obs = (v: any, path: string) => {
    record(v,['layout','normalization','previousAction'],path);
    en(v.normalization,['embedded_in_onnx','adapter','none','unknown'],path);
    en(v.previousAction,['raw_policy_action','processed_action','none','unknown'],path);
    array(v.layout,path,32).forEach((f:any) => {
      record(f,['name','start','width','units'],path);str(f.name,path);str(f.units,path);
      if (!Number.isSafeInteger(f.start) || f.start < 0 || f.start > 256 || !Number.isSafeInteger(f.width) || f.width < 1 || f.width > 256) fail(path);
    });
  };
  record(input,['schemaVersion','provenance','pins','policy','model','adapter','evidence'],'/');
  en(input.schemaVersion,[POLICY_PREFLIGHT],'/schemaVersion');en(input.provenance,['verified_local_artifacts','synthetic_fixture'],'/provenance');
  record(input.pins,['policySha256','modelDigest','adapterDigest'],'/pins');
  for (const key of ['policySha256','modelDigest','adapterDigest']) digest(input.pins[key],`/pins/${key}`);
  const p = input.policy, a = input.adapter, m = input.model;
  record(p,['policyId','inspectedSha256','sourceRevision','licenseSpdx','expectedModelDigest','topology','input','output','observation','jointOrder','homeRad','actionScale','actionSemantics','requiredActuatorProfile','policyPeriodSeconds'],'/policy');
  str(p.policyId,'/policy/policyId');digest(p.inspectedSha256,'/policy/inspectedSha256',true);digest(p.expectedModelDigest,'/policy/expectedModelDigest');
  if (typeof p.sourceRevision !== 'string' || !/^[a-f0-9]{40}$/.test(p.sourceRevision)) fail('/policy/sourceRevision');
  if (p.licenseSpdx !== null) str(p.licenseSpdx,'/policy/licenseSpdx');
  if (p.requiredActuatorProfile !== null) str(p.requiredActuatorProfile,'/policy/requiredActuatorProfile');
  tensor(p.input,'/policy/input');tensor(p.output,'/policy/output');obs(p.observation,'/policy/observation');
  record(m,['modelDigest','topology','jointOrder','actuatorProfile'],'/model');digest(m.modelDigest,'/model/modelDigest');str(m.actuatorProfile,'/model/actuatorProfile');
  record(a,['adapterId','implemented','modelDigest','supportedTopology','input','output','observation','jointOrder','homeRad','actionScale','actionSemantics','actuatorProfile','physicsTimestepSeconds','policyDecimation'],'/adapter');
  str(a.adapterId,'/adapter/adapterId');if (typeof a.implemented !== 'boolean') fail('/adapter/implemented');
  digest(a.modelDigest,'/adapter/modelDigest');str(a.actuatorProfile,'/adapter/actuatorProfile');
  if (a.input !== null) tensor(a.input,'/adapter/input');if (a.output !== null) tensor(a.output,'/adapter/output');
  if (a.observation !== null) obs(a.observation,'/adapter/observation');
  for (const v of [p.topology,m.topology,a.supportedTopology]) en(v,['fixed_base_serial','floating_base'],'/topology');
  for (const [v,path] of [[p,'policy'],[a,'adapter']] as const) {
    strings(v.jointOrder,`/${path}/jointOrder`);nums(v.homeRad,`/${path}/homeRad`);num(v.actionScale,`/${path}/actionScale`);
    en(v.actionSemantics,['home_plus_scaled_position','torque','unknown'],`/${path}/actionSemantics`);
  }
  strings(m.jointOrder,'/model/jointOrder');num(p.policyPeriodSeconds,'/policy/policyPeriodSeconds');num(a.physicsTimestepSeconds,'/adapter/physicsTimestepSeconds');
  if (!Number.isSafeInteger(a.policyDecimation) || a.policyDecimation < 1 || a.policyDecimation > 1000) fail('/adapter/policyDecimation');
  record(input.evidence,[...POLICY_EVIDENCE_ROLES],'/evidence');
  for (const role of POLICY_EVIDENCE_ROLES) {
    const e = input.evidence[role];record(e,['status','kind','policySha256','modelDigest','adapterDigest','sourceSha256'],`/evidence/${role}`);
    en(e.status,['verified','missing','failed','not_run'],`/evidence/${role}/status`);
    en(e.kind,['artifact_replay','training_checkpoint','runtime_pair','operator_coverage','browser_timing','synthetic_fixture','unavailable'],`/evidence/${role}/kind`);
    for (const key of ['policySha256','modelDigest','adapterDigest','sourceSha256']) digest(e[key],`/evidence/${role}/${key}`,true);
  }
  return input;
}

/** Assess contract consistency and evidence completeness only; never grants runtime admission. */
export function assessPolicyCompatibility(raw: unknown): PolicyCompatibilityReport {
  const findings: PolicyCompatibilityFinding[] = [];
  const add = (code: string, field: string, message: string) => findings.push({code,field,message});
  let input: PolicyCompatibilityInput | undefined;
  let inputDigest: string | null = null;
  try { input = validateInput(raw);inputDigest = hash(input); }
  catch (error) { add('INPUT_INVALID','/',String(error instanceof Error ? error.message : error).slice(0,500)); }
  const evidence = input ? {} as Record<EvidenceRole, EvidenceStatus> : null;
  if (input) {
    const {pins,policy:p,model:m,adapter:a} = input;
    if (p.inspectedSha256 !== pins.policySha256) add('POLICY_BYTES_UNVERIFIED','/policy/inspectedSha256','Policy bytes are missing, changed or not bound to independently retained pins.');
    if (m.modelDigest !== pins.modelDigest || a.modelDigest !== pins.modelDigest) add('MODEL_BINDING_MISMATCH','/model/modelDigest','Model/adapter identity differs from the selected model pin.');
    if (computePolicyAdapterDigest(a) !== pins.adapterDigest) add('ADAPTER_BINDING_MISMATCH','/pins/adapterDigest','Adapter metadata changed after its pin was retained.');
    if (p.expectedModelDigest !== pins.modelDigest) add('POLICY_MODEL_MISMATCH','/policy/expectedModelDigest','Policy source targets another model; matching dimensions do not establish body compatibility.');
    if (p.licenseSpdx === null || /^(unknown|unreviewed|not_available)$/i.test(p.licenseSpdx)) add('POLICY_LICENSE_UNRECORDED','/policy/licenseSpdx','Policy license/provenance requires a separately recorded source; body/runtime licenses do not supply policy rights.');
    if (!a.implemented) add('POLICY_ADAPTER_UNAVAILABLE','/adapter/implemented','A policy-to-runtime adapter for this target has not been implemented/qualified.');
    if (p.topology !== m.topology || a.supportedTopology !== m.topology) add('TOPOLOGY_UNSUPPORTED','/model/topology','Policy/model/adapter fixed or floating-base requirements disagree.');
    for (const key of ['input','output'] as const) {
      const actual = a[key], expected = p[key];
      if (!actual) add('ADAPTER_TENSOR_CONTRACT_MISSING',`/adapter/${key}`,'No implemented observation/action tensor contract exists for this adapter.');
      else if (canonicalAssemblyString(actual) !== canonicalAssemblyString(expected)) add('TENSOR_CONTRACT_MISMATCH',`/adapter/${key}`,'Tensor name, shape or dtype differs from the policy interface.');
      if (expected.shape[0] !== 1 || expected.dtype !== 'float32') add('POLICY_INTERFACE_UNSUPPORTED',`/policy/${key}`,'This preflight supports batch-one float32 feed-forward contracts only.');
    }
    if (p.output.shape[1] !== m.jointOrder.length || p.output.shape[1] !== a.jointOrder.length) add('ACTION_DIMENSION_MISMATCH','/policy/output','The policy action width differs from the selected model/adapter joint count.');
    for (const [order,field] of [[m.jointOrder,'/model/jointOrder'],[a.jointOrder,'/adapter/jointOrder']] as const) {
      if (canonicalAssemblyString(order) !== canonicalAssemblyString(p.jointOrder)) add('JOINT_ORDER_MISMATCH',field,'Exact ordered joint identities must match; padding, truncation and reordering are unsupported.');
    }
    if (p.homeRad.length !== p.jointOrder.length || a.homeRad.length !== a.jointOrder.length || canonicalAssemblyString(p.homeRad) !== canonicalAssemblyString(a.homeRad)) add('HOME_POSE_MISMATCH','/adapter/homeRad','Use the exact source home/order, never rounded ONNX display metadata.');
    if (p.actionScale <= 0 || a.actionScale <= 0 || p.actionScale !== a.actionScale || p.actionSemantics === 'unknown' || p.actionSemantics !== a.actionSemantics) add('ACTION_MAPPING_MISMATCH','/adapter/actionSemantics','Output meaning, home offset and scale must match without implicit clamping.');
    const contiguous = (o: ObservationContract, width: number) => {
      let end=0;const names=new Set<string>();
      for (const f of o.layout) { if (f.start !== end || names.has(f.name)) return false; end+=f.width;names.add(f.name); }
      return end === width;
    };
    if (!contiguous(p.observation,p.input.shape[1])) add('OBSERVATION_LAYOUT_INVALID','/policy/observation/layout','Observation fields must cover the input vector once, without gaps, overlaps or duplicates.');
    if (!a.observation) add('OBSERVATION_CONTRACT_MISSING','/adapter/observation','No observation encoder contract is supplied for this adapter.');
    else {
      if (!a.input || !contiguous(a.observation,a.input.shape[1]) || canonicalAssemblyString(a.observation.layout) !== canonicalAssemblyString(p.observation.layout)) add('OBSERVATION_LAYOUT_MISMATCH','/adapter/observation/layout','Observation units, order and field widths must match exactly.');
      if (a.observation.normalization !== p.observation.normalization) add('NORMALIZATION_MISMATCH','/adapter/observation/normalization','Embedded normalization must not be applied a second time in an adapter.');
      if (a.observation.previousAction !== p.observation.previousAction) add('ACTION_HISTORY_MISMATCH','/adapter/observation/previousAction','Previous raw policy actions and processed/clamped controls are distinct inputs.');
    }
    if (p.observation.normalization === 'unknown' || p.observation.previousAction === 'unknown') add('OBSERVATION_SEMANTICS_UNKNOWN','/policy/observation','Normalization and action-history semantics need an explicit source contract.');
    if (!p.requiredActuatorProfile || /^(unknown|unreviewed|not_available)$/i.test(p.requiredActuatorProfile)) add('ACTUATOR_CONTRACT_UNVERIFIED','/policy/requiredActuatorProfile','The exact trained actuator/delay/friction contract has no reviewed equivalence mapping.');
    else if (m.actuatorProfile !== p.requiredActuatorProfile || a.actuatorProfile !== p.requiredActuatorProfile) add('ACTUATOR_PROFILE_MISMATCH','/model/actuatorProfile','Ideal position/torque actuators cannot stand in for an independently trained actuator model.');
    if (p.policyPeriodSeconds <= 0 || a.physicsTimestepSeconds <= 0 || a.physicsTimestepSeconds > 0.01 || Math.abs(a.physicsTimestepSeconds*a.policyDecimation-p.policyPeriodSeconds)>1e-12) add('CONTROL_CADENCE_MISMATCH','/adapter/policyDecimation','Integer physics decimation must reproduce the pinned policy period.');
    const codes: Record<EvidenceRole,string> = {artifactReplay:'ARTIFACT_REPLAY_UNVERIFIED',trainingReference:'TRAINING_REFERENCE_MISSING',runtimePair:'RUNTIME_PAIR_UNVERIFIED',operatorCoverage:'OPERATOR_COVERAGE_UNVERIFIED',browserTiming:'BROWSER_TIMING_UNVERIFIED'};
    const kinds: Record<EvidenceRole,string> = {artifactReplay:'artifact_replay',trainingReference:'training_checkpoint',runtimePair:'runtime_pair',operatorCoverage:'operator_coverage',browserTiming:'browser_timing'};
    for (const role of POLICY_EVIDENCE_ROLES) {
      const e=input.evidence[role];evidence![role]=e.status;
      if (e.status !== 'verified') add(codes[role],`/evidence/${role}`,`${role} evidence is ${e.status}; another evidence category cannot replace it.`);
      else if (e.kind !== kinds[role] && !(input.provenance === 'synthetic_fixture' && e.kind === 'synthetic_fixture')) {
        evidence![role]='failed';add('EVIDENCE_KIND_MISMATCH',`/evidence/${role}`,'Artifact replay, independent training references and runtime/browser evidence have distinct roles.');
      } else if (role === 'trainingReference' && e.sourceSha256 === input.evidence.artifactReplay.sourceSha256) {
        evidence![role]='failed';add('TRAINING_REFERENCE_NOT_INDEPENDENT',`/evidence/${role}`,'Reusing the artifact replay goldens does not supply independent checkpoint outputs.');
      } else if (e.policySha256 !== pins.policySha256 || !e.sourceSha256 ||
        (role !== 'artifactReplay' && e.modelDigest !== pins.modelDigest) ||
        (['runtimePair','operatorCoverage','browserTiming'].includes(role) && e.adapterDigest !== pins.adapterDigest)) {
        evidence![role]='failed';add('EVIDENCE_BINDING_MISMATCH',`/evidence/${role}`,'Evidence does not bind the current policy/model/adapter or lacks a source artifact pin.');
      }
    }
  }
  findings.sort((a,b)=>a.code.localeCompare(b.code,'en')||a.field.localeCompare(b.field,'en'));
  const payload = {schemaVersion:'seedcore.cw-s03.policy-preflight-report.v1' as const,checker:POLICY_PREFLIGHT,
    scope:'offline_policy_compatibility_preflight' as const,physicalAcceptance:false as const,executionAuthority:'none' as const,
    runtimeQualification:'not_granted' as const,provenance:input?.provenance ?? 'invalid_input' as const,
    decision:findings.length ? 'blocked' as const : 'contract_consistent' as const,inputDigest,pins:input?.pins ?? null,evidence,findings};
  return {...payload, reportDigest:hash(payload)};
}
