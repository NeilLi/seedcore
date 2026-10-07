/* Local simulation only. No hardware routes or execution authority. */
'use strict';
importScripts('physics.js', 'sim-contracts.js');
const P = globalThis.MiniRobotPhysics, C = MiniSimContracts;
const { PROTOCOL, DT, TOTAL_TICKS, CHUNK_TICKS } = C;
if (P.VERSION !== C.ENGINE) throw new Error('Engine/contract version mismatch.');
let runId = 0, revision = 0, sequence = 0, tick = 0, frameSequence = 0;
let compiled, model, control, state, timer = null, status = 'ready', started = false;
let inputs = [], lastCommandTick = 0, diagnostics, activeSince = null;
let deadline = null;
// Only these three buffers are allocated. Never transfer live engine state.
const free = Array.from({ length: C.POOL_SIZE }, (_, bufferId) => ({ bufferId, buffer: new ArrayBuffer(C.BUFFER_BYTES) }));
const loans = new Map();
const now = () => performance.now();
function cancelTimer() { if (timer !== null) clearTimeout(timer); timer = null; deadline = null; }
function endActive() {
  if (activeSince !== null) diagnostics.activeWallMs += now() - activeSince;
  activeSince = null;
}
function metrics() {
  const wall = diagnostics.activeWallMs + (activeSince === null ? 0 : now() - activeSince);
  return { ...diagnostics, activeWallMs: wall, simulatedMs: tick*DT*1000,
    realtimeRatio: wall > 0 ? tick*DT*1000/wall : null };
}
function reply(type = 'update', samples = [], extra = {}) {
  const message = { protocol: PROTOCOL, type, runId, revision, sequence, frameSequence: ++frameSequence,
    modelDigest: compiled.modelDigest, recipeDigest: compiled.recipeDigest,
    applicationTick: lastCommandTick, appliedTick: tick, tick, status, state, sampleCount: samples.length,
    diagnostics: metrics(), ...extra };
  if (samples.length) {
    const slot = free.pop();
    C.pack(slot.buffer, samples);
    loans.set(slot.bufferId, message.frameSequence);
    diagnostics.maxInFlight = Math.max(diagnostics.maxInFlight, loans.size);
    message.diagnostics = metrics();
    postMessage({ ...message, ...slot }, [slot.buffer]);
  } else postMessage(message);
}
function applyInputs() {
  while (inputs.length && inputs[0].applicationTick === tick) {
    const input = inputs.shift(); control = input.control;
    reply('applied', [], { sequence: input.sequence, applicationTick: tick, input });
  }
}
function advance() {
  if (!free.length) { diagnostics.bufferWaits++; return false; }
  const samples = [], begin = now();
  if (!started) { samples.push(state); started = true; }
  try {
    for (let i = 0; i < CHUNK_TICKS && tick < TOTAL_TICKS; i++) {
      applyInputs();
      state = P.step(model, state, s => control.motors ? P.motor(model, s, control.target, control.strength) : [0,0], DT);
      tick++;
    }
    // Tick inputs take effect before integrating that tick's interval.
    applyInputs();
    samples.push(state);
    diagnostics.chunks++;
    diagnostics.maxChunkMs = Math.max(diagnostics.maxChunkMs, now()-begin);
    if (tick === TOTAL_TICKS) { status = 'complete'; endActive(); }
    reply('update', samples);
  } catch (error) {
    status = 'error'; cancelTimer(); endActive();
    reply('error', [], { error: error.message });
  }
  return true;
}
function schedule() {
  if (timer !== null || status !== 'running') return;
  // Exhausted pool stops scheduling. Recycling wakes it; no tick/sample drops.
  if (!free.length) { diagnostics.bufferWaits++; deadline = null; return; }
  const period = CHUNK_TICKS*DT*1000;
  if (deadline === null) deadline = now()+period;
  timer = setTimeout(() => {
    timer = null;
    const nextDeadline = deadline+period;
    advance();
    // Compensate computation time, but never accumulate unbounded catch-up.
    // Slow callbacks rebase the wall-clock schedule, retaining every tick.
    deadline = Math.max(nextDeadline, now());
    schedule();
  }, Math.max(0, deadline-now()));
}
onmessage = ({ data: message }) => {
  try {
    if (message?.protocol === PROTOCOL && message.type === 'recycle') {
      if (loans.get(message.bufferId) !== message.frameSequence ||
          !loans.has(message.bufferId) || !(message.buffer instanceof ArrayBuffer) || message.buffer.byteLength !== C.BUFFER_BYTES) {
        throw new Error('Invalid or duplicate snapshot return.');
      }
      loans.delete(message.bufferId);
      free.push({ bufferId: message.bufferId, buffer: message.buffer });
      schedule(); return;
    }
    if (!C.validEnvelope(message) || message.sequence <= sequence) throw new Error('Invalid protocol or stale command sequence.');
    if (message.type === 'reset') {
      if (message.runId <= runId || message.applicationTick !== 0) throw new Error('Reset requires a newer run at tick zero.');
      const next = C.compile(message.settings);
      if (message.modelDigest !== next.modelDigest || message.recipeDigest !== next.recipeDigest) throw new Error('Model or recipe digest mismatch.');
      const nextModel = P.createModel(next.parameters);
      cancelTimer(); runId = message.runId; revision = message.revision; sequence = message.sequence;
      compiled = next; model = nextModel; control = next.recipe.control;
      state = P.createState(next.recipe.initial.q, next.recipe.initial.velocity);
      tick = 0; status = 'ready'; started = false; inputs = []; lastCommandTick = 0; activeSince = null;
      diagnostics = { chunks: 0, maxChunkMs: 0, activeWallMs: 0, simulatedMs: 0, realtimeRatio: null,
        bufferWaits: 0, allocatedBuffers: C.POOL_SIZE, maxInFlight: loans.size };
      reply(); return;
    }
    if (!model || message.runId !== runId || message.revision !== revision ||
        message.modelDigest !== compiled.modelDigest || message.recipeDigest !== compiled.recipeDigest) {
      throw new Error('Command does not match the current run, revision or digests.');
    }
    if (!['start','pause','step','set-control'].includes(message.type)) throw new Error('Unknown worker command.');
    if (status === 'error') throw new Error('Reset the failed experiment before continuing.');
    if (message.type === 'set-control') {
      if (!C.validControl(message.control) || message.applicationTick < tick || message.applicationTick >= TOTAL_TICKS ||
          inputs.length >= C.MAX_INPUTS || status === 'complete') throw new Error('Invalid, late or over-capacity tick input.');
      const input = { sequence: message.sequence, applicationTick: message.applicationTick,
        control: { ...message.control, target: [...message.control.target] } };
      sequence = message.sequence; inputs.push(input);
      inputs.sort((a,b) => a.applicationTick-b.applicationTick || a.sequence-b.sequence);
      reply('queued', [], { applicationTick: message.applicationTick, appliedTick: null });
      applyInputs(); return;
    }
    // Administrative requests apply at the next worker boundary; their requested
    // tick may lag an in-flight chunk. Future administrative ticks are rejected.
    if (message.applicationTick > tick) throw new Error('Administrative command requests a future tick.');
    if (message.type !== 'pause' && (status === 'running' || status === 'complete')) throw new Error('Pause or reset before this command.');
    if (message.type === 'step' && !free.length) throw new Error('Return snapshots before single stepping.');
    sequence = message.sequence; lastCommandTick = message.applicationTick; cancelTimer();
    if (message.type === 'pause') {
      endActive(); if (status === 'running') status = 'paused'; reply();
    } else if (message.type === 'step') {
      status = 'paused'; activeSince = now(); advance(); endActive();
    } else {
      status = 'running'; activeSince = now(); reply(); schedule();
    }
  } catch (error) {
    // Invalid commands do not mutate the active run, work queue or pool.
    postMessage({ protocol: PROTOCOL, type: 'rejected', runId: message?.runId, revision: message?.revision,
      modelDigest: message?.modelDigest, recipeDigest: message?.recipeDigest,
      sequence: message?.sequence, error: error.message });
  }
};
