/** Retain real Wasm gesture captures for independent native and browser comparisons. */
import {mkdirSync,readFileSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {compileAssemblyToMjcf,compileGesture,createTabletopGestureExample,gestureFrameAtTick,createGestureReplay,gestureCaptureDigest,
  createMujocoModelSession,loadVerifiedMujocoModule,MujocoBoundedExecutor,assessSimulationReadiness,
} from '../../ts/packages/wasm-sim-bridge/src/index.js';
import {makeSyntheticSimulationInput,realStarterInput,studioReferenceInput} from '../../ts/tests/fixtures/cw-s01.js';

async function main() {
const out=resolve(process.argv[2]??'artifacts/robotics/cw-s04/models');mkdirSync(out,{recursive:true});
const mujoco=await loadVerifiedMujocoModule(readFileSync('ts/node_modules/@mujoco/mujoco/mujoco.wasm'));
const inputs=[...([1,2,3] as const).flatMap(n=>[false,true].map(rotated=>({name:`serial-${n}-${rotated?'rotated':'aligned'}`,input:makeSyntheticSimulationInput(n,rotated)}))),
  {name:'studio-reference',input:studioReferenceInput()}];
const cases=[];
for(const {name,input} of inputs){
  input.options.positionGain=1;const model=compileAssemblyToMjcf(input);
  const binding={assemblyDigest:model.manifest.assemblyDigest,catalogDigest:model.manifest.catalogDigest,drcDigest:model.manifest.drcDigest,
    modelDigest:model.modelDigest,revisionDigest:model.manifest.assemblyDigest,authorityEpoch:1};
  const gesture=compileGesture(createTabletopGestureExample(model,binding),model,binding);
  const session=createMujocoModelSession(mujoco,model,binding);
  try{
    const attempt={...binding,generation:1,startedMonotonicMs:1000,deadlineMonotonicMs:4000};
    const executor=new MujocoBoundedExecutor(session,{attempt,totalSubsteps:gesture.totalTicks,policyDecimation:1,maxCaptureSamples:gesture.totalTicks});
    for(let tick=0;tick<gesture.totalTicks;tick++)executor.stepSubstep(1000+(tick+1)*2,()=>({generation:1,authorityEpoch:1,modelDigest:model.modelDigest,
      proposedAtMonotonicMs:1000,expiresAtMonotonicMs:4000,targetCtrl:gestureFrameAtTick(gesture,tick+1).targetRad}));
    const summary=executor.getSummary(),samples=executor.getSamples();
    const replay=createGestureReplay(gesture,summary,samples,model,{binding,gestureDigest:gesture.gestureDigest,generation:1,captureDigest:gestureCaptureDigest(summary,samples)});
    cases.push({name,model,replay});
  }finally{session.dispose();}
}
const starter=realStarterInput();
writeFileSync(resolve(out,'cases.json'),JSON.stringify({scope:'offline_simulation_only',physicalAcceptance:false,executionAuthority:'none',cases,
  starter:{disposition:starter.drcReport.disposition,readiness:assessSimulationReadiness(starter)}},null,2)+'\n');
console.log(`CW-S04: ${cases.length} synthetic 120-step Wasm gesture captures; actual starter blocked.`);
}
main().catch(error=>{console.error(error);process.exitCode=1;});
