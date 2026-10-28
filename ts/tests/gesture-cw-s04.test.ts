import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { canonicalAssemblyString } from '@seedcore/contracts';
import { compileAssemblyToMjcf, compileGesture, createTabletopGestureExample, gestureFrameAtTick, parseGestureDraft,
  assertCompiledGestureCurrent, gestureHash, createGestureReplay, inspectGestureReplay, gestureCaptureDigest,
  createMujocoModelSession, loadVerifiedMujocoModule, MujocoBoundedExecutor,
  MUJOCO_WASM_BYTES, MUJOCO_WASM_SHA256, type GestureDraft, type GestureBinding,
} from '@seedcore/wasm-sim-bridge';
import { studioReferenceInput, refreshFixture, makeSyntheticSimulationInput } from './fixtures/cw-s01.js';

function fixture(home?: number) {
  const input = studioReferenceInput(); input.options.positionGain = 1;
  if (home !== undefined) {
    input.assembly.mechanical_tree.filter(e => e.connection_type === 'articulated_joint').forEach(e => { if (e.connection_type === 'articulated_joint') e.joint.rest_angle_rad = home; });
    refreshFixture(input);
  }
  const model = compileAssemblyToMjcf(input);
  const binding: GestureBinding = {assemblyDigest:model.manifest.assemblyDigest,catalogDigest:model.manifest.catalogDigest,
    drcDigest:model.manifest.drcDigest,modelDigest:model.modelDigest,revisionDigest:model.manifest.assemblyDigest,authorityEpoch:1};
  return {input,model,binding,draft:createTabletopGestureExample(model,binding)};
}
const clone = <T>(v:T):T => structuredClone(v);

test('CW-MOM-01 deterministic immutable compilation and analytic golden extrema', () => {
  const {model,binding,draft} = fixture(); const g = compileGesture(draft,model,binding);
  assert.equal(g.totalTicks,120);
  assert.equal(g.gestureDigest,compileGesture(JSON.stringify(draft),model,binding).gestureDigest);
  const s = g.tracks[0].segments[0];
  assert.ok(Math.abs(s.maxVelocityRadS-0.0125)<1e-14);
  assert.ok(Math.abs(s.maxAccelerationRadS2-5/12)<1e-12);
  assert.equal(s.minPositionRad,draft.tracks[0].knots[0].positionRad);
  assert.equal(gestureFrameAtTick(g,60).virtualLed,'#d19b42');
  assert.ok(Math.abs(gestureFrameAtTick(g,60).targetRad[0]-draft.tracks[0].knots[1].positionRad)<1e-15);
  draft.name='External mutation'; assert.notEqual(g.draft.name,draft.name);
  assert.equal(Reflect.set(g.draft.tracks[0].knots[0],'positionRad',1),false);
  assert.throws(() => gestureFrameAtTick(g,121));
  assert.throws(() => gestureFrameAtTick(g,0.5));
});

const invalid: [string,(d: any)=>void][] = [
  ['physical claim',d=>d.physicalAcceptance=true],['authority claim',d=>d.executionAuthority='motor'],
  ['scope',d=>d.scope='hardware'],['executable interpolation',d=>d.interpolation='eval'],
  ['script',d=>d.script='fetch("https://example.com")'],['camera effect',d=>d.camera=true],['network effect',d=>d.network={}],
  ['wrong units',d=>d.tracks[0].knots[0].positionDegrees=0],['nonfinite',d=>d.tracks[0].knots[1].positionRad=NaN],
  ['unsafe integer',d=>d.durationTicks=Number.MAX_SAFE_INTEGER+1],['string tick',d=>d.tracks[0].knots[1].tick='60'],
  ['duplicate joint',d=>d.tracks[1].jointId=d.tracks[0].jointId],['wrong joint',d=>d.tracks[0].jointId='wrong_frame'],
  ['missing joint',d=>d.tracks.pop()],['initial discontinuity',d=>d.tracks[0].knots[0].positionRad+=0.01],
  ['start velocity',d=>d.tracks[0].knots[0].velocityRadS=0.1],['end velocity',d=>d.tracks[0].knots.at(-1).velocityRadS=0.1],
  ['duplicate tick',d=>d.tracks[0].knots[1].tick=0],['missing end',d=>d.tracks[0].knots.pop()],
  ['unbounded loops',d=>d.loops=0],['loop budget',d=>d.loops=2],['time stretch budget',d=>d.timeScale=2],
  ['fractional scaled tick',d=>{d.durationTicks=119;d.timeScale=0.5;}],
  ['negative acceleration bound',d=>d.tracks[0].maxAccelerationRadS2=-1],
  ['virtual LED injection',d=>d.virtualLed[0].color='url(x)'],['duplicate LED cue',d=>d.virtualLed[1].tick=0],
];
for (const [name,edit] of invalid) test(`CW-MOM-01 rejects ${name}`, () => {
  const {model,binding,draft}=fixture(); edit(draft); assert.throws(()=>compileGesture(draft,model,binding));
});
test('CW-MOM-01 strict raw parser rejects duplicate decoded keys, oversized and deeply nested input', () => {
  assert.throws(()=>parseGestureDraft('{"scope":1,"scop\\u0065":2}'),/Duplicate JSON key/);
  assert.throws(()=>parseGestureDraft(' '.repeat(65537)),/64 KiB/);
  assert.throws(()=>parseGestureDraft('['.repeat(34)+'0'+']'.repeat(34)),/nesting/);
});
test('CW-MOM-01 refuses interior velocity and acceleration overshoot despite zero endpoint derivatives', () => {
  const {model,binding,draft}=fixture();
  draft.tracks[0].maxVelocityRadS=0.01; assert.throws(()=>compileGesture(draft,model,binding),/GESTURE_BOUNDS/);
  draft.tracks[0].maxVelocityRadS=0.1; draft.tracks[0].maxAccelerationRadS2=0.2;
  assert.throws(()=>compileGesture(draft,model,binding),/GESTURE_BOUNDS/);
});
test('CW-MOM-01 refuses safe-position knots whose cubic interior exceeds the joint range', () => {
  const {model,binding,draft}=fixture(0.49);
  for (const t of draft.tracks) {
    t.maxVelocityRadS=1; t.maxAccelerationRadS2=1000;
    t.knots=[{tick:0,positionRad:0.49,velocityRadS:0},{tick:40,positionRad:0.49,velocityRadS:1},
      {tick:80,positionRad:0.49,velocityRadS:-1},{tick:120,positionRad:0.49,velocityRadS:0}];
  }
  assert.throws(()=>compileGesture(draft,model,binding),/GESTURE_BOUNDS/);
});
test('CW-MOM-01 time scaling rechecks full derivative bounds; finite loops preserve seams', () => {
  const {model,binding,draft}=fixture(); draft.durationTicks=60;
  draft.tracks.forEach(t=>t.knots.forEach(k=>k.tick/=2)); draft.virtualLed.forEach(k=>k.tick/=2);
  draft.loops=2;
  const loop=compileGesture(draft,model,binding);
  assert.deepEqual(gestureFrameAtTick(loop,0),gestureFrameAtTick(loop,60));
  draft.tracks[0].knots.at(-1)!.positionRad+=0.001; assert.throws(()=>compileGesture(draft,model,binding),/Loop seam/);
  draft.tracks[0].knots.at(-1)!.positionRad-=0.001; draft.loops=1; draft.timeScale=2;
  const slow=compileGesture(draft,model,binding); draft.timeScale=0.5;
  draft.tracks.forEach(t=>{t.maxAccelerationRadS2=2;});
  assert.throws(()=>compileGesture(draft,model,binding),/GESTURE_BOUNDS/);
  assert.equal(slow.totalTicks,120);
});
test('CW-MOM-01 model joint order is canonical and all build/revision bindings fence stale curves', () => {
  const {model,binding,draft}=fixture(); const g=compileGesture(draft,model,binding);
  draft.tracks.reverse(); assert.equal(compileGesture(draft,model,binding).gestureDigest,g.gestureDigest);
  for(const key of Object.keys(binding) as (keyof GestureBinding)[]) {
    const changed={...binding,[key]:key==='authorityEpoch'?2:'0'.repeat(64)};
    assert.throws(()=>compileGesture(draft,model,changed),/GESTURE_BINDING_MISMATCH/);
    assert.throws(()=>assertCompiledGestureCurrent(g,model,changed,g.gestureDigest));
  }
  assert.throws(()=>assertCompiledGestureCurrent({...g,totalTicks:119},model,binding,g.gestureDigest));
  const edited=clone(draft);edited.name='New behavior';assert.notEqual(compileGesture(edited,model,binding).gestureDigest,g.gestureDigest);
});
test('CW-MOM-01 rejects unqualified settings, altered model bytes and torque mode', () => {
  const {input,model,binding,draft}=fixture();
  for(const options of [{actuatorMode:'position' as const,positionGain:10},{actuatorMode:'torque' as const}]) {
    input.options=options;const other=compileAssemblyToMjcf(input);
    const b={...binding,modelDigest:other.modelDigest};const d={...draft,binding:b};assert.throws(()=>compileGesture(d,other,b));
  }
  assert.throws(()=>compileGesture(draft,{...model,xml:model.xml+' '},binding));
});
test('CW-MOM-01 compiles the declared 1-, 2-, and 3-joint synthetic subset',()=>{
  for(const count of [1,2,3] as const){
    const input=makeSyntheticSimulationInput(count);input.options.positionGain=1;const model=compileAssemblyToMjcf(input);
    const binding={assemblyDigest:model.manifest.assemblyDigest,catalogDigest:model.manifest.catalogDigest,drcDigest:model.manifest.drcDigest,
      modelDigest:model.modelDigest,revisionDigest:model.manifest.assemblyDigest,authorityEpoch:0};
    assert.equal(compileGesture(createTabletopGestureExample(model,binding),model,binding).tracks.length,count);
  }
});

const wasm = new Uint8Array(readFileSync(new URL('../node_modules/@mujoco/mujoco/mujoco.wasm',import.meta.url)));
let modulePromise: ReturnType<typeof loadVerifiedMujocoModule> | undefined;
async function execute(kind:'completed'|'stopped'|'stopped_empty'|'revoked'|'overflow'='completed') {
  const f=fixture(),g=compileGesture(f.draft,f.model,f.binding);
  const mujoco=await (modulePromise??=loadVerifiedMujocoModule(wasm,MUJOCO_WASM_BYTES,MUJOCO_WASM_SHA256));
  const session=createMujocoModelSession(mujoco,f.model,f.binding);
  const attempt={...f.binding,generation:2,startedMonotonicMs:1000,deadlineMonotonicMs:4000};
  const executor=new MujocoBoundedExecutor(session,{attempt,totalSubsteps:g.totalTicks,policyDecimation:1,maxCaptureSamples:kind==='overflow'?10:g.totalTicks});
  try {
    for(let tick=0;tick<g.totalTicks;tick++) {
      if((tick===10 && kind==='stopped') || (tick===0 && kind==='stopped_empty')){executor.stop();break;}
      if(tick===10 && kind==='revoked')executor.revoke();
      try {executor.stepSubstep(1000+(tick+1)*2,()=>({generation:2,authorityEpoch:f.binding.authorityEpoch,modelDigest:f.model.modelDigest,
        proposedAtMonotonicMs:1000,expiresAtMonotonicMs:4000,targetCtrl:gestureFrameAtTick(g,tick+1).targetRad}));}
      catch(e){if(kind==='revoked'||kind==='overflow')break;throw e;}
    }
    const summary=executor.getSummary(),samples=executor.getSamples();
    const expected={binding:f.binding,gestureDigest:g.gestureDigest,generation:2,captureDigest:gestureCaptureDigest(summary,samples)};
    const replay=createGestureReplay(g,summary,samples,f.model,expected);
    return {...f,g,summary,samples,expected,replay};
  } finally {session.dispose();}
}
test('CW-MOM-01 real pinned Wasm captures all 120 gesture controls; scrub is read-only and deterministic',async()=>{
  const run=await execute(),again=await execute();
  assert.equal(run.summary.status,'completed');assert.equal(run.summary.traceDigest,again.summary.traceDigest);
  const raw=canonicalAssemblyString(run.replay);const checked=inspectGestureReplay(raw,run.model,run.expected);
  assert.equal(checked.projection.disposition,'completed_simulation_capture');assert.equal(checked.projection.frames.length,120);
  const frame=checked.projection.frames[59];assert.equal(frame.virtualLed,'#d19b42');assert.deepEqual(frame.targetRad,run.samples[59].ctrl);
  assert.notDeepEqual(frame.targetRad,frame.observedRad); // Target commands are not measured tracking guarantees.
  assert.equal(canonicalAssemblyString(run.replay),raw);
});
for(const kind of ['stopped','revoked','overflow'] as const)test(`CW-MOM-01 retains ${kind} partial capture without claiming completion`,async()=>{
  const run=await execute(kind),checked=inspectGestureReplay(run.replay,run.model,run.expected);
  assert.notEqual(run.summary.status,'completed');assert.equal(run.summary.executedSubsteps,10);
  assert.equal(checked.projection.disposition,'interrupted_simulation_capture');assert.equal(checked.projection.capturedTicks,10);
});
test('CW-MOM-01 replay rejects wrong independent pins, missing/gapped/reordered samples and forged completion',async()=>{
  const run=await execute();
  const corruptions: ((r:any)=>void)[]=[r=>r.samples.pop(),r=>{r.samples[5].tick++;},r=>r.samples.reverse(),
    r=>r.samples[5].ctrl[0]+=0.0001,r=>r.samples[5].qpos[0]=null,r=>r.summary.scope='hardware',r=>r.summary.attempt.generation++,
    r=>r.summary.traceDigest='0'.repeat(64),r=>r.summary.finalQpos[0]+=1,r=>r.gesture.draft.name='Rewritten',r=>r.summary.capturedSamples--];
  for(const corrupt of corruptions){
    const r=clone(run.replay);corrupt(r);const {replayDigest:_,...payload}=r;r.replayDigest=gestureHash(payload);
    assert.throws(()=>inspectGestureReplay(r,run.model,run.expected));
  }
  assert.throws(()=>inspectGestureReplay(run.replay,run.model,{...run.expected,generation:3}));
  assert.throws(()=>inspectGestureReplay(run.replay,run.model,{...run.expected,binding:{...run.binding,authorityEpoch:2}}));
  const partial=await execute('stopped'),r=clone(partial.replay);r.summary.status='completed';
  const {replayDigest:_,...payload}=r;r.replayDigest=gestureHash(payload);
  assert.throws(()=>inspectGestureReplay(r,partial.model,partial.expected));
});

test('CW-MOM-01 evaluates authored knots exactly even when Horner endpoint arithmetic would round',()=>{
  const {model,binding,draft}=fixture();
  draft.tracks[0].knots[1].positionRad=0.000001234;
  draft.tracks[0].knots[1].velocityRadS=0.0001234;
  const g=compileGesture(draft,model,binding);
  for(const [i,t] of g.draft.tracks.entries())for(const knot of t.knots) {
    assert.equal(gestureFrameAtTick(g,knot.tick).targetRad[i],knot.positionRad);
  }
});

test('CW-MOM-01 rejects larger valid compiler models outside the five-body capture profile',()=>{
  const input=makeSyntheticSimulationInput(3);input.options.positionGain=1;
  const payload=input.assembly.nodes.find(n=>n.node_id==='payload')!;
  const part=JSON.parse(input.catalog.partDocuments.find(d=>d.part_id===payload.part_id)!.raw_json);
  input.assembly.nodes.push({...payload,node_id:'extra_payload'});
  input.assembly.mechanical_tree.push({edge_id:'extra_rigid',connection_type:'rigid_mount',parent_node_id:'payload',parent_port_id:'mount.top',
    child_node_id:'extra_payload',child_port_id:'mount.bottom',relative_transform:{position_m:[0,0,part.mechanical.collision.size_m[2]],quaternion_wxyz:[1,0,0,0]}});
  refreshFixture(input);
  const model=compileAssemblyToMjcf(input);
  assert.equal(model.manifest.bodies.length,6);
  const binding={modelDigest:model.modelDigest,assemblyDigest:model.manifest.assemblyDigest,catalogDigest:model.manifest.catalogDigest,
    drcDigest:model.manifest.drcDigest,revisionDigest:model.manifest.assemblyDigest,authorityEpoch:1};
  assert.throws(()=>compileGesture(createTabletopGestureExample(model,binding),model,binding),/five bodies/);
});

const resign=(r:any)=>{
  r.summary.traceDigest=gestureHash({modelDigest:r.summary.attempt.modelDigest,timestepSeconds:r.summary.timestepSeconds,policyDecimation:r.summary.policyDecimation,
    samples:r.samples.map(({monotonicMs:_wall,...physics}:any)=>physics)});
  const {replayDigest:_,...payload}=r;r.replayDigest=gestureHash(payload);
};

test('CW-MOM-01 imports reject rehashed capture, wall-time, attempt-window and summary rewrites',async()=>{
  const run=await execute();
  for(const edit of [
    (r:any)=>{r.samples[4].qpos[0]+=0.1;},
    (r:any)=>{r.samples[4].monotonicMs+=0.5;},
    (r:any)=>{r.summary.attempt.deadlineMonotonicMs+=1000;},
    (r:any)=>{r.summary.maxSubstepsPerBatch=16;},
  ]) {
    const r=clone(run.replay);edit(r);resign(r);
    assert.throws(()=>inspectGestureReplay(r,run.model,run.expected),/independently retained original attempt/);
  }
  assert.equal(inspectGestureReplay(run.replay,run.model,run.expected).projection.capturedTicks,120);
});

test('CW-MOM-01 replay requires the independent capture pin in addition to gesture/generation identity',async()=>{
  const run=await execute();const {captureDigest:_,...incomplete}=run.expected;
  assert.throws(()=>inspectGestureReplay(run.replay,run.model,incomplete as any),/independent attempt\/capture identity/);
});

test('CW-MOM-01 capture ingestion rejects inconsistent source counters, guard inventories and terminal metadata',async()=>{
  const run=await execute();
  for(const edit of [
    (r:any)=>{r.summary.policyUpdates=-1;},(r:any)=>{r.summary.batchesExecuted=999;},
    (r:any)=>{r.summary.maxSubstepsPerBatch=0;},(r:any)=>{r.summary.mutationPathsGuarded=[];},
    (r:any)=>{r.summary.errorMessage='Contradictory completed fault';},(r:any)=>{r.summary.clearedExternalMutations=1;},
    (r:any)=>{r.summary.finalCtrl=null;},(r:any)=>{r.summary.extra=true;},
    (r:any)=>{r.samples[0].extra=true;},(r:any)=>{r.summary.attempt.extra=true;},
  ]) {
    const r=clone(run.replay);edit(r);resign(r);
    const expected={...run.expected,captureDigest:gestureCaptureDigest(r.summary,r.samples)};
    assert.throws(()=>inspectGestureReplay(r,run.model,expected));
  }
  const partial=await execute('stopped');
  for(const edit of [
    (r:any)=>{r.summary.finalCtrl[0]=0.1;},
    (r:any)=>{r.summary.status='fenced';r.summary.fenceCode='UNKNOWN_REASON';},
    (r:any)=>{r.summary.status='vetoed';r.summary.fenceCode='CAPTURE_OVERFLOW';r.summary.vetoReason='REVOKED';},
  ]) {
    const r=clone(partial.replay);edit(r);resign(r);
    assert.throws(()=>inspectGestureReplay(r,partial.model,{...partial.expected,captureDigest:gestureCaptureDigest(r.summary,r.samples)}));
  }
});

test('CW-MOM-01 raw replay import rejects oversized and duplicate-key envelopes',async()=>{
  const run=await execute();
  assert.throws(()=>inspectGestureReplay(' '.repeat(262145),run.model,run.expected),/REPLAY_INVALID/);
  const raw=canonicalAssemblyString(run.replay).replace('"scope":','"scope":"offline_simulation_only","scope":');
  assert.throws(()=>inspectGestureReplay(raw,run.model,run.expected),/Duplicate JSON key/);
});

test('CW-MOM-01 an acknowledged zero-step stop retains an explicitly empty interrupted capture',async()=>{
  const run=await execute('stopped_empty');
  const checked=inspectGestureReplay(run.replay,run.model,run.expected);
  assert.equal(run.summary.status,'stopped');assert.equal(run.summary.executedSubsteps,0);
  assert.equal(checked.projection.disposition,'interrupted_simulation_capture');
  assert.deepEqual(checked.projection.frames,[]);
});
