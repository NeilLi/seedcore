/** Declared mathematical contracts only: no ONNX policy, training result or runtime qualification. */
import { sha256Hex } from '../../packages/drc-solver/src/index.js';
import { computePolicyAdapterDigest, POLICY_PREFLIGHT, POLICY_EVIDENCE_ROLES, type PolicyCompatibilityInput } from '../../packages/wasm-sim-bridge/src/policyCompatibility.js';

export function syntheticPolicyContract(): PolicyCompatibilityInput {
  const policySha256=sha256Hex('synthetic-contract-only-not-an-onnx-file');
  const modelDigest=sha256Hex('synthetic-two-joint-mathematical-model');
  const observation={layout:[{name:'joint_pos',start:0,width:2,units:'rad_relative_to_home'},
    {name:'joint_vel',start:2,width:2,units:'rad/s'}, {name:'actions',start:4,width:2,units:'raw_previous_policy_action'}],
    normalization:'embedded_in_onnx' as const,previousAction:'raw_policy_action' as const};
  const input={name:'obs',shape:[1,6],dtype:'float32' as const},output={name:'actions',shape:[1,2],dtype:'float32' as const};
  const adapter={adapterId:'synthetic.contract-only.v1',implemented:true,modelDigest,supportedTopology:'fixed_base_serial' as const,
    input,output,observation,jointOrder:['joint_a','joint_b'],homeRad:[-0.0873,0.3491],actionScale:1,
    actionSemantics:'home_plus_scaled_position' as const,actuatorProfile:'synthetic_ideal_position',physicsTimestepSeconds:0.002,policyDecimation:10};
  const adapterDigest=computePolicyAdapterDigest(adapter);
  return {schemaVersion:POLICY_PREFLIGHT,provenance:'synthetic_fixture',pins:{policySha256,modelDigest,adapterDigest},
    policy:{policyId:'synthetic.contract-only',inspectedSha256:policySha256,sourceRevision:'0'.repeat(40),
      licenseSpdx:'LicenseRef-SyntheticContract',expectedModelDigest:modelDigest,topology:'fixed_base_serial',input:structuredClone(input),output:structuredClone(output),observation:structuredClone(observation),
      jointOrder:['joint_a','joint_b'],homeRad:[-0.0873,0.3491],actionScale:1,actionSemantics:'home_plus_scaled_position',
      requiredActuatorProfile:'synthetic_ideal_position',policyPeriodSeconds:0.02},
    model:{modelDigest,topology:'fixed_base_serial',jointOrder:['joint_a','joint_b'],actuatorProfile:'synthetic_ideal_position'},adapter,
    evidence:Object.fromEntries(POLICY_EVIDENCE_ROLES.map(role=>[role,{status:'verified',kind:'synthetic_fixture',policySha256,modelDigest,adapterDigest,
      sourceSha256:sha256Hex(`synthetic declared ${role}; no actual training/runtime result`)}])) as PolicyCompatibilityInput['evidence']};
}
