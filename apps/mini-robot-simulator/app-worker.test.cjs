const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const P = require('./physics.js');
const C = require('./sim-contracts.js');

// Exercise the real UI's asynchronous worker boundary without rendering a DOM.
function page() {
  const elements = new Map(), workers = [], timers = new Map(), exports = [];
  const context2d = new Proxy({}, { get: () => () => {} });
  const element = id => {
    if (!elements.has(id)) elements.set(id, { value: '', checked: false, disabled: false, textContent: '',
      listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; },
      getContext: () => context2d });
    return elements.get(id);
  };
  for (const [id, value] of Object.entries({shoulder:'55', elbow:'-70', strength:'16', mass:'0.7', lesson:'reach'})) element(id).value = value;
  element('motors').checked = element('gravity').checked = true;
  const document = { hidden: false, listeners: {}, getElementById: element,
    querySelectorAll: () => [], querySelector: () => null,
    createElement: () => ({ click() {} }),
    addEventListener(type, fn) { this.listeners[type] = fn; } };
  class Worker {
    constructor() { this.commands = []; this.frameSequence = 0; workers.push(this); }
    postMessage(message, transfer = []) { this.commands.push(structuredClone(message, { transfer })); }
    terminate() { this.terminated = true; }
    reply(command, extra = {}) {
      const message = { ...command, type: 'update', status: 'ready', tick: 0, frameSequence: ++this.frameSequence,
        appliedTick: 0, sampleCount: 0, state: P.createState([Math.PI / 12, Math.PI / 4]), ...extra };
      if (extra.samples?.length) {
        message.buffer = new ArrayBuffer(C.BUFFER_BYTES); message.bufferId = 0;
        message.sampleCount = extra.samples.length; C.pack(message.buffer, extra.samples);
      }
      delete message.samples;
      this.frameSequence = Math.max(this.frameSequence, message.frameSequence);
      this.onmessage({ data: message });
    }
  }
  let timerId = 0;
  vm.runInNewContext(fs.readFileSync(`${__dirname}/app.js`, 'utf8'), {
    MiniRobotPhysics: P, MiniSimContracts: C, MiniPhysicsBuild: require('./physics-build.json'), ArrayBuffer, document, Worker, location: { protocol: 'http:' },
    Blob, URL: { createObjectURL: blob => { exports.push(blob); return 'blob:test'; }, revokeObjectURL() {} },
    ResizeObserver: class { observe() {} }, requestAnimationFrame() {},
    setTimeout: fn => { timers.set(++timerId, fn); return timerId; },
    clearTimeout: id => timers.delete(id),
  });
  return { element, document, workers, timers, exports,
    click: id => element(id).listeners.click(),
    latest: () => workers.at(-1).commands.filter(c => c.type !== 'recycle').at(-1) };
}

test('queued snapshots from replaced runs and model revisions cannot change the view', () => {
  const p = page(), worker = p.workers[0], old = p.latest(); worker.reply(old);
  p.element('mass').value = '1.8'; p.element('mass').listeners.input();
  const current = p.latest(); worker.reply(current);
  worker.reply(old, { tick: 2880, status: 'complete', state: P.createState([0, 0], [0, 0], 6) });
  worker.reply({ ...current, revision: old.revision }, { status: 'running' });
  assert.equal(p.element('run-status').textContent, 'Ready');
  assert.equal(p.element('time').textContent, '0.00 s');
  assert.equal(p.element('replay').disabled, true);
});

test('pause retains in-flight observations and waits for its own acknowledgement', () => {
  const p = page(), worker = p.workers[0]; worker.reply(p.latest());
  p.click('run'); const start = p.latest();
  worker.reply(start, { status: 'running', samples: [P.createState()] });
  p.click('pause'); const pause = p.latest();
  const state = P.createState([0, 0], [0, 0], 1 / 60);
  worker.reply(start, { status: 'running', tick: 8, state, samples: [state] });
  assert.equal(p.element('run-status').textContent, 'Updating…');
  assert.equal(p.element('download').disabled, true);
  worker.reply(pause, { status: 'paused', tick: 8, state });
  assert.equal(p.element('run-status').textContent, 'Paused');
  assert.equal(p.element('replay').disabled, false);
});

test('failed acknowledgement terminates the worker and reset creates a fresh one', () => {
  const p = page(), failed = p.workers[0];
  [...p.timers.values()][0]();
  assert.equal(failed.terminated, true);
  assert.equal(p.element('run-status').textContent, 'Stopped · error');
  p.click('reset');
  assert.equal(p.workers.length, 2);
  p.workers[1].reply(p.latest());
  assert.equal(p.element('run-status').textContent, 'Ready');
});

test('hiding the page while start is pending sends pause when start is acknowledged', () => {
  const p = page(), worker = p.workers[0]; worker.reply(p.latest());
  p.click('run'); const start = p.latest();
  p.document.hidden = true; p.document.listeners.visibilitychange();
  worker.reply(start, { status: 'running' });
  assert.equal(p.latest().type, 'pause');
  worker.reply(p.latest(), { status: 'paused' });
  assert.equal(p.element('run-status').textContent, 'Paused');
});

test('obsolete transfers are returned and wrong digests cannot acknowledge the active command', () => {
  const p = page(), worker = p.workers[0], old = p.latest(); worker.reply(old);
  p.click('reset'); const current = p.latest();
  worker.reply(old, { tick: 8, samples: [P.createState(),P.createState([0,0],[0,0],C.DT*8)] });
  assert.equal(worker.commands.at(-1).type, 'recycle');
  assert.equal(p.element('run-status').textContent, 'Updating…');
  worker.reply(old, { buffer: new ArrayBuffer(1), sampleCount: 99 });
  assert.equal(p.element('run-status').textContent, 'Updating…');
  worker.reply({ ...current, modelDigest: 'sha256:'+'0'.repeat(64) });
  assert.equal(p.element('run-status').textContent, 'Updating…');
  worker.reply(current); assert.equal(p.element('run-status').textContent, 'Ready');
});

test('completion with missing observations stops visibly and cannot be replayed or saved', () => {
  const p = page(), worker = p.workers[0]; worker.reply(p.latest());
  p.click('run'); const start = p.latest(); worker.reply(start, { status: 'running' });
  worker.reply(start, { status: 'complete', tick: C.TOTAL_TICKS, state: P.createState([0,0],[0,0],6) });
  assert.equal(p.element('run-status').textContent, 'Stopped · error');
  assert.equal(p.element('download').disabled, true); assert.equal(p.element('replay').disabled, true);
});

test('duplicate frame sequences cannot append the same observations twice', () => {
  const p = page(), worker = p.workers[0]; worker.reply(p.latest());
  p.click('run'); const start = p.latest(); worker.reply(start, { status: 'running' });
  const extra = { status: 'running', tick: 8, frameSequence: 10,
    state: P.createState([0,0],[0,0],8*C.DT), samples: [P.createState(), P.createState([0,0],[0,0],8*C.DT)] };
  worker.reply(start, extra); worker.reply(start, extra);
  worker.reply(start, { ...extra, samples: [], buffer: new ArrayBuffer(1), sampleCount: 99 });
  p.click('pause'); worker.reply(p.latest(), { status: 'paused', tick: 8, state: extra.state });
  assert.equal(p.element('run-status').textContent, 'Paused');
});

test('events from a terminated connection do not fail a recovered worker', () => {
  const p = page(), old = p.workers[0]; [...p.timers.values()][0]();
  p.click('reset'); p.workers[1].reply(p.latest()); old.onerror(); old.onmessageerror();
  assert.equal(p.element('run-status').textContent, 'Ready');
});

test('v2 export after starting recorded replay preserves completeness and compiled identity', async () => {
  const p = page(), worker = p.workers[0]; worker.reply(p.latest());
  p.click('run'); const start = p.latest(); worker.reply(start, { status: 'running' });
  for (let tick = 8; tick <= C.TOTAL_TICKS; tick += 8) {
    const state = P.createState([0,0],[0,0],tick*C.DT);
    worker.reply(start, { status: tick === C.TOTAL_TICKS ? 'complete' : 'running', tick, state,
      samples: tick === 8 ? [P.createState(),state] : [state], diagnostics: { allocatedBuffers: 3 } });
  }
  p.click('replay');
  // Download is disabled while replay is active; pause makes its recorded
  // samples available while the display time has moved back to tick zero.
  p.click('pause'); p.click('download');
  const record = JSON.parse(await p.exports[0].text());
  assert.equal(record.schema, 'seedcore.mini-lab.experiment.v2');
  assert.equal(record.complete, true); assert.equal(record.samples.length,361);
  assert.equal(record.source,'local_research_simulation');
  assert.equal(record.compiled.recipe.modelDigest,record.compiled.modelDigest);
  assert.equal(record.diagnostics.allocatedBuffers,3);
  assert.ok(record.limitations.includes('recorded playback only, not a resumable checkpoint'));
});

test('saved progress uses the acknowledged worker checkpoint and keeps experiment exports separate',async()=>{
  const p=page(),w=p.workers[0];w.reply(p.latest());p.click('step');
  const state=P.createState([.2,.3],[.4,.5],8*C.DT),initial=P.createState([Math.PI/12,Math.PI/4]);
  w.reply(p.latest(),{tick:8,status:'paused',state,samples:[initial,state]});
  p.click('save-progress');const request=p.latest();assert.equal(request.type,'checkpoint');
  assert.equal(p.element('save-progress').disabled,true);
  const buildDigest=require('./physics-build.json').sha256;
  const checkpoint={schema:'seedcore.mini-lab.checkpoint.v1',engine:P.VERSION,buildDigest,
    modelDigest:request.modelDigest,recipeDigest:request.recipeDigest,tick:8,state,control:{target:[55*Math.PI/180,-70*Math.PI/180],strength:16,motors:true},started:true,inputs:[]};
  w.reply(request,{type:'checkpoint',tick:8,status:'paused',state,checkpoint,buildDigest,backend:'cpp-wasm'});
  const saved=JSON.parse(await p.exports.at(-1).text());
  assert.deepEqual(saved.checkpoint,checkpoint);assert.equal(saved.samples.length,2);assert.equal(saved.schema,'seedcore.mini-lab.progress.v1');
});

test('progress import waits for a fresh reset, restores observation coverage and can continue',async()=>{
  const p=page(),w=p.workers[0];w.reply(p.latest());
  const settings={target:[55*Math.PI/180,-70*Math.PI/180],strength:16,mass:.7,motors:true,gravity:true},compiled=C.compile(settings);
  const state=P.createState([.2,.3],[.4,.5],8*C.DT);
  const checkpoint={schema:'seedcore.mini-lab.checkpoint.v1',engine:P.VERSION,buildDigest:require('./physics-build.json').sha256,...compiled,
    tick:8,state,control:compiled.recipe.control,started:true,inputs:[]};
  delete checkpoint.descriptor;delete checkpoint.parameters;delete checkpoint.recipe;
  const saved={schema:'seedcore.mini-lab.progress.v1',source:'local_research_simulation',settings,lesson:'reach',prediction:'yes',
    samples:[P.createState([Math.PI/12,Math.PI/4]),state],appliedInputs:[],checkpoint};
  const target={files:[{size:1000,text:async()=>JSON.stringify(saved)}],value:'chosen'};
  await p.element('progress-file').listeners.change({target});
  assert.equal(p.latest().type,'reset');assert.equal(target.value,'');w.reply(p.latest());
  const restore=p.latest();assert.equal(restore.type,'restore');assert.equal(restore.applicationTick,0);
  w.reply(restore,{tick:8,state,status:'paused'});assert.equal(p.element('run-status').textContent,'Paused');
  assert.equal(p.element('replay').disabled,false);p.click('run');assert.equal(p.latest().type,'start');assert.equal(p.latest().applicationTick,8);
});

test('invalid progress import leaves the current experiment intact',async()=>{
  const p=page();p.workers[0].reply(p.latest());const command=p.latest();
  for(const file of [{size:300000,text:async()=>''},{size:1,text:async()=>'{invalid'},
    {size:10,text:async()=>JSON.stringify({settings:{}})}]) {
    await p.element('progress-file').listeners.change({target:{files:[file]}});
    assert.equal(p.latest(),command);assert.match(p.element('feedback').textContent,/Could not restore progress/);
  }
});
