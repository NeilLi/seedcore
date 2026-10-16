const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

// Load compiled TS contracts from dist
const {
  SEEDCORE_ASSEMBLY_SCHEMA_V1,
  canonicalAssemblyString,
  validateAssemblyStructure,
} = require('../../ts/packages/contracts/dist/index.js');

const FIXTURE_PATH = path.resolve(
  __dirname,
  '../../packages/component-registry/assemblies/tabletop-starter.sc-assembly.json'
);

test('Assembly contracts schema version is seedcore.assembly.v1', () => {
  assert.equal(SEEDCORE_ASSEMBLY_SCHEMA_V1, 'seedcore.assembly.v1');
});

test('Golden starter assembly validates cleanly in TypeScript/Node', () => {
  const raw = JSON.parse(fs.readFileSync(FIXTURE_PATH, 'utf-8'));
  const validated = validateAssemblyStructure(raw);

  assert.equal(validated.schema_version, 'seedcore.assembly.v1');
  assert.equal(validated.identity.assembly_id, 'tabletop.starter-arm-v1');
  assert.equal(validated.nodes.length, 5);
  assert.equal(validated.mechanical_tree.length, 4);
  assert.equal(validated.electrical_nets.length, 1);
});

test('Cross-language canonical JSON digest matches Python implementation exactly', () => {
  const raw = JSON.parse(fs.readFileSync(FIXTURE_PATH, 'utf-8'));
  const canonicalStr = canonicalAssemblyString(raw);
  const jsDigest = crypto.createHash('sha256').update(canonicalStr, 'utf-8').digest('hex');

  // Exact golden digest computed by Python
  const EXPECTED_PYTHON_DIGEST = '1a4451a2664ef4368c5f1664b74a17d9b1db2f3b81601448517fef3ebeeaac8c';
  assert.equal(jsDigest, EXPECTED_PYTHON_DIGEST);
});

test('validateAssemblyStructure rejects structural violations', () => {
  const raw = JSON.parse(fs.readFileSync(FIXTURE_PATH, 'utf-8'));

  // Corrupt schema_version
  assert.throws(() => {
    validateAssemblyStructure({ ...raw, schema_version: 'wrong.v2' });
  }, /Invalid schema_version/);

  // Missing root_node_id
  assert.throws(() => {
    validateAssemblyStructure({ ...raw, root_node_id: 'unknown_root' });
  }, /not present in nodes/);

  // Duplicate node_id
  assert.throws(() => {
    validateAssemblyStructure({ ...raw, nodes: [...raw.nodes, raw.nodes[0]] });
  }, /Duplicate node_id/);

  // Mechanical tree edge count mismatch
  assert.throws(() => {
    validateAssemblyStructure({ ...raw, mechanical_tree: raw.mechanical_tree.slice(0, 2) });
  }, /must have N-1/);

  // Self loop
  const loopTree = JSON.parse(JSON.stringify(raw.mechanical_tree));
  loopTree[0].child_node_id = loopTree[0].parent_node_id;
  assert.throws(() => {
    validateAssemblyStructure({ ...raw, mechanical_tree: loopTree });
  }, /Self-loop detected/);

  // Rigid mount with joint
  const spuriousJointTree = JSON.parse(JSON.stringify(raw.mechanical_tree));
  spuriousJointTree[0].joint = { joint_id: 'bad_j' };
  assert.throws(() => {
    validateAssemblyStructure({ ...raw, mechanical_tree: spuriousJointTree });
  }, /cannot declare a joint/);
});
