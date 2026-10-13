const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '../..');
const bytes = fs.readFileSync(path.join(root, 'apps/mini-robot-simulator/mini-physics.wasm'));
const build = require('../../apps/mini-robot-simulator/physics-build.json');
const TreeWasm = require('../../apps/mini-robot-simulator/tree-physics-wasm.js');
const C = require('../../apps/mini-robot-simulator/sim-contracts.js');
const P2 = require('../../apps/mini-robot-simulator/physics.js');

const tree = TreeWasm.create(bytes, build);

test('Tree Physics Wasm instance exports ABI 2', () => {
  assert.equal(tree.ABI, 2);
  assert.equal(tree.BACKEND, 'cpp-wasm-tree');
});

test('1-link pendulum: forward kinematics, Jacobian and potential energy gradient', () => {
  const model1 = C.Tree.compileTreeModel({
    modelId: 'pendulum-1',
    numLinks: 1,
    links: [{ name: 'link1', length: 1.2, mass: 2.5, com: 0.6, inertia: 0.3, damping: 0.1 }],
    gravity: 9.81
  });

  // FK tests
  const fk0 = tree.forward(model1, [0]);
  assert.ok(Math.abs(fk0.tip.x - 1.2) < 1e-12);
  assert.ok(Math.abs(fk0.tip.y - 0.0) < 1e-12);

  const fkHalfPi = tree.forward(model1, [Math.PI / 2]);
  assert.ok(Math.abs(fkHalfPi.tip.x - 0.0) < 1e-12);
  assert.ok(Math.abs(fkHalfPi.tip.y - 1.2) < 1e-12);

  // Jacobian vs Finite Difference
  const q0 = 0.7;
  const jac = tree.jacobian(model1, [q0]);
  const eps = 1e-6;
  const fkPlus = tree.forward(model1, [q0 + eps]);
  const fkMinus = tree.forward(model1, [q0 - eps]);
  const fdJx = (fkPlus.tip.x - fkMinus.tip.x) / (2 * eps);
  const fdJy = (fkPlus.tip.y - fkMinus.tip.y) / (2 * eps);

  assert.ok(Math.abs(jac.Jx[0] - fdJx) < 1e-6);
  assert.ok(Math.abs(jac.Jy[0] - fdJy) < 1e-6);

  // Gravity vector vs dU/dq
  const terms0 = tree.terms(model1, [q0], [0]);
  const uPlus = tree.energy(model1, [q0 + eps], [0]).potential;
  const uMinus = tree.energy(model1, [q0 - eps], [0]).potential;
  const fd_dUdq = (uPlus - uMinus) / (2 * eps);
  assert.ok(Math.abs(terms0.gravity[0] - fd_dUdq) < 1e-6);
});

test('1-link pendulum: unforced energy conservation and damping dissipation', () => {
  const modelUndamped = C.Tree.compileTreeModel({
    modelId: 'pendulum-undamped',
    numLinks: 1,
    links: [{ name: 'link1', length: 1.0, mass: 2.0, com: 0.5, inertia: 0.16666667, damping: 0.0 }],
    gravity: 9.81
  });

  let q = [0.8];
  let v = [0.0];
  let t = 0.0;
  const dt = 1 / 480;
  const e0 = tree.energy(modelUndamped, q, v).total;

  for (let tick = 0; tick < 1000; tick++) {
    const next = tree.step(modelUndamped, q, v, t, [0], dt);
    q = next.q;
    v = next.v;
    t = next.t;
  }
  const eEnd = tree.energy(modelUndamped, q, v).total;
  assert.ok(Math.abs(eEnd - e0) < 1e-4, `Energy drift too large: ${Math.abs(eEnd - e0)}`);

  // With damping, mechanical energy must strictly decrease
  const modelDamped = C.Tree.compileTreeModel({
    modelId: 'pendulum-damped',
    numLinks: 1,
    links: [{ name: 'link1', length: 1.0, mass: 2.0, com: 0.5, inertia: 0.16666667, damping: 0.5 }],
    gravity: 9.81
  });

  q = [0.8];
  v = [0.0];
  t = 0.0;
  const eDamped0 = tree.energy(modelDamped, q, v).total;
  for (let tick = 0; tick < 500; tick++) {
    const next = tree.step(modelDamped, q, v, t, [0], dt);
    q = next.q;
    v = next.v;
    t = next.t;
  }
  const eDampedEnd = tree.energy(modelDamped, q, v).total;
  assert.ok(eDampedEnd < eDamped0 * 0.5, 'Damping did not dissipate energy');
});

test('2-link exact numerical parity with SIM-2 planar double pendulum', () => {
  const l1 = 0.75, l2 = 0.6, m1 = 1.0, m2 = 0.7, g = 9.81, damping = 0.12;
  const p2Model = P2.createModel({ l1, l2, m1, m2, gravity: g, damping });

  const treeModel = C.Tree.compileTreeModel({
    modelId: 'two-link-parity',
    numLinks: 2,
    links: [
      { name: 'link1', length: l1, mass: m1, com: l1 / 2, inertia: m1 * l1 * l1 / 12, damping },
      { name: 'link2', length: l2, mass: m2, com: l2 / 2, inertia: m2 * l2 * l2 / 12, damping }
    ],
    gravity: g
  });

  const testStates = [
    { q: [0.1, 0.2], v: [0.0, 0.0] },
    { q: [15 * Math.PI / 180, 45 * Math.PI / 180], v: [0.5, -0.3] },
    { q: [-1.2, 2.1], v: [-1.5, 2.0] }
  ];

  for (const s of testStates) {
    const p2Terms = P2.terms(p2Model, s.q, s.v);
    const treeTerms = tree.terms(treeModel, s.q, s.v);

    // Check mass matrix
    assert.ok(Math.abs(treeTerms.M[0][0] - p2Terms.mass[0]) < 1e-12);
    assert.ok(Math.abs(treeTerms.M[0][1] - p2Terms.mass[1]) < 1e-12);
    assert.ok(Math.abs(treeTerms.M[1][0] - p2Terms.mass[1]) < 1e-12);
    assert.ok(Math.abs(treeTerms.M[1][1] - p2Terms.mass[2]) < 1e-12);

    // Check Coriolis
    assert.ok(Math.abs(treeTerms.coriolis[0] - p2Terms.coriolis[0]) < 1e-12);
    assert.ok(Math.abs(treeTerms.coriolis[1] - p2Terms.coriolis[1]) < 1e-12);

    // Check Gravity
    assert.ok(Math.abs(treeTerms.gravity[0] - p2Terms.gravity[0]) < 1e-12);
    assert.ok(Math.abs(treeTerms.gravity[1] - p2Terms.gravity[1]) < 1e-12);

    // Check RK4 single step
    const p2Next = P2.step(p2Model, P2.createState(s.q, s.v, 0), [0.5, -0.5], 1 / 480);
    const treeNext = tree.step(treeModel, s.q, s.v, 0, [0.5, -0.5], 1 / 480);

    assert.ok(Math.abs(treeNext.q[0] - p2Next.q[0]) < 1e-12);
    assert.ok(Math.abs(treeNext.q[1] - p2Next.q[1]) < 1e-12);
    assert.ok(Math.abs(treeNext.v[0] - p2Next.velocity[0]) < 1e-12);
    assert.ok(Math.abs(treeNext.v[1] - p2Next.velocity[1]) < 1e-12);
  }
});

test('3-link tree: mass matrix symmetry and positive definiteness', () => {
  const model3 = C.Tree.compileTreeModel({
    modelId: 'three-link-tree',
    numLinks: 3,
    links: [
      { name: 'link1', length: 0.6, mass: 1.5, com: 0.3, inertia: 0.045, damping: 0.08 },
      { name: 'link2', length: 0.5, mass: 1.0, com: 0.25, inertia: 0.021, damping: 0.08 },
      { name: 'link3', length: 0.4, mass: 0.6, com: 0.2, inertia: 0.008, damping: 0.08 }
    ],
    gravity: 9.81
  });

  const testPoses = [
    [0.0, 0.0, 0.0],
    [Math.PI / 4, -Math.PI / 3, Math.PI / 6],
    [-1.2, 0.9, -0.5]
  ];

  for (const q of testPoses) {
    const terms = tree.terms(model3, q, [0, 0, 0]);
    const M = terms.M;

    // Symmetry: M[i][j] === M[j][i]
    assert.ok(Math.abs(M[0][1] - M[1][0]) < 1e-12);
    assert.ok(Math.abs(M[0][2] - M[2][0]) < 1e-12);
    assert.ok(Math.abs(M[1][2] - M[2][1]) < 1e-12);

    // Sylvester's criterion for positive definiteness:
    // Leading principal minors must all be strictly positive
    const det1 = M[0][0];
    const det2 = M[0][0] * M[1][1] - M[0][1] * M[1][0];
    const det3 =
      M[0][0] * (M[1][1] * M[2][2] - M[1][2] * M[2][1]) -
      M[0][1] * (M[1][0] * M[2][2] - M[1][2] * M[2][0]) +
      M[0][2] * (M[1][0] * M[2][1] - M[1][1] * M[2][0]);

    assert.ok(det1 > 0, `Minor 1 not positive: ${det1}`);
    assert.ok(det2 > 0, `Minor 2 not positive: ${det2}`);
    assert.ok(det3 > 0, `Minor 3 not positive: ${det3}`);
  }
});

test('3-link tree: controlled reach converges smoothly toward target', () => {
  const model3 = C.Tree.compileTreeModel({
    modelId: 'three-link-control',
    numLinks: 3,
    links: [
      { name: 'link1', length: 0.5, mass: 1.0, com: 0.25, inertia: 0.02, damping: 0.1 },
      { name: 'link2', length: 0.4, mass: 0.8, com: 0.20, inertia: 0.01, damping: 0.1 },
      { name: 'link3', length: 0.3, mass: 0.5, com: 0.15, inertia: 0.005, damping: 0.1 }
    ],
    gravity: 9.81
  });

  const target = [0.6, -0.4, 0.3];
  let q = [0.0, 0.0, 0.0];
  let v = [0.0, 0.0, 0.0];
  let t = 0.0;
  const dt = 1 / 480;

  for (let tick = 0; tick < 1440; tick++) { // 3.0 seconds
    const stepRes = tree.stepControlled(model3, q, v, t, dt, target, 24.0, true);
    q = stepRes.q;
    v = stepRes.v;
    t = stepRes.t;
  }

  // Reached target within close tolerance
  for (let i = 0; i < 3; i++) {
    assert.ok(Math.abs(q[i] - target[i]) < 0.05, `Joint ${i} did not reach target: ${q[i]} vs ${target[i]}`);
    assert.ok(Math.abs(v[i]) < 0.1, `Joint ${i} velocity not settled: ${v[i]}`);
  }
});

test('Tree Physics Wasm rejects invalid model configurations and dimensions', () => {
  // numLinks = 0
  const invalidModel0 = { numLinks: 0, links: [], gravity: 9.81 };
  assert.throws(() => tree.terms(invalidModel0, []));

  // numLinks = 4
  const invalidModel4 = {
    numLinks: 4,
    links: [
      { length: 1, mass: 1, com: 0.5, inertia: 0.1, damping: 0.1 },
      { length: 1, mass: 1, com: 0.5, inertia: 0.1, damping: 0.1 },
      { length: 1, mass: 1, com: 0.5, inertia: 0.1, damping: 0.1 },
      { length: 1, mass: 1, com: 0.5, inertia: 0.1, damping: 0.1 }
    ],
    gravity: 9.81
  };
  assert.throws(() => tree.terms(invalidModel4, [0, 0, 0, 0]));

  // Negative mass
  const badMassModel = {
    numLinks: 1,
    links: [{ length: 1, mass: -1.0, com: 0.5, inertia: 0.1, damping: 0.1 }],
    gravity: 9.81
  };
  assert.throws(() => tree.terms(badMassModel, [0]));
});

function regressionModel(n = 1) {
  return { numLinks: n, gravity: 9.81, links: Array.from({ length: n }, () =>
    ({ length: 1, mass: 1, com: 0.5, inertia: 0.1, damping: 0 })) };
}

test('Tree Wasm rejects malformed dimensions and non-finite time/control inputs', () => {
  const model = regressionModel();
  assert.throws(() => tree.terms({ ...model, numLinks: 1.5, links: [...model.links, ...model.links] }, [0, 0]));
  for (const q of [[], [0, 0], [null], [NaN]]) assert.throws(() => tree.forward(model, q));
  assert.throws(() => tree.step(model, [0], [0], NaN, [0], 1 / 480));
  assert.throws(() => tree.stepControlled(model, [0], [0], 0, 1 / 480, [], 16, true));
  assert.throws(() => tree.stepControlled(model, [0], [0], 0, 1 / 480, [0], 16, 'false'));
});

test('Tree acceleration is invariant to uniform mass and inertia scaling', () => {
  for (const n of [1, 2, 3]) {
    const model = regressionModel(n);
    const q = [0.2, -0.3, 0.4].slice(0, n), v = [0.5, -0.2, 0.3].slice(0, n);
    const expected = tree.acceleration(model, q, v);
    for (const scale of [1e-9, 1e-6, 1]) {
      const scaled = { ...model, links: model.links.map(l => ({ ...l, mass: l.mass * scale, inertia: l.inertia * scale })) };
      const actual = tree.acceleration(scaled, q, v);
      actual.forEach((a, i) => assert.ok(Math.abs(a - expected[i]) < 1e-10));
    }
  }
});

test('Raw tree ABI rejects invalid link counts and preserves the buffer on every error', () => {
  const e = new WebAssembly.Instance(new WebAssembly.Module(bytes), { env: { sin: Math.sin, cos: Math.cos } }).exports;
  const ptr = e.mini_tree_scratch(), b = new Float64Array(e.memory.buffer, ptr, 64);
  const reset = () => {
    b.fill(0); b[0] = 1; b[1] = 1; b[4] = 1; b[7] = 0.5; b[10] = 0.1; b[16] = 9.81; b[27] = 1 / 480;
    b.fill(123, 34);
  };
  const failsUnchanged = (op, status) => {
    const before = Array.from(b);
    assert.equal(e.mini_tree_eval(op, ptr, 64), status);
    assert.deepEqual(Array.from(b), before);
  };
  for (const n of [1.5, NaN, Infinity, -Infinity, 1e100]) {
    reset(); b[0] = n; failsUnchanged(0, 1);
  }
  for (const tau of [NaN, Infinity]) {
    reset(); b[24] = tau; failsUnchanged(2, 1);
  }
  reset(); b[20] = 1e200; failsUnchanged(0, 3);
  reset(); b[17] = 1e308; b[0] = 2; b[2] = 1; b[5] = 1; b[8] = 0.5; b[11] = 0.1; b[18] = 1e308;
  failsUnchanged(3, 3);
});
