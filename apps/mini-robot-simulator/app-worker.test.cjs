const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const P = require('./physics.js');

// Exercise the real UI's asynchronous worker boundary without rendering a DOM.
function page() {
  const elements = new Map(), workers = [], timers = new Map();
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
    addEventListener(type, fn) { this.listeners[type] = fn; } };
  class Worker {
    constructor() { this.commands = []; workers.push(this); }
    postMessage(message) { this.commands.push(structuredClone(message)); }
    terminate() { this.terminated = true; }
    reply(command, extra = {}) {
      this.onmessage({ data: { ...command, type: 'update', status: 'ready', tick: 0,
        state: P.createState([Math.PI / 12, Math.PI / 4]), samples: [], ...extra } });
    }
  }
  let timerId = 0;
  vm.runInNewContext(fs.readFileSync(`${__dirname}/app.js`, 'utf8'), {
    MiniRobotPhysics: P, document, Worker, location: { protocol: 'http:' },
    ResizeObserver: class { observe() {} }, requestAnimationFrame() {},
    setTimeout: fn => { timers.set(++timerId, fn); return timerId; },
    clearTimeout: id => timers.delete(id),
  });
  return { element, document, workers, timers,
    click: id => element(id).listeners.click(),
    latest: () => workers.at(-1).commands.at(-1) };
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
