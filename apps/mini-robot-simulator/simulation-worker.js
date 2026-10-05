/* Local simulation only. Also loaded in a Node VM by the worker protocol tests. */
'use strict';
importScripts('physics.js');

const P = globalThis.MiniRobotPhysics;
const PROTOCOL = 'seedcore.mini-lab.worker.v1';
const DT = 1 / 480, TOTAL_TICKS = 2880, CHUNK_TICKS = 8;
let runId = 0, revision = 0, sequence = 0, tick = 0;
let model, settings, state, timer = null, status = 'ready', started = false;

function cancelTimer() {
  if (timer !== null) clearTimeout(timer);
  timer = null;
}

function reply(type, samples = [], error) {
  postMessage({ protocol: PROTOCOL, type, runId, revision, sequence,
    tick, status, state, samples, error });
}

function advance() {
  const samples = [];
  if (!started) { samples.push(state); started = true; }
  try {
    for (let i = 0; i < CHUNK_TICKS && tick < TOTAL_TICKS; i++) {
      state = P.step(model, state,
        s => settings.motors ? P.motor(model, s, settings.target, settings.strength) : [0, 0], DT);
      tick++;
    }
    samples.push(state);
    if (tick === TOTAL_TICKS) status = 'complete';
    reply('update', samples);
  } catch (error) {
    status = 'error';
    cancelTimer();
    reply('error', samples, error.message);
  }
}

function schedule() {
  // One bounded chunk per callback. Throttling slows simulated time without
  // skipping ticks or enlarging dt; the event loop can process pause/reset.
  timer = setTimeout(() => {
    timer = null;
    advance();
    if (status === 'running') schedule();
  }, CHUNK_TICKS * DT * 1000);
}

function validSettings(value) {
  return value && Array.isArray(value.target) && value.target.length === 2 &&
    value.target.every(x => Number.isFinite(x) && Math.abs(x) <= Math.PI) &&
    Number.isFinite(value.strength) && value.strength >= 1 && value.strength <= 20 &&
    Number.isFinite(value.mass) && value.mass >= 0.2 && value.mass <= 2 &&
    typeof value.motors === 'boolean' && typeof value.gravity === 'boolean';
}

onmessage = ({ data: message }) => {
  try {
    if (!message || message.protocol !== PROTOCOL ||
        !Number.isSafeInteger(message.runId) || message.runId <= 0 ||
        !Number.isSafeInteger(message.revision) || message.revision < 0 ||
        !Number.isSafeInteger(message.sequence) || message.sequence <= sequence) {
      throw new Error('Invalid protocol or stale command sequence.');
    }
    if (message.type === 'reset') {
      if (message.runId <= runId || !validSettings(message.settings)) {
        throw new Error('Reset requires a new run and valid lesson settings.');
      }
      const nextModel = P.createModel({ m2: message.settings.mass, gravity: message.settings.gravity ? 9.81 : 0 });
      cancelTimer();
      runId = message.runId;
      revision = message.revision;
      sequence = message.sequence;
      settings = message.settings;
      model = nextModel;
      state = P.createState([15 * Math.PI / 180, 45 * Math.PI / 180]);
      tick = 0; status = 'ready'; started = false;
      reply('update');
      return;
    }
    if (!model || message.runId !== runId || message.revision !== revision) {
      throw new Error('Command does not match the current run and model revision.');
    }
    if (!['start', 'pause', 'step'].includes(message.type)) throw new Error('Unknown worker command.');
    if (status === 'error') throw new Error('Reset the failed experiment before continuing.');
    if (message.type !== 'pause' && (status === 'running' || status === 'complete')) {
      throw new Error('Pause or reset before this command.');
    }
    sequence = message.sequence;
    cancelTimer();
    if (message.type === 'pause') {
      if (status === 'running') status = 'paused';
      reply('update');
    } else if (message.type === 'step') {
      status = 'paused';
      advance();
    } else {
      status = 'running';
      const samples = started ? [] : [state];
      started = true;
      reply('update', samples);
      schedule();
    }
  } catch (error) {
    // Rejection does not change the active run or its timer. Echo the rejected
    // envelope so the UI can discard replies belonging to an obsolete run.
    postMessage({ protocol: PROTOCOL, type: 'rejected', runId: message?.runId,
      revision: message?.revision, sequence: message?.sequence, error: error.message });
  }
};
