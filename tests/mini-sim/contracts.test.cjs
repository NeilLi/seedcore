const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const C = require('../../apps/mini-robot-simulator/sim-contracts.js');
const settings = { target: [55*Math.PI/180,-70*Math.PI/180], strength: 16, mass: 0.7, motors: true, gravity: true };

test('bounded SHA-256 agrees with the platform implementation including multi-block padding', () => {
  for (const input of ['', 'abc', 'a'.repeat(55), 'a'.repeat(56), 'a'.repeat(64), 'a'.repeat(8192)]) {
    assert.equal(C.sha256Ascii(input), 'sha256:'+crypto.createHash('sha256').update(input).digest('hex'));
  }
  assert.throws(() => C.sha256Ascii('é')); assert.throws(() => C.sha256Ascii('a'.repeat(8193)));
});

test('compiler identities distinguish physical changes from controller-only changes and are immutable', () => {
  const base = C.compile(settings);
  const reordered = C.compile({ gravity: true, motors: true, mass: 0.7, strength: 16, target: [...settings.target] });
  assert.deepEqual(base, reordered);
  assert.notEqual(base.modelDigest, C.compile({ ...settings, mass: 1.8 }).modelDigest);
  assert.notEqual(base.modelDigest, C.compile({ ...settings, gravity: false }).modelDigest);
  const control = C.compile({ ...settings, target: [0,0], strength: 5, motors: false });
  assert.equal(base.modelDigest, control.modelDigest); assert.notEqual(base.recipeDigest, control.recipeDigest);
  assert.equal(base.descriptor.nq, 2); assert.equal(base.descriptor.nv, 2);
  assert.equal(base.descriptor.bodies[1].inertia, settings.mass*0.6**2/12);
  assert.ok(Object.isFrozen(base.descriptor.bodies[0])); assert.ok(Object.isFrozen(base.recipe.control.target));
  settings.target[0] = 0;
  assert.notEqual(base.recipe.control.target[0], settings.target[0]);
  settings.target[0] = 55*Math.PI/180;
});

test('unsupported settings and malformed snapshot metadata fail explicitly', () => {
  for (const changes of [{ mass: NaN }, { mass: 0 }, { mass: 2.1 }, { target: [0] },
      { target: [0,Infinity] }, { strength: 0 }, { motors: 1 }, { contact: true }]) {
    assert.throws(() => C.compile({ ...settings, ...changes }));
  }
  const buffer = new ArrayBuffer(C.BUFFER_BYTES);
  C.pack(buffer, [{ q: [0,1], velocity: [2,3], time: 8*C.DT }]);
  assert.deepEqual(C.unpack(buffer,1), [{ q: [0,1], velocity: [2,3], time: 8*C.DT }]);
  for (const n of [-1,0,3,1.5]) assert.throws(() => C.unpack(buffer,n));
  new Float64Array(buffer)[0] = 7; assert.throws(() => C.unpack(buffer,1));
  assert.throws(() => C.unpack(new ArrayBuffer(1),1));
});

test('versioned golden model, recipe and command fixture stays compatible', () => {
  const golden = require('./planar-golden.json'), compiled = C.compile(settings);
  assert.deepEqual(compiled, golden.compiled);
  assert.ok(C.validEnvelope(golden.reset));
  assert.equal(C.validEnvelope({ ...golden.reset, protocol: 'seedcore.mini-lab.worker.v1' }), false);
  assert.equal(C.validEnvelope({ ...golden.reset, applicationTick: 0.5 }), false);
  assert.equal(C.validEnvelope({ ...golden.reset, arbitraryModel: {} }), false);
});

test('binary SHA-256 binds the Wasm artifact and handles non-ASCII bytes',()=>{
  const fs=require('node:fs');
  for(const input of [Uint8Array.from([0,128,255]),new Uint8Array(65536),fs.readFileSync(`${__dirname}/../../apps/mini-robot-simulator/mini-physics.wasm`)]) {
    assert.equal(C.sha256Bytes(input),'sha256:'+crypto.createHash('sha256').update(input).digest('hex'));
  }
  assert.throws(()=>C.sha256Bytes(new Uint8Array(65537)));
});
