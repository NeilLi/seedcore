const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '../..');
const bytes = fs.readFileSync(path.join(root, 'apps/mini-robot-simulator/mini-physics.wasm'));
const build = require('../../apps/mini-robot-simulator/physics-build.json');
const TreeWasm = require('../../apps/mini-robot-simulator/tree-physics-wasm.js');
const C = require('../../apps/mini-robot-simulator/sim-contracts.js');

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

test('wall-clock pacing produces identical physics at 30, 60, 120 and 144 Hz', () => {
  const snapshots = [];
  for (const fps of [30, 60, 120, 144]) {
    const lab = TreeLab.createTreeLab({ wasmEngine });
    lab.isRunning = true;
    for (let i = 0; i <= fps; i++) lab.advanceFrame(i * 1000 / fps);
    assert.equal(lab.tick, 480);
    assert.equal(lab.t, 1);
    snapshots.push(lab.q);
  }
  for (const q of snapshots) assert.deepEqual(q, snapshots[0]);
});

test('pause, reset and stalls cannot inject a large physics catch-up burst', () => {
  const lab = TreeLab.createTreeLab({ wasmEngine });
  lab.isRunning = true;
  lab.advanceFrame(0);
  assert.equal(lab.advanceFrame(10_000), 48);
  assert.equal(lab.tick, 48);
  lab.isRunning = false;
  lab.advanceFrame(20_000);
  lab.isRunning = true;
  assert.equal(lab.advanceFrame(30_000), 0);
  assert.equal(lab.advanceFrame(30_000 + 1000 / 60), 8);
  lab.reset();
  assert.equal(lab.isRunning, false);
  assert.equal(lab.tick, 0);
});

test('invalid controls are rejected atomically and snapshots cannot mutate the simulation', () => {
  const lab = TreeLab.createTreeLab({ wasmEngine });
  lab.step();
  const before = lab.getDiagnostics();
  for (const change of [() => { lab.damping = NaN; }, () => { lab.gravityOn = 'false'; },
    () => { lab.target = [0]; }, () => { lab.target = [0, NaN, 0]; },
    () => { lab.motors = 1; }, () => lab.setModel('toString')]) {
    assert.throws(change);
    assert.deepEqual(lab.getDiagnostics(), before);
  }
  const target = [0.1, 0.2, 0.3];
  lab.target = target; target[0] = 42;
  lab.q[0] = 42; lab.v[0] = 42; lab.target[0] = 42;
  lab.trail[0].x = 42;
  const diag = lab.getDiagnostics(); diag.q[0] = 42; diag.target[0] = 42;
  assert.notEqual(lab.q[0], 42);
  assert.notEqual(lab.v[0], 42);
  assert.equal(lab.target[0], 0.1);
  assert.notEqual(lab.trail[0].x, 42);
  assert.throws(() => TreeLab.createTreeLab({ defaultModel: 'toString' }));
});

test('model edits pause and reset time while retaining selected controller settings', () => {
  const lab = TreeLab.createTreeLab({ wasmEngine });
  lab.isRunning = true; lab.step(); lab.damping = 0.2;
  assert.equal(lab.isRunning, false); assert.equal(lab.t, 0);
  assert.equal(lab.model.links[0].damping, 0.2);
  lab.isRunning = true; lab.step(); lab.gravityOn = false;
  assert.equal(lab.isRunning, false); assert.equal(lab.model.gravity, 0);
  lab.isRunning = true; lab.setModel('1-link');
  assert.equal(lab.isRunning, false); assert.equal(lab.target.length, 1);
});

test('state export binds the complete model, control, tick, and verified engine build', () => {
  const lab = TreeLab.createTreeLab({ wasmEngine });
  lab.motors = false; lab.gravityOn = false; lab.damping = 0.21; lab.step();
  const snapshot = lab.exportSnapshot();
  assert.equal(snapshot.source, 'local_research_simulation');
  assert.equal(snapshot.tick, 1); assert.equal(snapshot.dt, 1 / 480);
  assert.equal(snapshot.time, snapshot.tick * snapshot.dt);
  assert.equal(snapshot.engine.build.sha256, build.sha256);
  assert.equal(snapshot.model.gravity, 0);
  assert.equal(snapshot.model.links[0].damping, 0.21);
  assert.equal(snapshot.control.motors, false);
  assert.equal(snapshot.control.tauMax, 20);
  assert.deepEqual(snapshot.control.target, lab.target);
  assert.ok(snapshot.limitations.includes('current state only; no replay or checkpoint restore'));
  assert.throws(() => TreeLab.createTreeLab().exportSnapshot());
});
