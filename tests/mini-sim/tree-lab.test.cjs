const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '../..');
const bytes = fs.readFileSync(path.join(root, 'apps/mini-robot-simulator/mini-physics.wasm'));
const build = require('../../apps/mini-robot-simulator/physics-build.json');
const TreeWasm = require('../../apps/mini-robot-simulator/tree-physics-wasm.js');
const C = require('../../apps/mini-robot-simulator/sim-contracts.js');

// Mock globalThis.MiniSimContracts for tree-lab.js
globalThis.MiniSimContracts = C;
const TreeLab = require('../../apps/mini-robot-simulator/tree-lab.js');

const wasmEngine = TreeWasm.create(bytes, build);

test('TreeLab preset models compile to valid TreeContracts descriptors', () => {
  for (const [key, preset] of Object.entries(TreeLab.PRESET_MODELS)) {
    assert.ok(C.Tree.validateTreeModel(preset.model), `Preset ${key} failed validation`);
    const compiled = C.Tree.compileTreeModel(preset.model);
    assert.equal(compiled.schema, C.Tree.SCHEMA);
    assert.equal(compiled.numLinks, preset.model.numLinks);
    assert.ok(compiled.modelDigest.startsWith('sha256:'));
    assert.equal(preset.defaultQ.length, preset.model.numLinks);
    assert.equal(preset.defaultTarget.length, preset.model.numLinks);
  }
});

test('Projector3D projects world coordinates to screen perspective correctly', () => {
  const camera = {
    yaw: 0,
    pitch: 0,
    distance: 3.0,
    target: [0, 0, 0]
  };

  const width = 800, height = 600;

  // Origin (0, 0, 0)
  const pOrig = TreeLab.Projector3D.project({ x: 0, y: 0, z: 0 }, width, height, camera);
  assert.ok(pOrig);
  assert.ok(Math.abs(pOrig.x - 400) < 1e-6);
  assert.ok(Math.abs(pOrig.y - 312) < 1e-6); // 600 * 0.52 = 312
  assert.equal(pOrig.depth, 3.0);

  // Point behind camera (depth <= 0.1) should return null
  const pBehind = TreeLab.Projector3D.project({ x: 0, y: 0, z: -4.0 }, width, height, camera);
  assert.equal(pBehind, null);

  // Point higher in +Y should project higher on screen (smaller screen y)
  const pAbove = TreeLab.Projector3D.project({ x: 0, y: 1.0, z: 0 }, width, height, camera);
  assert.ok(pAbove);
  assert.ok(pAbove.y < pOrig.y);
});

test('createTreeLab manages 1-, 2-, and 3-link models, physics stepping, and diagnostics', () => {
  const lab = TreeLab.createTreeLab({ defaultModel: '3-link', wasmEngine });

  assert.equal(lab.model.numLinks, 3);
  assert.equal(lab.q.length, 3);
  assert.equal(lab.v.length, 3);
  assert.equal(lab.t, 0);
  assert.equal(lab.trail.length, 0);

  // Step 10 ticks
  for (let i = 0; i < 10; i++) {
    const res = lab.step(1 / 480);
    assert.equal(res.q.length, 3);
    assert.equal(res.v.length, 3);
    assert.ok(res.t > 0);
    assert.equal(res.appliedTau.length, 3);
  }

  assert.equal(lab.trail.length, 10);
  const diag = lab.getDiagnostics();
  assert.ok(diag);
  assert.equal(diag.terms.M.length, 3);
  assert.equal(diag.jacobian.Jx.length, 3);
  assert.ok(Number.isFinite(diag.energy.total));

  // Switch to 1-link
  lab.setModel('1-link');
  assert.equal(lab.model.numLinks, 1);
  assert.equal(lab.q.length, 1);
  assert.equal(lab.t, 0);
  assert.equal(lab.trail.length, 0);

  lab.step(1 / 480);
  assert.equal(lab.trail.length, 1);
  assert.equal(lab.getDiagnostics().terms.M.length, 1);

  // Switch to 2-link
  lab.setModel('2-link');
  assert.equal(lab.model.numLinks, 2);
  assert.equal(lab.q.length, 2);

  // Invalid model key throws
  assert.throws(() => lab.setModel('invalid-key'));
});

test('renderScene executes canvas 2D draw operations without throwing', () => {
  const lab = TreeLab.createTreeLab({ defaultModel: '3-link', wasmEngine });
  const diag = lab.getDiagnostics();

  // Mock canvas context
  const mockCtx = {
    clearRect() {},
    beginPath() {},
    moveTo() {},
    lineTo() {},
    arc() {},
    ellipse() {},
    closePath() {},
    fill() {},
    stroke() {},
    fillText() {},
    set strokeStyle(v) {},
    set fillStyle(v) {},
    set lineWidth(v) {},
    set lineCap(v) {},
    set font(v) {},
    set textAlign(v) {}
  };

  assert.doesNotThrow(() => {
    TreeLab.renderScene(mockCtx, 800, 600, lab.camera, diag.pose, diag.targetPose, lab.trail, { gravity: true });
  });
});
