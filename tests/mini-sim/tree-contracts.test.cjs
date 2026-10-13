const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const C = require('../../apps/mini-robot-simulator/sim-contracts.js');

test('TreeContracts exports are present under C.Tree', () => {
  assert.ok(C.Tree);
  assert.equal(C.Tree.SCHEMA, 'seedcore.mini-sim.tree-model.v1');
  assert.equal(C.Tree.PROTOCOL, 'seedcore.mini-lab.worker.v3');
  assert.equal(typeof C.Tree.validateTreeModel, 'function');
  assert.equal(typeof C.Tree.compileTreeModel, 'function');
  assert.equal(typeof C.Tree.forwardKinematics3D, 'function');
  assert.equal(typeof C.Tree.packTreeBuffer, 'function');
});

test('TreeContracts validates and compiles 1-link pendulum', () => {
  const model1 = {
    modelId: 'pendulum-1',
    numLinks: 1,
    links: [
      { name: 'link1', length: 1.0, mass: 2.0, com: 0.5, inertia: 0.16666667, damping: 0.1 }
    ],
    gravity: 9.81
  };
  assert.ok(C.Tree.validateTreeModel(model1));
  const compiled = C.Tree.compileTreeModel(model1);
  assert.equal(compiled.schema, C.Tree.SCHEMA);
  assert.equal(compiled.modelId, 'pendulum-1');
  assert.equal(compiled.numLinks, 1);
  assert.equal(compiled.nq, 1);
  assert.equal(compiled.nv, 1);
  assert.ok(compiled.modelDigest.startsWith('sha256:'));
  assert.ok(Object.isFrozen(compiled));
  assert.ok(Object.isFrozen(compiled.links));
  assert.ok(Object.isFrozen(compiled.links[0]));

  // FK at q = [0] (pointing along +X)
  const fk0 = C.Tree.forwardKinematics3D(compiled, [0]);
  assert.deepEqual(fk0.origin, { x: 0, y: 0, z: 0 });
  assert.equal(fk0.joints.length, 1);
  assert.ok(Math.abs(fk0.joints[0].x - 1.0) < 1e-12);
  assert.ok(Math.abs(fk0.joints[0].y - 0.0) < 1e-12);
  assert.deepEqual(fk0.tip, fk0.joints[0]);

  // FK at q = [pi/2] (pointing along +Y)
  const fk90 = C.Tree.forwardKinematics3D(compiled, [Math.PI / 2]);
  assert.ok(Math.abs(fk90.tip.x - 0.0) < 1e-12);
  assert.ok(Math.abs(fk90.tip.y - 1.0) < 1e-12);
});

test('TreeContracts validates and compiles 2-link serial arm', () => {
  const model2 = {
    modelId: 'two-link-planar',
    numLinks: 2,
    links: [
      { name: 'link1', length: 0.75, mass: 1.0, com: 0.375, inertia: 0.046875, damping: 0.12, jointLimits: [-Math.PI, Math.PI] },
      { name: 'link2', length: 0.60, mass: 0.7, com: 0.300, inertia: 0.021000, damping: 0.12, jointLimits: [-Math.PI, Math.PI] }
    ],
    gravity: 9.81
  };
  assert.ok(C.Tree.validateTreeModel(model2));
  const compiled = C.Tree.compileTreeModel(model2);
  assert.equal(compiled.numLinks, 2);

  // FK at q = [0, 0] (fully extended along +X: tip = 0.75 + 0.60 = 1.35)
  const fkStraight = C.Tree.forwardKinematics3D(compiled, [0, 0]);
  assert.ok(Math.abs(fkStraight.tip.x - 1.35) < 1e-12);
  assert.ok(Math.abs(fkStraight.tip.y - 0.0) < 1e-12);

  // FK at q = [pi/2, -pi/2] (elbow folded 90 deg back along +X)
  // joint 1 at (0, 0.75), tip at (0.60, 0.75)
  const fkFolded = C.Tree.forwardKinematics3D(compiled, [Math.PI / 2, -Math.PI / 2]);
  assert.ok(Math.abs(fkFolded.joints[0].x - 0.0) < 1e-12);
  assert.ok(Math.abs(fkFolded.joints[0].y - 0.75) < 1e-12);
  assert.ok(Math.abs(fkFolded.tip.x - 0.60) < 1e-12);
  assert.ok(Math.abs(fkFolded.tip.y - 0.75) < 1e-12);
});

test('TreeContracts validates and compiles 3-link kinematic tree', () => {
  const model3 = {
    modelId: 'three-link-robot',
    numLinks: 3,
    links: [
      { name: 'link1', length: 0.5, mass: 1.2, com: 0.25, inertia: 0.025, damping: 0.05 },
      { name: 'link2', length: 0.4, mass: 0.8, com: 0.20, inertia: 0.010, damping: 0.05 },
      { name: 'link3', length: 0.3, mass: 0.5, com: 0.15, inertia: 0.004, damping: 0.05 }
    ],
    gravity: 9.81
  };
  assert.ok(C.Tree.validateTreeModel(model3));
  const compiled = C.Tree.compileTreeModel(model3);
  assert.equal(compiled.numLinks, 3);
  assert.equal(compiled.nq, 3);
  assert.equal(compiled.nv, 3);

  // Digest is sensitive to parameter perturbation
  const model3Perturbed = {
    ...model3,
    links: [
      { ...model3.links[0], mass: 1.2001 },
      model3.links[1],
      model3.links[2]
    ]
  };
  const compiledPerturbed = C.Tree.compileTreeModel(model3Perturbed);
  assert.notEqual(compiled.modelDigest, compiledPerturbed.modelDigest);

  // Buffer packing
  const q = [0.1, 0.2, 0.3];
  const v = [0.0, 0.0, 0.0];
  const tau = [0.0, 0.0, 0.0];
  const target = [0.5, 0.5, 0.5];
  const buf = C.Tree.packTreeBuffer(compiled, q, v, 0.0, tau, 1 / 480, target, 16.0, true);
  assert.equal(buf.length, 64);
  assert.equal(buf[0], 3); // numLinks
  assert.equal(buf[1], 0.5); // l0
  assert.equal(buf[2], 0.4); // l1
  assert.equal(buf[3], 0.3); // l2
  assert.equal(buf[4], 1.2); // m0
  assert.equal(buf[16], 9.81); // g
  assert.equal(buf[17], 0.1); // q0
  assert.equal(buf[18], 0.2); // q1
  assert.equal(buf[19], 0.3); // q2
  assert.equal(buf[27], 1 / 480); // dt
  assert.equal(buf[31], 16.0); // tauMax
  assert.equal(buf[32], 1.0); // motors
});

test('TreeContracts rejects invalid tree models', () => {
  // Invalid link count
  assert.equal(C.Tree.validateTreeModel({ modelId: 'test', numLinks: 0, links: [], gravity: 9.81 }), false);
  assert.equal(C.Tree.validateTreeModel({ modelId: 'test', numLinks: 4, links: [{}, {}, {}, {}], gravity: 9.81 }), false);

  // Missing links or length mismatch
  assert.equal(C.Tree.validateTreeModel({ modelId: 'test', numLinks: 2, links: [{ name: 'l1' }], gravity: 9.81 }), false);

  // Negative mass or length
  const badLink = { name: 'l1', length: -1.0, mass: 1.0, com: 0.5, inertia: 0.1, damping: 0 };
  assert.equal(C.Tree.validateTreeModel({ modelId: 'test', numLinks: 1, links: [badLink], gravity: 9.81 }), false);

  // COM outside link length
  const badCom = { name: 'l1', length: 1.0, mass: 1.0, com: 1.5, inertia: 0.1, damping: 0 };
  assert.equal(C.Tree.validateTreeModel({ modelId: 'test', numLinks: 1, links: [badCom], gravity: 9.81 }), false);

  // Inverted joint limits
  const badLimits = { name: 'l1', length: 1.0, mass: 1.0, com: 0.5, inertia: 0.1, damping: 0, jointLimits: [1.0, -1.0] };
  assert.equal(C.Tree.validateTreeModel({ modelId: 'test', numLinks: 1, links: [badLimits], gravity: 9.81 }), false);

  // compileTreeModel throws on invalid input
  assert.throws(() => C.Tree.compileTreeModel({ modelId: 'test', numLinks: 0, links: [], gravity: 9.81 }));
});

function modelInput(overrides = {}) {
  return { modelId: 'regression', numLinks: 1, gravity: 9.81,
    links: [{ name: 'link', length: 1, mass: 1, com: 0.5, inertia: 0.1, damping: 0, jointLimits: [-1, 1] }],
    ...overrides };
}

test('Tree compiler preserves precise parameters and freezes nested joint limits', () => {
  const input = modelInput();
  input.links[0].inertia = 1e-9;
  input.links[0].jointLimits = [1, 1 + 1e-10];
  const compiled = C.Tree.compileTreeModel(input);
  assert.equal(compiled.links[0].inertia, 1e-9);
  assert.deepEqual(compiled.links[0].jointLimits, input.links[0].jointLimits);
  assert.ok(Object.isFrozen(compiled.links[0].jointLimits));
  input.links[0].jointLimits[0] = -10;
  assert.equal(compiled.links[0].jointLimits[0], 1);
  assert.notEqual(compiled.modelDigest, C.Tree.compileTreeModel(modelInput()).modelDigest);
});

test('Tree compiler hashes Unicode model identities as UTF-8 canonical JSON', () => {
  const input = modelInput({ modelId: '机器人 🦆' });
  input.links[0].name = '关节';
  const compiled = C.Tree.compileTreeModel(input);
  const canonical = { schema: C.Tree.SCHEMA, modelId: input.modelId, numLinks: input.numLinks,
    links: compiled.links, gravity: compiled.gravity, encoders: compiled.encoders };
  assert.equal(compiled.modelDigest, 'sha256:' + crypto.createHash('sha256').update(JSON.stringify(canonical)).digest('hex'));
});

test('Tree validator rejects unsupported schemas, fields, and malformed optional metadata', () => {
  const invalid = [
    modelInput({ schema: 'unknown.v2' }), modelInput({ parent: 0 }),
    ...['energy', null, ['camera'], ['energy', 'energy'], [null]].map(encoders => modelInput({ encoders })),
    ...[null, false, 0, [0], [0, NaN]].map(jointLimits => {
      const input = modelInput(); input.links[0].jointLimits = jointLimits; return input;
    }),
    ...[{ name: 'x'.repeat(33) }, { axis: [1, 0, 0] }].map(fields => {
      const input = modelInput(); Object.assign(input.links[0], fields); return input;
    })
  ];
  for (const input of invalid) {
    assert.equal(C.Tree.validateTreeModel(input), false, JSON.stringify(input));
    assert.throws(() => C.Tree.compileTreeModel(input), /Invalid TreeModel/);
  }
});

test('Tree packing and FK reject malformed state instead of silently replacing it', () => {
  const model = C.Tree.compileTreeModel(modelInput());
  for (const q of [[], [NaN], [Infinity], [null], [0, 0]]) {
    assert.throws(() => C.Tree.forwardKinematics3D(model, q));
    assert.throws(() => C.Tree.packTreeBuffer(model, q, [0], 0, [0], 1 / 480, [0], 16, true));
  }
  for (const field of [1, 2, 3, 4, 5, 6, 7]) {
    const args = [[0], [0], 0, [0], 1 / 480, [0], 16, true];
    args[field] = Array.isArray(args[field]) ? [NaN] : NaN;
    assert.throws(() => C.Tree.packTreeBuffer(model, ...args));
  }
});
