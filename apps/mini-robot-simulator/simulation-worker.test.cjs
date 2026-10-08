const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const P = require('./physics.js');

const C = require('./sim-contracts.js');
const { PROTOCOL } = C;
const settings = { target: [55 * Math.PI / 180, -70 * Math.PI / 180], strength: 16, mass: 0.7, motors: true, gravity: true };

// Run the actual worker entry point with browser-style structured-clone
// boundaries and a controllable timer queue, so races do not require sleeps.
function harness(options = {}) {
  const messages = [], timers = new Map();
  let timerId = 0, sequence = 0, identity = C.compile(settings);
  const context = vm.createContext({
    onmessage: null,
    ArrayBuffer, performance, WebAssembly, structuredClone,
    XMLHttpRequest: class {
      open() {} send() {
        const bytes=options.wasmBytes || fs.readFileSync(path.join(__dirname,'mini-physics.wasm'));
        this.response=bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength); this.status=options.httpStatus ?? 200;
      }
    },
    postMessage: (message, transfer = []) => {
      const copy = structuredClone(message, { transfer });
      copy.samples = copy.buffer ? C.unpack(copy.buffer, copy.sampleCount) : [];
      messages.push(copy);
    },
    setTimeout: callback => { timers.set(++timerId, callback); return timerId; },
    clearTimeout: id => timers.delete(id),
    importScripts: (...files) => files.forEach(file => vm.runInContext(fs.readFileSync(path.join(__dirname, file), 'utf8'), context)),
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, 'simulation-worker.js'), 'utf8'), context);
  return {
    messages, timers,
    recycle(message) {
      if (message.buffer?.byteLength) context.onmessage({ data: structuredClone({ protocol: PROTOCOL, type: 'recycle',
        bufferId: message.bufferId, frameSequence: message.frameSequence, buffer: message.buffer }, { transfer: [message.buffer] }) });
    },
    send(type, extra = {}) {
      let next = identity;
      if (type === 'reset' && C.validSettings(extra.settings)) next = C.compile(extra.settings);
      context.onmessage({ data: structuredClone({ protocol: PROTOCOL, type, runId: 1, revision: 0, sequence: ++sequence,
        applicationTick: 0, modelDigest: next.modelDigest, recipeDigest: next.recipeDigest, ...extra }) });
      if (type === 'reset' && messages.at(-1).type !== 'rejected') identity = next;
      return messages.at(-1);
    },
    pump(recycle = true) {
      if (recycle) for (const message of messages) this.recycle(message);
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
      if (tick % 8 === 0) {
        const actual=samples[tick/8];
        for(const key of ['q','velocity']) actual[key].forEach((value,i)=>assert.ok(Math.abs(value-state[key][i])<1e-8, `${lesson} tick ${tick} ${key}`));
        assert.ok(Math.abs(actual.time-state.time)<1e-12);
      }
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
  h.recycle(first);
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

test('a stalled UI exhausts three transfers, remains interruptible and resumes with every observation', () => {
  const h = harness(); h.send('reset', { settings }); h.send('start');
  for (let i = 0; i < C.POOL_SIZE; i++) h.pump(false);
  assert.equal(h.messages.at(-1).tick, 24);
  assert.equal(h.timers.size, 0);
  assert.equal(h.messages.at(-1).diagnostics.allocatedBuffers, 3);
  const paused = h.send('pause');
  assert.equal(paused.appliedTick, 24); assert.equal(paused.status, 'paused');
  assert.equal(paused.diagnostics.bufferWaits, 1);
  h.send('start'); assert.equal(h.timers.size, 0);
  for (const message of h.messages) h.recycle(message);
  while (h.timers.size) h.pump();
  const all = h.messages.flatMap(m => m.samples);
  assert.deepEqual(all.map(s => Math.round(s.time/C.DT)), Array.from({ length: 361 }, (_, i) => i*8));
  assert.equal(h.messages.at(-1).status, 'complete');
  assert.equal(h.messages.at(-1).diagnostics.maxInFlight, 3);
});

test('reset while all buffers are in flight reuses returns from the old run', () => {
  const h = harness(); h.send('reset', { settings }); h.send('start');
  for (let i = 0; i < 3; i++) h.pump(false);
  h.send('reset', { runId: 2, revision: 1, settings });
  h.send('start', { runId: 2, revision: 1 });
  assert.equal(h.timers.size, 0);
  h.recycle(h.messages.find(m => m.buffer));
  assert.equal(h.timers.size, 1);
  const next = h.pump(false);
  assert.equal(next.runId, 2); assert.equal(next.tick, 8);
  assert.deepEqual(next.samples.map(s => Math.round(s.time/C.DT)), [0,8]);
});

test('tick-addressed controls apply exactly inside chunks and match a direct trace', () => {
  const h = harness(), compiled = C.compile(settings);
  h.send('reset', { settings });
  const schedule = [
    { applicationTick: 9, control: { target: [0,0], strength: 2, motors: false } },
    { applicationTick: 17, control: { target: [-0.2,0.1], strength: 8, motors: true } },
    { applicationTick: 17, control: { target: [0.3,-0.2], strength: 12, motors: true } },
  ];
  for (const input of schedule) assert.equal(h.send('set-control', input).type, 'queued');
  h.send('start'); for (let i = 0; i < 5; i++) h.pump();
  const applied = h.messages.filter(m => m.type === 'applied');
  assert.deepEqual(applied.map(m => m.appliedTick), [9,17,17]);
  let state = P.createState(compiled.recipe.initial.q), control = compiled.recipe.control;
  const model = P.createModel(compiled.parameters), direct = [state];
  for (let tick = 0; tick < 40; tick++) {
    for (const input of schedule) if (input.applicationTick === tick) control = input.control;
    state = P.step(model, state, s => control.motors ? P.motor(model,s,control.target,control.strength) : [0,0], C.DT);
    if ((tick+1)%8 === 0) direct.push(state);
  }
  const actual=h.messages.flatMap(m => m.samples);
  assert.equal(actual.length,direct.length);
  actual.forEach((state,i)=>{for(const key of ['q','velocity']) state[key].forEach((v,j)=>assert.ok(Math.abs(v-direct[i][key][j])<1e-8));});
});

test('late controls, wrong identities, future admin ticks and queue overflow preserve active work', () => {
  const h = harness(), control = { target: [0,0], strength: 2, motors: false };
  h.send('reset', { settings }); h.send('start'); h.pump();
  assert.equal(h.send('set-control', { applicationTick: 7, control }).type, 'rejected');
  for (const key of ['modelDigest','recipeDigest']) {
    assert.equal(h.send('pause', { [key]: 'sha256:'+'0'.repeat(64) }).type, 'rejected');
  }
  assert.equal(h.send('pause', { applicationTick: 20 }).type, 'rejected');
  for (let i = 0; i < C.MAX_INPUTS; i++) {
    assert.equal(h.send('set-control', { applicationTick: 200+i, control }).type, 'queued');
  }
  assert.equal(h.send('set-control', { applicationTick: 300, control }).type, 'rejected');
  assert.equal(h.pump().tick, 16);
  assert.equal(h.send('reset', { runId: 2, settings, modelDigest: 'sha256:'+'0'.repeat(64) }).type, 'rejected');
  assert.equal(h.pump().tick, 24);
});

test('checkpoint restore continues exactly with same-tick queued inputs and outstanding transfers',()=>{
  const h=harness(); h.send('reset',{settings}); h.send('start');
  const controlA={target:[.4,-.3],strength:9,motors:true},controlB={target:[.2,-.7],strength:6,motors:true};
  h.send('set-control',{applicationTick:81,control:controlA});
  h.send('set-control',{applicationTick:81,control:controlB});
  for(let i=0;i<10;i++) h.pump();
  h.send('pause'); const saved=h.send('checkpoint').checkpoint;
  assert.equal(saved.tick,80); assert.equal(saved.inputs.length,2);
  const old=h.messages.length;
  h.send('start'); for(let i=10;i<360;i++) h.pump();
  const uninterrupted=h.messages.slice(old).flatMap(m=>m.samples);
  const r=harness(); r.send('reset',{settings,runId:2});
  const restored=r.send('restore',{runId:2,sequence:100,checkpoint:saved});
  assert.equal(restored.status,'paused'); assert.equal(restored.tick,80);
  r.send('start',{runId:2,sequence:101});
  for(let i=10;i<360;i++) r.pump();
  assert.deepEqual(r.messages.flatMap(m=>m.samples),uninterrupted);
  assert.equal(r.messages.at(-1).status,'complete');
});

test('checkpoint validation is atomic and binds build, recipe, tick, controls and queue',()=>{
  const h=harness();h.send('reset',{settings});h.send('step');
  const saved=h.send('checkpoint').checkpoint;
  assert.equal(h.send('restore',{checkpoint:saved}).type,'rejected');
  h.send('reset',{settings,runId:2});
  for(const change of [{buildDigest:'different'},{recipeDigest:'sha256:'+'0'.repeat(64)},
    {tick:9},{state:{...saved.state,velocity:[Infinity,0]}},{control:{...saved.control,strength:0}},
    {inputs:[{sequence:1,applicationTick:0,control:saved.control}]},{inputs:Array(33).fill({})}]) {
    assert.equal(h.send('restore',{runId:2,checkpoint:{...saved,...change}}).type,'rejected');
  }
  assert.equal(h.send('checkpoint',{runId:2}).checkpoint.tick,0);
  const restored=h.send('restore',{runId:2,checkpoint:saved});assert.equal(restored.tick,8);
  assert.equal(h.send('step',{runId:2}).tick,16);
});

test('saving while running is rejected without interrupting work; tick zero restores its first observation',()=>{
  const h=harness();h.send('reset',{settings});
  const saved=h.send('checkpoint').checkpoint;
  h.send('start');assert.equal(h.send('checkpoint').type,'rejected');assert.equal(h.pump().tick,8);
  const r=harness();r.send('reset',{settings});r.send('restore',{checkpoint:saved});
  r.send('step');assert.deepEqual(r.messages.at(-1).samples.map(s=>Math.round(s.time/C.DT)),[0,8]);
});

test('missing or corrupt Wasm fails initialization without a reference fallback',()=>{
  assert.throws(()=>harness({httpStatus:404}),/could not load/);
  const bytes=fs.readFileSync(path.join(__dirname,'mini-physics.wasm'));bytes[bytes.length-1]^=1;
  assert.throws(()=>harness({wasmBytes:bytes}),/digest mismatch/);
});
