/** Export source inputs and generated offline models for independent native checks. */
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { compileAssemblyToMjcf, assessSimulationReadiness } from '../../ts/packages/wasm-sim-bridge/src/index.js';
import { makeSyntheticSimulationInput, realStarterInput } from '../../ts/tests/fixtures/cw-s01.js';

const out=resolve(process.argv[2] ?? 'artifacts/robotics/cw-s01/models');
mkdirSync(out,{recursive:true});
const models=[];
for (const joints of [1,2,3] as const) for (const rotated of [false,true]) for (const mode of ['position','torque'] as const) {
  const input=makeSyntheticSimulationInput(joints,rotated); input.options.actuatorMode=mode;
  const model=compileAssemblyToMjcf(input), name=`serial-${joints}-${rotated?'rotated':'aligned'}-${mode}`;
  writeFileSync(resolve(out,`${name}.xml`),model.xml);
  models.push({name,input,model});
}
const starter=realStarterInput();
writeFileSync(resolve(out,'cases.json'),JSON.stringify({scope:'offline_simulation_only',physicalAcceptance:false,models,starter:{drc:starter.drcReport,readiness:assessSimulationReadiness(starter)}},null,2)+'\n');
console.log(`CW-S01 exported ${models.length} synthetic models; actual starter stays blocked.`);
