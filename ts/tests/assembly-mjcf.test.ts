import { test } from 'node:test';
import assert from 'node:assert/strict';
import { canonicalAssemblyString, type RobotAssembly } from '../packages/contracts/src/index.js';
import { sha256Hex } from '../packages/drc-solver/src/index.js';
import {
  assessSimulationReadiness, assertCompiledModelCurrent, compileAssemblyToMjcf,
  CwS01Error, type CompilerInput, type CompilerErrorCode,
} from '../packages/wasm-sim-bridge/src/index.js';
import { makeSyntheticSimulationInput, realStarterInput, refreshFixture, rewriteFixturePart, snapshotFixture, studioReferenceInput } from './fixtures/cw-s01.js';
import { assertStudioModelCurrent } from '../apps/mini-studio/src/simulation.js';

const rejects = (input: CompilerInput, code?: CompilerErrorCode) => assert.throws(() => compileAssemblyToMjcf(input), error => error instanceof CwS01Error && (!code || error.code === code));

test('CW-S01: actual starter stays blocked; source/catalog/DRC bytes are not rewritten', () => {
  const input = realStarterInput(), before = snapshotFixture(input);
  const ready = assessSimulationReadiness(input);
  assert.equal(input.drcReport.disposition,'blocked');
  assert.equal(ready.ready,false);
  assert.deepEqual(input.drcReport.counts, { blocked: 10, conflict: 0 });
  assert.equal(ready.blockingFindings.length,9);
  assert.equal(ready.deferredPhysicalFindings.length,1);
  assert.equal(ready.blockingFindings.length,input.drcReport.findings.length-1);
  rejects(input,'DRC_NOT_READY');
  assert.equal(snapshotFixture(input),before);
});

test('CW-S01: committed Studio reference keeps the full DRC blocked and uses separate synthetic pins', () => {
  const input = studioReferenceInput(), before = snapshotFixture(input);
  assert.deepEqual(input.drcReport.findings.map(f => f.code), ['MECHANICAL_PROXY_UNQUALIFIED']);
  assert.equal(input.catalog.provenance, 'synthetic_fixture');
  assert.ok(input.assembly.nodes.every(n => n.part_id.startsWith('synthetic.cw-s01.')));
  const model = compileAssemblyToMjcf(input);
  assert.deepEqual(model, compileAssemblyToMjcf(input));
  assert.equal(model.manifest.readiness.physicalAcceptance, false);
  assert.equal(snapshotFixture(input), before);
  input.assembly.mechanical_tree.find(e => e.connection_type === 'articulated_joint')!.joint.rest_angle_rad = 0.1;
  assert.throws(() => compileAssemblyToMjcf(input), /DRC_BINDING_MISMATCH/);
  refreshFixture(input);
  assert.notEqual(compileAssemblyToMjcf(input).modelDigest, model.modelDigest);
});

test('CW-S01: Studio handoff fences every binding and rejects ABA epochs and tampered bytes', () => {
  const model = compileAssemblyToMjcf(studioReferenceInput());
  const binding = { revisionDigest: 'a'.repeat(64), authorityEpoch: 1, modelDigest: model.modelDigest,
    assemblyDigest: model.manifest.assemblyDigest, catalogDigest: model.manifest.catalogDigest, drcDigest: model.manifest.drcDigest };
  assertStudioModelCurrent(model, binding, binding);
  for (const field of ['revisionDigest', 'assemblyDigest', 'catalogDigest', 'drcDigest', 'authorityEpoch'] as const) {
    const changed = { ...binding, [field]: field === 'authorityEpoch' ? 3 : 'b'.repeat(64) };
    assert.throws(() => assertStudioModelCurrent(model, binding, changed), /Stale simulation handoff/);
  }
  const altered = structuredClone(model); altered.xml += ' ';
  assert.throws(() => assertStudioModelCurrent(altered, binding, binding), /MODEL_BINDING_MISMATCH/);
});

for (const count of [1,2,3] as const) for (const mode of ['position','torque'] as const) {
  test(`CW-S01: synthetic ${count}-joint ${mode} model is deterministic and non-authoritative`, () => {
    const input = makeSyntheticSimulationInput(count,true); input.options.actuatorMode=mode;
    const before = snapshotFixture(input), model=compileAssemblyToMjcf(input);
    assert.deepEqual(model,compileAssemblyToMjcf(input));
    assert.equal(snapshotFixture(input),before);
    assert.equal(model.manifest.readiness.ready,true);
    assert.equal(model.manifest.readiness.drcDisposition,'blocked');
    assert.equal(input.drcReport.findings[0].code,'MECHANICAL_PROXY_UNQUALIFIED');
    assert.equal(model.manifest.catalogProvenance,'synthetic_fixture');
    assert.equal(model.physicalAcceptance,false);
    assert.equal(model.executionAuthority,'none');
    assert.equal(model.manifest.joints.length,count);
    assert.equal((model.xml.match(/<joint /g)??[]).length,count);
    assert.equal((model.xml.match(mode==='position'?/<position /g:/<motor /g)??[]).length,count);
    assert.ok(!/<(?:asset|include|mesh|freejoint|plugin)\b|\bfile=/.test(model.xml));
    assert.ok(model.xml.includes('contype="0" conaffinity="0"'));
  });
}

test('CW-S01: canonical model identity binds settings, full inertials and source report', () => {
  const input=makeSyntheticSimulationInput(), original=compileAssemblyToMjcf(input);
  const expected={assemblyDigest:original.manifest.assemblyDigest,catalogDigest:original.manifest.catalogDigest,drcDigest:original.manifest.drcDigest,modelDigest:original.modelDigest};
  assertCompiledModelCurrent(original,expected);
  input.options.positionGain=20;
  const changed=compileAssemblyToMjcf(input);
  assert.notEqual(changed.modelDigest,original.modelDigest);
  assert.throws(()=>assertCompiledModelCurrent(changed,expected),/MODEL_BINDING_MISMATCH/);
  const altered=structuredClone(original); altered.xml=altered.xml.replace('mass="0.05"','mass="0.06"');
  assert.notEqual(altered.xml,original.xml);
  assert.throws(()=>assertCompiledModelCurrent(altered,expected),/MODEL_BINDING_MISMATCH/);
  for (const field of ['assemblyDigest','catalogDigest','drcDigest','modelDigest'] as const) {
    assert.throws(()=>assertCompiledModelCurrent(original,{...expected,[field]:'0'.repeat(64)}),/MODEL_BINDING_MISMATCH/);
  }
});

test('CW-S01: missing, stale and forged reports fail, including a forged pass on the real starter', () => {
  const missing=makeSyntheticSimulationInput(); missing.drcReport=undefined as any; rejects(missing,'DRC_NOT_READY');
  const stale=makeSyntheticSimulationInput(); stale.assembly.identity.name='edited'; rejects(stale,'DRC_BINDING_MISMATCH');
  for (const field of ['assemblyDigest','catalogDigest','electricalPlanDigest'] as const) {
    const input=makeSyntheticSimulationInput(); input.drcReport[field]='0'.repeat(64); rejects(input,'DRC_BINDING_MISMATCH');
  }
  const forged=realStarterInput(); forged.drcReport.disposition='pass'; forged.drcReport.findings=[]; forged.drcReport.counts={blocked:0,conflict:0};
  rejects(forged,'DRC_BINDING_MISMATCH');
  const forgedMass=makeSyntheticSimulationInput(); forgedMass.drcReport.massProperties.totalMassKg=0.0001; rejects(forgedMass,'DRC_BINDING_MISMATCH');
});

test('CW-S01: cost, electrical and dynamic findings are not whitelisted as proxy-fit concerns', () => {
  for (const mutate of [
    (part: any)=>{part.identity.bom_cost_usd=null;part.identity.cost_basis='unknown';},
    (part: any)=>{part.electrical.rating_basis='unknown';for(const k of ['min_v','max_v','continuous_ma','peak_ma','output_capacity_ma'])part.electrical[k]=null;},
  ]) {
    const input=makeSyntheticSimulationInput(); rewriteFixturePart(input,'synthetic.cw-s01.actuator',mutate);
    assert.equal(assessSimulationReadiness(input).ready,false); rejects(input,'DRC_NOT_READY');
  }
  const bad=makeSyntheticSimulationInput();
  rewriteFixturePart(bad,'synthetic.cw-s01.payload',p=>{p.mechanical.visual_mesh.origin='reviewed_asset';p.mechanical.inertia_kg_m2.izz=0.001;});
  rejects(bad,'SEMANTIC_INVALID');
});

test('CW-S01: component schemas and selected electrical pins remain mandatory', () => {
  for (const edit of [
    (p: any)=>{p.hal_and_safety.qualification='qualified';},
    (p: any)=>{p.mechanical.basis='invented';},
    (p: any)=>{p.mechanical.extra_asset='/private';},
    (p: any)=>{p.mechanical.center_of_mass_m=[0.001,0,0];},
  ]) {
    const input=makeSyntheticSimulationInput(); rewriteFixturePart(input,'synthetic.cw-s01.payload',edit);
    rejects(input,'CATALOG_INVALID');
  }
  const pin=makeSyntheticSimulationInput(); delete pin.assembly.electrical_nets[0].endpoints[0].pins; refreshFixture(pin); rejects(pin,'SEMANTIC_INVALID');
  const invalid=makeSyntheticSimulationInput(); invalid.assembly.electrical_nets[0].endpoints[0].pins=['UNDECLARED']; refreshFixture(invalid); rejects(invalid,'SEMANTIC_INVALID');
});

test('CW-S01: changing exact catalog bytes invalidates both pins and cached DRC', () => {
  const input=makeSyntheticSimulationInput(); input.catalog.partDocuments[0].raw_json+=' ';
  rejects(input,'CATALOG_INVALID');
  const digest=makeSyntheticSimulationInput(); digest.catalog.catalogSha256='0'.repeat(64); rejects(digest,'CATALOG_INVALID');
  const changed=makeSyntheticSimulationInput();
  rewriteFixturePart(changed,'synthetic.cw-s01.payload',p=>p.identity.name='Changed source');
  const current=compileAssemblyToMjcf(changed);
  assert.equal(current.manifest.catalogDigest,changed.catalog.catalogSha256);
});

test('CW-S01: branches, floating roots and undeclared/prismatic joints are refused', () => {
  const branched=makeSyntheticSimulationInput(2);
  branched.assembly.mechanical_tree[2].parent_node_id='base';
  branched.assembly.mechanical_tree[2].parent_port_id='mount.bottom';
  const joint=branched.assembly.mechanical_tree[2];
  joint.connection_type='rigid_mount'; delete (joint as any).joint;
  branched.assembly.actuator_outputs.pop(); rejects(branched,'UNSUPPORTED_SUBSET');
  const root=makeSyntheticSimulationInput(); root.assembly.nodes[0].role='other'; rejects(root,'UNSUPPORTED_SUBSET');
  const free=makeSyntheticSimulationInput(); (free.assembly as any).floating_base=true; rejects(free,'ASSEMBLY_INVALID');
  const prism=makeSyntheticSimulationInput(); (prism.assembly.mechanical_tree[1] as any).joint.kind='prismatic'; rejects(prism,'ASSEMBLY_INVALID');
  const inferred=makeSyntheticSimulationInput(); delete (inferred.assembly.mechanical_tree[1] as any).joint.axis; rejects(inferred,'ASSEMBLY_INVALID');
});

test('CW-S01: declared port/frame/limits must agree with exact component semantics', () => {
  const pose=makeSyntheticSimulationInput(); pose.assembly.mechanical_tree[0].relative_transform.position_m[0]+=0.001; refreshFixture(pose); rejects(pose,'SEMANTIC_INVALID');
  const limit=makeSyntheticSimulationInput(); (limit.assembly.mechanical_tree[1] as any).joint.limits_rad.max_rad=0.6; refreshFixture(limit); rejects(limit,'SEMANTIC_INVALID');
  const output=makeSyntheticSimulationInput();
  (output.assembly.mechanical_tree[1] as any).joint.pivot_m[0]=0.001;
  output.assembly.actuator_outputs[0].pivot_m=[0.001,0,0.02]; refreshFixture(output); rejects(output,'SEMANTIC_INVALID');
  const axis=makeSyntheticSimulationInput(); (axis.assembly.mechanical_tree[1] as any).joint.axis=[1,0,0]; rejects(axis,'ASSEMBLY_INVALID');
});

test('CW-S01: path traversal and external XML/mesh options never reach an asset loader', () => {
  const index=makeSyntheticSimulationInput();
  const data=JSON.parse(index.catalog.catalogRawJson); data.parts[0].path='parts/../../secrets.sc-part.json';
  index.catalog.catalogRawJson=JSON.stringify(data); index.catalog.catalogSha256=sha256Hex(index.catalog.catalogRawJson);
  rejects(index,'CATALOG_INVALID');
  const asset=makeSyntheticSimulationInput(); rewriteFixturePart(asset,'synthetic.cw-s01.payload',p=>p.mechanical.visual_mesh.uri='assets/../private.glb'); rejects(asset,'CATALOG_INVALID');
  const opt=makeSyntheticSimulationInput(); (opt.options as any).meshPath='../../private.glb'; rejects(opt,'OPTIONS_INVALID');
  const numeric=makeSyntheticSimulationInput(); numeric.options.positionGain=NaN; rejects(numeric,'OPTIONS_INVALID');
});

test('CW-S01: source metadata cannot inject MJCF names or arbitrary controls', () => {
  const input=makeSyntheticSimulationInput();
  input.assembly.identity.name='\"><include file="/private"/>';
  input.assembly.nodes[0].display_name='"&<script>';
  refreshFixture(input);
  const model=compileAssemblyToMjcf(input);
  assert.ok(!model.xml.includes('private') && !model.xml.includes('<include') && !model.xml.includes('script'));
  assert.notEqual(model.manifest.assemblyDigest,sha256Hex(canonicalAssemblyString(makeSyntheticSimulationInput().assembly)));
});
