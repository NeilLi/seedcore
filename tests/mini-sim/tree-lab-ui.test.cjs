const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const app = path.resolve(__dirname, '../../apps/mini-robot-simulator');
const C = require(`${app}/sim-contracts.js`);
const TreeLab = require(`${app}/tree-lab.js`);
const W = require(`${app}/tree-physics-wasm.js`);
const build = require(`${app}/physics-build.json`);
const bytes = fs.readFileSync(`${app}/mini-physics.wasm`);

// Run the real UI handlers against real Wasm with deterministic browser timing.
function page(options = {}) {
  const elements = new Map(), frames = [], downloads = [];
  let now = 0, requestCount = 0, stepError = false, lab;
  const ctx = new Proxy({}, { get: () => () => {} });
  function createElement() {
    return {
      listeners: {}, children: [], style: {}, value: '', textContent: '', disabled: false,
      addEventListener(type, listener) { this.listeners[type] = listener; },
      appendChild(child) { this.children.push(child); },
      click() {}, getContext: () => ctx, getBoundingClientRect: () => ({ width: 600, height: 440 }),
      setPointerCapture(id) { this.pointer = id; }, hasPointerCapture(id) { return this.pointer === id; },
      releasePointerCapture() { this.pointer = null; },
      set id(value) { elements.set(value, this); },
      set innerHTML(value) { this.children = []; this.html = value; }, get innerHTML() { return this.html; }
    };
  }
  const element = id => {
    if (!elements.has(id)) elements.set(id, createElement());
    return elements.get(id);
  };
  const document = { hidden: false, listeners: {}, getElementById: element, createElement,
    addEventListener(type, listener) { this.listeners[type] = listener; } };
  const engine = W.create(bytes, build);
  vm.runInNewContext(fs.readFileSync(`${app}/tree-lab-ui.js`, 'utf8'), {
    MiniSimContracts: C, MiniPhysicsBuild: build,
    MiniTreePhysicsWasm: { create: () => ({ ...engine, stepControlled(...args) {
      if (stepError) throw new Error('Injected numerical failure');
      return engine.stepControlled(...args);
    } }) },
    MiniTreeLab: { ...TreeLab, createTreeLab(opts) { lab = TreeLab.createTreeLab(opts); return lab; } },
    document, window: { devicePixelRatio: 2 }, performance: { now: () => now },
    ResizeObserver: class { constructor(fn) { this.fn = fn; } observe() { this.fn(); } },
    requestAnimationFrame: fn => frames.push(fn),
    fetch: async () => {
      requestCount++;
      if (options.failFirst && requestCount === 1) throw new Error('Network unavailable');
      return { ok: true, arrayBuffer: async () => options.corrupt ? new Uint8Array([0]).buffer : bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) };
    },
    Blob, Uint8Array, URL: { createObjectURL: blob => { downloads.push(blob); return 'blob:test'; }, revokeObjectURL() {} },
    setTimeout() {}, console
  });
  return { element, document, downloads, get lab() { return lab; },
    ready: () => new Promise(resolve => setImmediate(resolve)),
    failStep: value => { stepError = value; },
    click(id) { element(id).listeners.click(); },
    event(id, type, values = {}) { Object.assign(element(id), values); element(id).listeners[type]({ target: element(id) }); },
    frame(time) { now = time; assert.equal(frames.length, 1); frames.shift()(time); assert.equal(frames.length, 1); }
  };
}

test('UI runs at wall-clock speed and pauses hidden tabs without automatic resume', async () => {
  const p = page(); await p.ready();
  p.click('run');
  for (let i = 1; i <= 120; i++) p.frame(i * 1000 / 120);
  assert.equal(p.lab.tick, 480);
  p.document.hidden = true; p.document.listeners.visibilitychange();
  assert.equal(p.lab.isRunning, false);
  assert.match(p.element('run-status').textContent, /tab hidden/);
  p.frame(10_000);
  p.document.hidden = false; p.document.listeners.visibilitychange();
  assert.equal(p.lab.tick, 480);
  p.click('run'); p.frame(10_000 + 1000 / 60);
  assert.equal(p.lab.tick, 488);
});

test('numerical failures stop visibly, keep RAF alive, and recover through Reset', async () => {
  const p = page(); await p.ready(); p.click('run'); p.failStep(true);
  p.frame(1000 / 60);
  assert.equal(p.lab.isRunning, false);
  assert.equal(p.element('run-status').textContent, 'Stopped · error');
  assert.match(p.element('error-message').textContent, /Injected numerical failure/);
  assert.equal(p.element('run').disabled, true); assert.equal(p.element('export-json').disabled, true);
  p.frame(100); p.failStep(false); p.click('reset');
  assert.equal(p.element('run').disabled, false); assert.equal(p.element('error-message').textContent, '');
  p.click('step'); p.frame(200);
  assert.equal(p.lab.tick, 8);
});

test('failed loading can retry and corrupt Wasm cannot enable simulation or export', async () => {
  const p = page({ failFirst: true });
  assert.equal(p.element('export-json').disabled, true); await p.ready();
  assert.equal(p.element('run').disabled, true); assert.equal(p.element('reset').disabled, false);
  p.click('reset'); await p.ready();
  assert.equal(p.element('run-status').textContent, 'Ready');
  p.click('step'); assert.equal(p.lab.tick, 8);
  const corrupt = page({ corrupt: true }); await corrupt.ready();
  assert.match(corrupt.element('error-message').textContent, /digest mismatch/);
  assert.equal(corrupt.element('run').disabled, true);
  assert.equal(corrupt.element('export-json').disabled, true);
});

test('model and parameter edits reset and pause; joint targets update through validated setters', async () => {
  const p = page(); await p.ready(); p.click('run'); p.frame(1000 / 60);
  p.event('damping', 'input', { value: '0.22' });
  assert.equal(p.lab.tick, 0); assert.equal(p.lab.isRunning, false);
  assert.equal(p.element('run').textContent, '▶ Run Dynamics');
  p.event('q-target-0', 'input', { value: '90' });
  assert.equal(p.lab.target[0], Math.PI / 2);
  p.click('run'); p.event('model-select', 'change', { value: '1-link' });
  assert.equal(p.lab.model.numLinks, 1); assert.equal(p.lab.isRunning, false);
  assert.equal(p.element('joint-sliders').children.length, 1);
  p.click('step'); assert.equal(p.lab.tick, 8);
});

test('export uses the current model and control snapshot; camera supports keyboard and cancelled drags', async () => {
  const p = page(); await p.ready();
  p.event('motors', 'change', { checked: false }); p.click('step'); p.click('export-json');
  const saved = JSON.parse(await p.downloads[0].text());
  assert.equal(saved.kind, 'state_snapshot'); assert.equal(saved.tick, 8);
  assert.equal(saved.control.motors, false); assert.equal(saved.engine.build.sha256, build.sha256);
  const canvas = p.element('viewport3d'), yaw = p.lab.camera.yaw;
  canvas.listeners.keydown({ key: 'ArrowRight', preventDefault() {} });
  assert.equal(p.lab.camera.yaw, yaw + 0.1);
  canvas.listeners.pointerdown({ pointerId: 1, button: 0, clientX: 10, clientY: 10 });
  canvas.listeners.pointercancel({ pointerId: 1 });
  canvas.listeners.pointermove({ pointerId: 1, clientX: 100, clientY: 100 });
  assert.equal(p.lab.camera.yaw, yaw + 0.1);
});
