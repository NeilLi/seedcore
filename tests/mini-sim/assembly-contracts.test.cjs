const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { pathToFileURL } = require('node:url');
const root = path.resolve(__dirname, '../..');
const fixtures = path.join(root, 'tests/fixtures/assembly-v2');
const starter = JSON.parse(fs.readFileSync(path.join(root, 'packages/component-registry/assemblies/tabletop-starter.sc-assembly.json')));
const cases = JSON.parse(fs.readFileSync(path.join(fixtures, 'conformance.json'))).cases;
const vectors = JSON.parse(fs.readFileSync(path.join(fixtures, 'canonical.json'))).vectors;
let contracts;
test.before(async () => {
  contracts = await import(pathToFileURL(path.join(root, 'ts/packages/contracts/dist/index.js')).href);
});
function patched(source, operations) {
  const result = structuredClone(source);
  for (const operation of operations) {
    let target = result;
    for (const key of operation.path.slice(0, -1)) target = target[key];
    const key = operation.path.at(-1);
    if (operation.op === 'remove') {
      if (Array.isArray(target)) target.splice(key, 1);
      else delete target[key];
    } else target[key] = structuredClone(operation.value);
  }
  return result;
}
for (const fixture of cases) {
  test(`shared structure: ${fixture.name}`, () => {
    const raw = patched(starter, fixture.patch), before = structuredClone(raw);
    if (fixture.structural_valid) assert.deepEqual(contracts.validateAssemblyStructure(raw), raw);
    else assert.throws(() => contracts.validateAssemblyStructure(raw));
    assert.deepEqual(raw, before);
  });
}
for (const vector of vectors) {
  test(`independent canonical bytes: ${vector.name}`, () => {
    if (vector.reject) assert.throws(() => contracts.canonicalAssemblyString(vector.input));
    else assert.equal(contracts.canonicalAssemblyString(vector.input), vector.expected);
  });
}
test('canonicalizer rejects non-JSON, non-finite and oversized values', () => {
  let deep = [];
  for (let i = 0; i < 34; i++) deep = [deep];
  for (const value of [NaN, Infinity, -Infinity, 2n, undefined, {x: undefined}, new Date(), Array(2), deep, 'x'.repeat(262145), Array(50001).fill(0)]) {
    assert.throws(() => contracts.canonicalAssemblyString(value));
  }
});
test('validated candidate is detached from input', () => {
  const accepted = contracts.validateAssemblyStructure(starter);
  accepted.nodes[0].display_name = 'changed copy';
  assert.equal(starter.nodes[0].display_name, 'Tabletop Base');
});
test('one channel cannot drive multiple joints', () => {
  const raw = structuredClone(starter), edge = raw.mechanical_tree[3];
  Object.assign(edge, {parent_node_id:'servo_0', parent_port_id:'another.output', connection_type:'articulated_joint', joint:structuredClone(raw.mechanical_tree[2].joint)});
  edge.joint.joint_id = 'second_joint';
  assert.throws(() => contracts.validateAssemblyStructure(raw), /assigned to multiple joints/);
});
test('v2 canonical fixture hash records the reviewed draft migration', () => {
  assert.equal(contracts.SEEDCORE_ASSEMBLY_SCHEMA_V2, starter.schema_version);
  assert.equal(crypto.createHash('sha256').update(contracts.canonicalAssemblyString(starter)).digest('hex'), '2550d184c44a064c6ad6a2245a08f430f257c40ca8f3627e73eeb3fedd452acb');
});
test('live Python/JS canonical parity for every valid shared assembly', () => {
  const values = cases.filter(c => c.semantic_valid).map(c => patched(starter, c.patch));
  const python = process.env.SEEDCORE_TEST_PYTHON || (fs.existsSync(path.join(root, '.venv/bin/python')) ? path.join(root, '.venv/bin/python') : 'python3');
  const script = 'import json,sys; from seedcore.robotics.assembly import canonical_assembly_bytes; print(json.dumps([canonical_assembly_bytes(v).decode("utf-8") for v in json.load(sys.stdin)]))';
  const result = spawnSync(python, ['-c', script], {cwd:root, input:JSON.stringify(values), encoding:'utf8', env:{...process.env, PYTHONPATH:path.join(root, 'src')}});
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), values.map(v => contracts.canonicalAssemblyString(v)));
});
