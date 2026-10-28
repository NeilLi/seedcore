/** Cross-language candidate fixture only; never generates a trusted review or token. */
import {mkdirSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {canonicalAssemblyString} from '../../ts/packages/contracts/src/index.js';
import {compileAssemblyToMjcf,compileGesture,createTabletopGestureExample,createCwBuildCandidate} from '../../ts/packages/wasm-sim-bridge/src/index.js';
import {studioReferenceInput} from '../../ts/tests/fixtures/cw-s01.js';

const input=studioReferenceInput();input.options.positionGain=1;
const model=compileAssemblyToMjcf(input);
const binding={revisionDigest:model.manifest.assemblyDigest,assemblyDigest:model.manifest.assemblyDigest,catalogDigest:model.manifest.catalogDigest,
  drcDigest:model.manifest.drcDigest,modelDigest:model.modelDigest,authorityEpoch:1};
const gesture=compileGesture(createTabletopGestureExample(model,binding),model,binding);
const candidate=createCwBuildCandidate(model,gesture,binding,'cw_sim://fixture/1');
const out=resolve(process.argv[2]??'artifacts/robotics/cw-g01');mkdirSync(out,{recursive:true});
writeFileSync(resolve(out,'candidate.json'),canonicalAssemblyString(candidate)+'\n');
console.log('CW-G01 exported an unsigned simulation review candidate; no registration, token or execution.');
