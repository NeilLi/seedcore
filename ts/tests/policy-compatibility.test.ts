import {test} from 'node:test';
import assert from 'node:assert/strict';
import {canonicalAssemblyString} from '../packages/contracts/src/index.js';
import {sha256Hex} from '../packages/drc-solver/src/index.js';
import {assessPolicyCompatibility,computePolicyAdapterDigest,POLICY_EVIDENCE_ROLES,type PolicyCompatibilityInput} from '../packages/wasm-sim-bridge/src/policyCompatibility.js';
import {syntheticPolicyContract} from './fixtures/policy-compatibility.js';

const has=(input:unknown,code:string)=>{
  const report=assessPolicyCompatibility(input);
  assert.equal(report.decision,'blocked');assert.ok(report.findings.some(f=>f.code===code),JSON.stringify(report.findings));
  return report;
};
const rebind=(i:PolicyCompatibilityInput)=>{
  i.pins.adapterDigest=computePolicyAdapterDigest(i.adapter);
  for(const e of Object.values(i.evidence)) e.adapterDigest=i.pins.adapterDigest;
};

test('CW-S03: synthetic contract consistency stays non-authoritative, deterministic and immutable',()=>{
  const i=syntheticPolicyContract(),before=canonicalAssemblyString(i);
  const r=assessPolicyCompatibility(i),again=assessPolicyCompatibility(JSON.parse(before));
  assert.deepEqual(r,again);assert.equal(r.decision,'contract_consistent');assert.deepEqual(r.findings,[]);
  assert.equal(r.provenance,'synthetic_fixture');assert.equal(r.physicalAcceptance,false);
  assert.equal(r.executionAuthority,'none');assert.equal(r.runtimeQualification,'not_granted');
  assert.equal(canonicalAssemblyString(i),before);
  const {reportDigest,...payload}=r;assert.equal(reportDigest,sha256Hex(canonicalAssemblyString(payload)));
  assert.equal(r.inputDigest,sha256Hex(before));
  r.pins!.modelDigest='f'.repeat(64);assert.equal(canonicalAssemblyString(i),before);
});

for(const [label,mutate,code] of [
  ['changed policy hash',(i:PolicyCompatibilityInput)=>{i.policy.inspectedSha256='a'.repeat(64);},'POLICY_BYTES_UNVERIFIED'],
  ['missing policy bytes',(i:PolicyCompatibilityInput)=>{i.policy.inspectedSha256=null;},'POLICY_BYTES_UNVERIFIED'],
  ['changed selected model',(i:PolicyCompatibilityInput)=>{i.model.modelDigest='b'.repeat(64);},'MODEL_BINDING_MISMATCH'],
  ['wrong policy body despite matching dimensions',(i:PolicyCompatibilityInput)=>{i.policy.expectedModelDigest='b'.repeat(64);},'POLICY_MODEL_MISMATCH'],
  ['stale adapter pin',(i:PolicyCompatibilityInput)=>{i.adapter.actionScale=2;},'ADAPTER_BINDING_MISMATCH'],
  ['unrecorded policy license',(i:PolicyCompatibilityInput)=>{i.policy.licenseSpdx=null;},'POLICY_LICENSE_UNRECORDED'],
  ['observation-only adapter',(i:PolicyCompatibilityInput)=>{i.adapter.implemented=false;},'POLICY_ADAPTER_UNAVAILABLE'],
  ['floating body into serial runtime',(i:PolicyCompatibilityInput)=>{i.policy.topology='floating_base';},'TOPOLOGY_UNSUPPORTED'],
  ['swapped model joint identities',(i:PolicyCompatibilityInput)=>{i.model.jointOrder.reverse();},'JOINT_ORDER_MISMATCH'],
  ['swapped adapter joint identities',(i:PolicyCompatibilityInput)=>{i.adapter.jointOrder.reverse();},'JOINT_ORDER_MISMATCH'],
  ['wrong action count',(i:PolicyCompatibilityInput)=>{i.policy.output.shape[1]=14;},'ACTION_DIMENSION_MISMATCH'],
  ['rounded ONNX display home',(i:PolicyCompatibilityInput)=>{i.adapter.homeRad=[-0.087,0.349];},'HOME_POSE_MISMATCH'],
  ['changed scale',(i:PolicyCompatibilityInput)=>{i.adapter.actionScale=0.5;},'ACTION_MAPPING_MISMATCH'],
  ['torque mistaken for position',(i:PolicyCompatibilityInput)=>{i.adapter.actionSemantics='torque';},'ACTION_MAPPING_MISMATCH'],
  ['normalization twice',(i:PolicyCompatibilityInput)=>{i.adapter.observation!.normalization='adapter';},'NORMALIZATION_MISMATCH'],
  ['clamped controls as action history',(i:PolicyCompatibilityInput)=>{i.adapter.observation!.previousAction='processed_action';},'ACTION_HISTORY_MISMATCH'],
  ['changed observation units',(i:PolicyCompatibilityInput)=>{i.adapter.observation!.layout[1].units='degrees/s';},'OBSERVATION_LAYOUT_MISMATCH'],
  ['overlapping observation slices',(i:PolicyCompatibilityInput)=>{i.policy.observation.layout[1].start=1;},'OBSERVATION_LAYOUT_INVALID'],
  ['unknown observation semantics',(i:PolicyCompatibilityInput)=>{i.policy.observation.normalization='unknown';},'OBSERVATION_SEMANTICS_UNKNOWN'],
  ['missing encoder',(i:PolicyCompatibilityInput)=>{i.adapter.observation=null;},'OBSERVATION_CONTRACT_MISSING'],
  ['wrong tensor dtype',(i:PolicyCompatibilityInput)=>{i.adapter.input!.dtype='float64';},'TENSOR_CONTRACT_MISMATCH'],
  ['missing tensor binding',(i:PolicyCompatibilityInput)=>{i.adapter.input=null;},'ADAPTER_TENSOR_CONTRACT_MISSING'],
  ['unverified training actuator mapping',(i:PolicyCompatibilityInput)=>{i.policy.requiredActuatorProfile=null;},'ACTUATOR_CONTRACT_UNVERIFIED'],
  ['ideal actuator substituted for trained dynamics',(i:PolicyCompatibilityInput)=>{i.model.actuatorProfile='different_delayed_actuator';},'ACTUATOR_PROFILE_MISMATCH'],
  ['wrong physics decimation',(i:PolicyCompatibilityInput)=>{i.adapter.policyDecimation=9;},'CONTROL_CADENCE_MISMATCH'],
  ['zero physics timestep',(i:PolicyCompatibilityInput)=>{i.adapter.physicsTimestepSeconds=0;},'CONTROL_CADENCE_MISMATCH'],
] as const) test(`CW-S03 refuses ${label}`,()=>{const i=structuredClone(syntheticPolicyContract());mutate(i);has(i,code);});

for(const role of POLICY_EVIDENCE_ROLES) test(`CW-S03: ${role} evidence is separately required and bound`,()=>{
  const i=syntheticPolicyContract();i.evidence[role].status='missing';
  assert.equal(assessPolicyCompatibility(i).decision,'blocked');
  assert.ok(assessPolicyCompatibility(i).findings.some(f=>f.field===`/evidence/${role}`));
  i.evidence[role].status='verified';i.evidence[role].policySha256='a'.repeat(64);has(i,'EVIDENCE_BINDING_MISMATCH');
  i.evidence[role].policySha256=i.pins.policySha256;i.evidence[role].sourceSha256=null;has(i,'EVIDENCE_BINDING_MISMATCH');
  if(role!=='artifactReplay') {i.evidence[role].sourceSha256='c'.repeat(64);i.evidence[role].modelDigest='d'.repeat(64);has(i,'EVIDENCE_BINDING_MISMATCH');}
});

test('CW-S03: retained artifact replay cannot substitute for independent training or browser evidence',()=>{
  const i=syntheticPolicyContract();
  for(const role of ['trainingReference','runtimePair','operatorCoverage','browserTiming'] as const) i.evidence[role].status='not_run';
  const r=has(i,'TRAINING_REFERENCE_MISSING');
  assert.equal(r.evidence!.artifactReplay,'verified');assert.equal(r.evidence!.trainingReference,'not_run');
  assert.ok(r.findings.some(f=>f.code==='RUNTIME_PAIR_UNVERIFIED'));assert.ok(r.findings.some(f=>f.code==='BROWSER_TIMING_UNVERIFIED'));
});

test('CW-S03: semantic checks still reject a re-pinned incompatible adapter',()=>{
  const i=syntheticPolicyContract();i.adapter.homeRad.reverse();rebind(i);
  const r=has(i,'HOME_POSE_MISMATCH');assert.ok(!r.findings.some(f=>f.code==='ADAPTER_BINDING_MISMATCH'));
});

for(const [label,mutate] of [
  ['NaN',(i:any)=>{i.policy.homeRad[0]=NaN;}],['infinite scale',(i:any)=>{i.policy.actionScale=Infinity;}],
  ['unknown authority field',(i:any)=>{i.executionAuthority='motor';}],['duplicate joint IDs',(i:any)=>{i.model.jointOrder=['joint_a','joint_a'];}],
  ['fractional decimation',(i:any)=>{i.adapter.policyDecimation=2.5;}],['unsupported schema',(i:any)=>{i.schemaVersion='v0';}],
  ['unbounded vector',(i:any)=>{i.policy.homeRad=Array(257).fill(0);}],['oversized input',(i:any)=>{i.policy.policyId='x'.repeat(262145);}],
] as const) test(`CW-S03 input rejects ${label} without emitting authority`,()=>{
  const i=syntheticPolicyContract();mutate(i);const r=has(i,'INPUT_INVALID');
  assert.equal(r.physicalAcceptance,false);assert.equal(r.executionAuthority,'none');assert.equal(r.inputDigest,null);
});

test('CW-S03: a replay record cannot be relabeled as training evidence',()=>{
  const i=syntheticPolicyContract();
  i.evidence.trainingReference.kind='artifact_replay';has(i,'EVIDENCE_KIND_MISMATCH');
  i.evidence.trainingReference.kind='training_checkpoint';
  i.evidence.trainingReference.sourceSha256=i.evidence.artifactReplay.sourceSha256;
  has(i,'TRAINING_REFERENCE_NOT_INDEPENDENT');
  const real=syntheticPolicyContract();real.provenance='verified_local_artifacts';
  has(real,'EVIDENCE_KIND_MISMATCH'); // synthetic declarations cannot qualify real candidates
});
