/** Assemble independently pinned local inventory and candidate contracts; emit refusal reports. */
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { canonicalAssemblyString, parseStrictJson } from '../../ts/packages/contracts/src/index.js';
import { sha256Hex } from '../../ts/packages/drc-solver/src/index.js';
import {
  assessPolicyCompatibility, computePolicyAdapterDigest, compileAssemblyToMjcf,
  POLICY_PREFLIGHT, POLICY_EVIDENCE_ROLES,
  type PolicyCompatibilityInput, type PolicyContract, type PolicyAdapterContract,
  type PolicyEvidence, type PolicyModelContract,
} from '../../ts/packages/wasm-sim-bridge/src/index.js';
import { studioReferenceInput } from '../../ts/tests/fixtures/cw-s01.js';

const out=resolve(process.argv[2] ?? 'artifacts/robotics/cw-s03');
const inventory=JSON.parse(readFileSync(resolve(out,'inventory.json'),'utf8'));
if (inventory.schemaVersion !== 'seedcore.cw-s03.local-inventory.v1' || inventory.scope !== 'offline_policy_compatibility_preflight' ||
    inventory.status !== 'inspected' || inventory.physicalAcceptance !== false || inventory.executionAuthority !== 'none') throw new Error('Invalid local inventory scope');
const pinRaw=readFileSync('packages/robotics-profiles/reviews/cw-s03-preflight-inputs-v1.json','utf8');
const pin=JSON.parse(pinRaw);
if (sha256Hex(pinRaw)!==inventory.inventoryPinsSha256) throw new Error('Stale inventory pin manifest');
for (const [path,expected] of Object.entries(pin.files)) {
  const raw=readFileSync(path,'utf8');
  if (sha256Hex(raw)!==expected || inventory.files.find((f:any)=>f.path===path)?.sha256!==expected) throw new Error(`Inventory source changed: ${path}`);
}
const profile=parseStrictJson(readFileSync('packages/robotics-profiles/microduck-sim-v1.json','utf8')) as any;
if (canonicalAssemblyString(profile)!==canonicalAssemblyString(inventory.deployment)) throw new Error('Inventory/deployment mismatch');
const observed=inventory.policy.inspection;
const tensor=(port:any)=>({name:port.name,shape:port.shape,dtype:port.type==='tensor(float)' ? 'float32' as const : 'unknown' as const});
const policy: PolicyContract={
  policyId:'microduck.alpha_walking', inspectedSha256:inventory.policy.status==='verified'?inventory.policy.actualSha256:null,
  sourceRevision:profile.policy.revision,licenseSpdx:null,expectedModelDigest:profile.body_manifest_sha256,
  topology:'floating_base',
  // When cache/dependencies are absent these are source expectations, not an inspection claim.
  input:observed?tensor(observed.inputs[0]):{name:'obs',shape:[1,61],dtype:'float32'},
  output:observed?tensor(observed.outputs[0]):{name:'actions',shape:[1,14],dtype:'float32'},
  observation:{layout:profile.observation_layout,normalization:profile.policy.normalization,previousAction:'raw_policy_action'},
  jointOrder:profile.policy_joints,homeRad:profile.home_rad,actionScale:profile.action_scale,
  actionSemantics:'home_plus_scaled_position',requiredActuatorProfile:null,policyPeriodSeconds:profile.policy_period_s,
};
const missing=():PolicyEvidence=>({status:'missing',kind:'unavailable',policySha256:null,modelDigest:null,adapterDigest:null,sourceSha256:null});
function candidate(name:string, model:PolicyModelContract, adapter:PolicyAdapterContract) {
  const input:PolicyCompatibilityInput={schemaVersion:POLICY_PREFLIGHT,provenance:'verified_local_artifacts',
    pins:{policySha256:profile.policy.sha256,modelDigest:model.modelDigest,adapterDigest:computePolicyAdapterDigest(adapter)},
    policy:structuredClone(policy),model,adapter,
    evidence:Object.fromEntries(POLICY_EVIDENCE_ROLES.map(r=>[r,missing()])) as PolicyCompatibilityInput['evidence']};
  const replay=inventory.artifactReplay;
  input.evidence.artifactReplay={status:replay.status,kind:'artifact_replay',policySha256:replay.policySha256,modelDigest:null,adapterDigest:null,sourceSha256:replay.sourceSha256};
  const report=assessPolicyCompatibility(input);
  if(report.decision!=='blocked') throw new Error(`Unexpected runtime-compatible claim for ${name}`);
  return {name,input,report};
}
const nativeModel=inventory.body as PolicyModelContract;
const native:PolicyModelContract={modelDigest:nativeModel.modelDigest,topology:nativeModel.topology,jointOrder:nativeModel.jointOrder,actuatorProfile:nativeModel.actuatorProfile};
const nativeAdapter:PolicyAdapterContract={adapterId:'microduck-native-readonly-observation-v1',implemented:false,
  modelDigest:native.modelDigest,supportedTopology:'floating_base',input:policy.input,output:policy.output,
  observation:policy.observation,jointOrder:policy.jointOrder,homeRad:policy.homeRad,actionScale:1,
  actionSemantics:'home_plus_scaled_position',actuatorProfile:native.actuatorProfile,
  physicsTimestepSeconds:0.002,policyDecimation:10};
// Read-only observation support exists; a governed policy-to-actuator path does not.
const nativeCandidate=candidate('microduck-native-policy-candidate',native,nativeAdapter);
const source=studioReferenceInput();source.options.positionGain=1;
const compiled=compileAssemblyToMjcf(source);
const tabletop:PolicyModelContract={modelDigest:compiled.modelDigest,topology:'fixed_base_serial',
  jointOrder:compiled.manifest.joints.map(j=>j.jointId),actuatorProfile:'ideal_position'};
const tabletopAdapter:PolicyAdapterContract={adapterId:'seedcore.cw-s02.mujoco-wasm-st.v1',implemented:false,
  modelDigest:tabletop.modelDigest,supportedTopology:'fixed_base_serial',input:null,output:null,observation:null,
  jointOrder:tabletop.jointOrder,homeRad:compiled.manifest.joints.map(j=>j.restAngleRad),actionScale:1,
  actionSemantics:'home_plus_scaled_position',actuatorProfile:'ideal_position',physicsTimestepSeconds:0.002,policyDecimation:10};
const tabletopCandidate=candidate('microduck-policy-on-cw-s02-tabletop',tabletop,tabletopAdapter);
// Assert precise refusal reasons, not just an aggregate blocked result.
const required=['TRAINING_REFERENCE_MISSING','RUNTIME_PAIR_UNVERIFIED','POLICY_ADAPTER_UNAVAILABLE','ACTUATOR_CONTRACT_UNVERIFIED','POLICY_LICENSE_UNRECORDED','OPERATOR_COVERAGE_UNVERIFIED','BROWSER_TIMING_UNVERIFIED'];
for(const c of [nativeCandidate,tabletopCandidate]) for(const code of required) if(!c.report.findings.some(f=>f.code===code)) throw new Error(`Missing expected finding ${code}: ${c.name}`);
for(const code of ['POLICY_MODEL_MISMATCH','TOPOLOGY_UNSUPPORTED','ACTION_DIMENSION_MISMATCH','JOINT_ORDER_MISMATCH','OBSERVATION_CONTRACT_MISSING']) {
  if(!tabletopCandidate.report.findings.some(f=>f.code===code)) throw new Error(`Missing tabletop incompatibility ${code}`);
}
const payload={schemaVersion:'seedcore.cw-s03.compatibility-matrix.v1',scope:'offline_policy_compatibility_preflight',
  physicalAcceptance:false,executionAuthority:'none',runtimeQualification:'not_granted',
  inventoryDigest:sha256Hex(canonicalAssemblyString(inventory)),artifactReplay:inventory.artifactReplay,
  cases:[nativeCandidate,tabletopCandidate],
  nextPackage:'CW-S04 bounded tabletop gesture; policy execution remains separately gated'};
mkdirSync(out,{recursive:true});
writeFileSync(resolve(out,'compatibility.json'),canonicalAssemblyString({...payload,matrixDigest:sha256Hex(canonicalAssemblyString(payload))})+'\n');
console.log(`CW-S03: ${payload.cases.length} real candidates BLOCKED; artifact replay=${inventory.artifactReplay.status}; training/runtime/browser evidence remains separate.`);
