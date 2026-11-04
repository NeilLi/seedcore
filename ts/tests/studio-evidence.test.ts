import test from 'node:test';
import assert from 'node:assert/strict';
import {canonicalAssemblyString} from '@seedcore/contracts';
import {gestureHash} from '@seedcore/wasm-sim-bridge';
import {validateEvidenceResult,type EvidenceCurrent} from '../apps/mini-studio/src/evidence.js';

function fixture(){
  const hash='a'.repeat(64),trust='b'.repeat(64);
  const context={schemaVersion:'seedcore.cw-g02.expected.v1',requestId:'attempt_1',instanceId:'c'.repeat(32),endpointId:'cw_sim://fixture/1',
    candidateDigest:hash,binding:{revisionDigest:hash,assemblyDigest:hash,catalogDigest:hash,drcDigest:hash,modelDigest:hash,authorityEpoch:1},
    sourceDigest:hash,executorDigest:hash};
  const summary={id:'attempt_1',endpointId:context.endpointId,candidateDigest:hash,binding:context.binding,modelDigest:hash,
    sourceDigest:hash,executorDigest:hash,state:'completed',reason:null,executedSubsteps:120,totalSubsteps:120};
  const report={schemaVersion:'seedcore.cw-g02.verification.v1',verified:true,disposition:'verified_completed',scope:'local_simulation_only',
    physicalAcceptance:false,executionAuthority:'none',bundleSha256:hash,expectedContextDigest:gestureHash(context),trustSnapshotDigest:trust,sourceRefs:{capture:hash}};
  const response={schemaVersion:'seedcore.cw-g02.studio-verification.v1',scope:'local_simulation_only',physicalAcceptance:false,executionAuthority:'none',
    expectedContext:context,expectedContextDigest:gestureHash(context),trustSnapshotDigest:trust,bundleSha256:hash,retainedBundleSha256:hash,
    matchesRetainedBundle:true,agreement:true,disposition:'verified_completed',summary,pythonReport:structuredClone(report),rustReport:structuredClone(report),
    pythonReportJson:canonicalAssemblyString(report),rustReportJson:canonicalAssemblyString(report),reason:'Both agree.'};
  const current:EvidenceCurrent={attempt:'attempt_1',context:structuredClone(context),trustDigest:trust,summary:structuredClone(summary)};
  return {response,current,hash};
}

test('a current completed result requires both original reports and retained bytes',()=>{
  const {response,current,hash}=fixture();assert.equal(validateEvidenceResult(response,current,hash).disposition,'verified_completed');
});
for(const change of ['instance','epoch','source','executor','trust','request','bundle','coverage','report_bytes','missing_rust','disagreement','physical'])
  test(`stale or conflicting evidence cannot restore a verified badge: ${change}`,()=>{
    const {response:r,current,hash}=fixture();
    if(change==='instance')r.expectedContext.instanceId='d'.repeat(32);
    else if(change==='epoch')r.expectedContext.binding.authorityEpoch++;
    else if(change==='source')r.summary.sourceDigest='d'.repeat(64);
    else if(change==='executor')r.summary.executorDigest='d'.repeat(64);
    else if(change==='trust')r.trustSnapshotDigest='d'.repeat(64);
    else if(change==='request')r.summary.id='other';
    else if(change==='bundle')r.retainedBundleSha256='d'.repeat(64);
    else if(change==='coverage')r.summary.executedSubsteps=7;
    else if(change==='report_bytes')r.rustReportJson='{}';
    else if(change==='missing_rust'){(r as any).rustReport=null;(r as any).rustReportJson=null;}
    else if(change==='disagreement')r.agreement=false;
    else if(change==='physical')r.physicalAcceptance=true;
    assert.throws(()=>validateEvidenceResult(r,current,hash));
  });
test('quarantine and unavailable are displayable without promoting them to verification',()=>{
  const {response:r,current,hash}=fixture();r.disposition='unavailable';r.agreement=false;(r as any).rustReport=null;(r as any).rustReportJson=null;
  assert.equal(validateEvidenceResult(r,current,hash).disposition,'unavailable');
  r.disposition='quarantine';assert.equal(validateEvidenceResult(r,current,hash).disposition,'quarantine');
});
