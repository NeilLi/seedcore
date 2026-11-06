/** Reproducible draft archive fixtures; no execution, secrets or external assets. */
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { canonicalAssemblyString } from '../../ts/packages/contracts/src/index.js';
import { createBuildPack } from '../../ts/packages/wasm-sim-bridge/src/index.js';
import { realStarterInput, studioReferenceInput } from '../../ts/tests/fixtures/cw-s01.js';

const out=resolve(process.argv[2]??'artifacts/robotics/cw-e01');mkdirSync(out,{recursive:true});
const cases=[];
for(const [name,input] of [['starter',realStarterInput()],['synthetic-reference',studioReferenceInput()]] as const){
  input.options.positionGain=1;
  const pack=createBuildPack(input),again=createBuildPack(structuredClone(input));
  if(Buffer.compare(pack.bytes,again.bytes)!==0)throw Error('Nondeterministic build pack');
  writeFileSync(resolve(out,`${name}.zip`),pack.bytes);
  writeFileSync(resolve(out,`${name}.manifest.json`),canonicalAssemblyString(pack.manifest)+'\n');
  writeFileSync(resolve(out,`${name}.input.json`),canonicalAssemblyString(input)+'\n');
  cases.push({name,path:`${name}.zip`,bytes:pack.bytes.length,sha256:createHash('sha256').update(pack.bytes).digest('hex'),
    files:pack.files.length,modelIncluded:pack.manifest.model.included,unpricedPartCount:pack.manifest.bom.unpricedPartCount});
}
writeFileSync(resolve(out,'export-verification.json'),JSON.stringify({schemaVersion:'seedcore.cw-e01.export-verification.v1',
  status:'checks_passed',scope:'offline_design_only',physicalAcceptance:false,executionAuthority:'none',deterministic:true,cases},null,2)+'\n');
console.log('CW-E01 exported deterministic draft starter/reference archives; no hardware or runtime authority.');
