import assert from 'node:assert/strict';
import test from 'node:test';
import { compileAssemblyToMjcf, compileGesture, createTabletopGestureExample, createCwBuildCandidate,
  assertCwBuildCandidateCurrent, gestureHash } from '@seedcore/wasm-sim-bridge';
import { studioReferenceInput, realStarterInput } from './fixtures/cw-s01.js';

function fixture() {
  const input=studioReferenceInput(); input.options.positionGain=1;
  const model=compileAssemblyToMjcf(input);
  const binding={revisionDigest:model.manifest.assemblyDigest,assemblyDigest:model.manifest.assemblyDigest,
    catalogDigest:model.manifest.catalogDigest,drcDigest:model.manifest.drcDigest,modelDigest:model.modelDigest,authorityEpoch:1};
  const gesture=compileGesture(createTabletopGestureExample(model,binding),model,binding);
  return {model,binding,gesture};
}

test('CW-G01 candidate freezes exact compiled content and analytic bounds without authority',()=>{
  const {model,binding,gesture}=fixture(), c=createCwBuildCandidate(model,gesture,binding,'cw_sim://fixture/1');
  assert.equal(c.physicalAcceptance,false);assert.equal(c.executionAuthority,'none');
  assert.deepEqual(c.binding,binding);assert.equal(c.behavior.gestureDigest,gesture.gestureDigest);
  assert.equal(c.behavior.durationSeconds,0.24);assert.equal(c.behavior.totalTicks,120);
  assert.deepEqual(c.behavior.joints.map(j=>j.jointId),gesture.tracks.map(j=>j.jointId));
  assert.equal(c.behavior.joints[0].lowerRad,0);assert.equal(c.behavior.joints[0].upperRad,0.001);
  assert.ok(Math.abs(c.behavior.joints[0].maxVelocityRadS-0.0125)<1e-14);
  assert.equal(c.behavior.joints[0].requestedMaxVelocityRadS,0.1);
  const {candidateDigest,...payload}=c;assert.equal(candidateDigest,gestureHash(payload));
  assert.deepEqual(c,createCwBuildCandidate(model,gesture,binding,c.endpointId));
  assert.equal(Reflect.set(c.binding,'authorityEpoch',2),false);
  assert.equal(Reflect.set(c.behavior.joints[0],'lowerRad',-2),false);
  assertCwBuildCandidateCurrent(c,model,gesture,binding,c.endpointId);
});

for(const endpoint of ['', 'https://example.com', 'hal://robot/1', 'cw_sim://../robot','cw_sim://r/./1','cw_sim://r/../1',
  'cw_sim://r?q=1','cw_sim://r#1','cw_sim://r%2f1',' cw_sim://r','cw_sim://'+ 'a'.repeat(129)]) {
  test(`CW-G01 rejects non-profile endpoint ${JSON.stringify(endpoint)}`,()=>{
    const f=fixture();assert.throws(()=>createCwBuildCandidate(f.model,f.gesture,f.binding,endpoint));
  });
}
for(const key of ['revisionDigest','assemblyDigest','catalogDigest','drcDigest','modelDigest','authorityEpoch'] as const) {
  test(`CW-G01 rejects stale ${key}`,()=>{
    const f=fixture(), changed={...f.binding,[key]:key==='authorityEpoch'?2:'f'.repeat(64)};
    assert.throws(()=>createCwBuildCandidate(f.model,f.gesture,changed,'cw_sim://fixture/1'));
  });
}
test('CW-G01 endpoint and gesture edits invalidate candidates; undo/redo epochs do not reuse identity',()=>{
  const f=fixture(), endpoint='cw_sim://fixture/1', c=createCwBuildCandidate(f.model,f.gesture,f.binding,endpoint);
  assert.throws(()=>assertCwBuildCandidateCurrent(c,f.model,f.gesture,f.binding,'cw_sim://fixture/2'));
  const draft=structuredClone(f.gesture.draft);draft.name='Edited gesture';
  const changed=compileGesture(draft,f.model,f.binding);
  assert.throws(()=>assertCwBuildCandidateCurrent(c,f.model,changed,f.binding,endpoint));
  for(const authorityEpoch of [2,3]) {
    const binding={...f.binding,authorityEpoch}, draft={...f.gesture.draft,binding};
    const g=compileGesture(draft,f.model,binding);
    assert.notEqual(c.candidateDigest,createCwBuildCandidate(f.model,g,binding,endpoint).candidateDigest);
  }
});
test('CW-G01 refuses altered compiled bounds and keeps the physical starter blocked',()=>{
  const f=fixture(), altered=structuredClone(f.gesture);altered.tracks[0].segments[0].maxVelocityRadS=0;
  assert.throws(()=>createCwBuildCandidate(f.model,altered,f.binding,'cw_sim://fixture/1'));
  assert.throws(()=>compileAssemblyToMjcf(realStarterInput()));
});
