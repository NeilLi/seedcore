const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const P = require('./physics.js');

const PROTOCOL = 'seedcore.mini-lab.worker.v1';
const settings = { target: [55 * Math.PI / 180, -70 * Math.PI / 180], strength: 16, mass: 0.7, motors: true, gravity: true };

// Run the actual worker entry point with browser-style structured-clone
// boundaries and a controllable timer queue, so races do not require sleeps.
function harness() {
  const messages = [], timers = new Map();
  let timerId = 0, sequence = 0;
  const context = vm.createContext({
    onmessage: null,
    postMessage: message => messages.push(structuredClone(message)),
    setTimeout: callback => { timers.set(++timerId, callback); return timerId; },
    clearTimeout: id => timers.delete(id),
    importScripts: file => vm.runInContext(fs.readFileSync(path.join(__dirname, file), 'utf8'), context),
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, 'simulation-worker.js'), 'utf8'), context);
  return {
    messages, timers,
    send(type, extra = {}) {
      context.onmessage({ data: structuredClone({ protocol: PROTOCOL, type, runId: 1, revision: 0, sequence: ++sequence, ...extra }) });
      return messages.at(-1);
    },
    pump() {
      const entry = timers.entries().next().value;
      assert.ok(entry, 'expected one scheduled physics chunk');
      timers.delete(entry[0]); entry[1]();
      assert.ok(timers.size <= 1, 'work queue must stay bounded');
      return messages.at(-1);
    },
  };
}

for (const [lesson, changes] of [['reach', {}], ['gravity', { motors: false }], ['heavy', { mass: 1.8, strength: 5 }]]) {
  test(`${lesson}: every worker observation equals the direct physics reference`, () => {
    const h = harness(), config = { ...settings, ...changes };
    h.send('reset', { settings: config }); h.send('start');
    for (let chunk = 0; chunk < 360; chunk++) h.pump();
    assert.equal(h.messages.at(-1).status, 'complete');
    assert.equal(h.messages.at(-1).tick, 2880);
    assert.equal(h.timers.size, 0);
    const samples = h.messages.flatMap(message => message.samples || []);
    assert.equal(samples.length, 361);
    const model = P.createModel({ m2: config.mass, gravity: config.gravity ? 9.81 : 0 });
    let state = P.createState([15 * Math.PI / 180, 45 * Math.PI / 180]);
    assert.deepEqual(samples[0], state);
    for (let tick = 1; tick <= 2880; tick++) {
      state = P.step(model, state, s => config.motors ? P.motor(model, s, config.target, config.strength) : [0, 0], 1 / 480);
      if (tick % 8 === 0) assert.deepEqual(samples[tick / 8], state);
    }
  });
}

test('pause acknowledges the applied tick, cancels scheduled work, and resumes without duplicate samples', () => {
  const h = harness(); h.send('reset', { settings }); h.send('start');
  h.pump(); h.pump();
  const paused = h.send('pause');
  assert.equal(paused.status, 'paused'); assert.equal(paused.tick, 16);
  assert.equal(h.timers.size, 0);
  const resumed = h.send('start'); assert.deepEqual(resumed.samples, []);
  assert.equal(h.pump().tick, 24);
  const ticks = h.messages.flatMap(m => m.samples || []).map(s => Math.round(s.time * 480));
  assert.deepEqual(ticks, [0, 8, 16, 24]);
});

test('reset cancels the old run and old commands cannot mutate the replacement', () => {
  const h = harness(); h.send('reset', { settings }); h.send('start'); h.pump();
  const reset = h.send('reset', { runId: 2, revision: 1, settings: { ...settings, motors: false } });
  assert.equal(reset.tick, 0); assert.equal(reset.status, 'ready'); assert.equal(h.timers.size, 0);
  for (const command of ['start', 'pause', 'step']) assert.equal(h.send(command).type, 'rejected');
  assert.equal(h.send('reset', { settings }).type, 'rejected');
  assert.equal(h.send('step', { runId: 2, revision: 0 }).type, 'rejected');
  const stepped = h.send('step', { runId: 2, revision: 1 });
  assert.equal(stepped.tick, 8); assert.equal(stepped.status, 'paused');
  assert.equal(stepped.samples.length, 2);
});

test('duplicate/out-of-order commands and invalid settings leave active work intact', () => {
  const h = harness(); h.send('reset', { settings }); h.send('start');
  assert.equal(h.send('pause', { sequence: 2 }).type, 'rejected');
  assert.equal(h.send('step', { protocol: 'unknown' }).type, 'rejected');
  assert.equal(h.send('reset', { runId: 2, settings: { ...settings, target: [NaN, 0] } }).type, 'rejected');
  assert.equal(h.send('reset', { runId: 2, settings: { ...settings, motors: 'yes' } }).type, 'rejected');
  const next = h.pump(); assert.equal(next.tick, 8); assert.equal(next.runId, 1);
  assert.equal(next.status, 'running');
});

test('single-step advances eight fixed ticks and does not schedule background work', () => {
  const h = harness(); h.send('reset', { settings });
  const first = h.send('step'); assert.equal(first.tick, 8); assert.equal(first.samples.length, 2);
  const second = h.send('step'); assert.equal(second.tick, 16); assert.equal(second.samples.length, 1);
  assert.equal(h.timers.size, 0);
  // Structured-cloned earlier observations cannot be changed by later steps.
  assert.equal(Math.round(first.state.time * 480), 8);
});

test('running/completed states reject extra start/step commands without extending the run', () => {
  const h = harness(); h.send('reset', { settings }); h.send('start');
  assert.equal(h.send('start').type, 'rejected'); assert.equal(h.send('step').type, 'rejected');
  for (let chunk = 0; chunk < 360; chunk++) h.pump();
  assert.equal(h.send('start').type, 'rejected'); assert.equal(h.send('step').type, 'rejected');
  assert.equal(h.send('pause').status, 'complete'); assert.equal(h.timers.size, 0);
});
