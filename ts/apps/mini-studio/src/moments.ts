import { canonicalAssemblyString } from '@seedcore/contracts';
import { CW_S02_WORKER_PROTOCOL, assertCompiledGestureCurrent, assertQualifiedMujocoSettings, compileGesture,
  CW_S04_MAX_BODIES, createGestureReplay, createTabletopGestureExample, inspectGestureReplay, gestureCaptureDigest,
  type CompiledGesture, type CompiledMjcf, type GestureBinding, type GestureReplay, type GestureReplayProjection, type GestureReplayExpected,
} from '@seedcore/wasm-sim-bridge';

/** Local JSON authoring and read-only capture scrubber; never an admission service. */
export function setupMoments(host: { current: () => {model: CompiledMjcf; binding: GestureBinding}; stopOther: () => void }) {
  const el = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
  const button = (id: string) => el<HTMLButtonElement>(id);
  let compiled: CompiledGesture | undefined, replay: GestureReplay | undefined, projection: GestureReplayProjection | undefined;
  let retainedAttempt: GestureReplayExpected | undefined;
  let worker: Worker | undefined, timer: ReturnType<typeof setTimeout> | undefined;
  let generation = 0, disposed = false, stopping = false;
  const status = (message: string, state: string) => {
    el('moment-status').textContent = message; el('moment-status').dataset.state = state;
  };
  const clearCapture = () => {
    replay = undefined; projection = undefined;
    el('moment-result').textContent = 'No current captured attempt.';
    el('moment-values').replaceChildren(); el('moment-frame').textContent = '—';
    el('moment-led').textContent = 'Virtual LED · no captured frame'; el('moment-led').style.backgroundColor = '';
    el<HTMLInputElement>('moment-tick').disabled = true;
    button('moment-export').disabled = true;
  };
  const terminate = () => { clearTimeout(timer); timer = undefined; worker?.terminate(); worker = undefined; stopping = false; button('moment-stop').disabled = true; };
  const current = () => {
    const c = host.current();
    if (!compiled) throw new Error('Validate a gesture for the current model first.');
    assertCompiledGestureCurrent(compiled,c.model,c.binding,compiled.gestureDigest);
    return c;
  };
  const refresh = () => {
    let eligible = false;
    try { const c = host.current(); assertQualifiedMujocoSettings(c.model); eligible = c.model.manifest.catalogProvenance === 'synthetic_fixture' && c.model.manifest.options.actuatorMode === 'position' && c.model.manifest.bodies.length <= CW_S04_MAX_BODIES; } catch {}
    button('moment-example').disabled = !eligible; button('moment-compile').disabled = !eligible;
    button('moment-run').disabled = !compiled || Boolean(worker);
    button('moment-inspect-replay').disabled = !retainedAttempt || Boolean(worker);
  };
  const invalidate = (reason = 'Build or settings changed. Rebind and validate a new simulation gesture.') => {
    generation++; terminate(); compiled = undefined; retainedAttempt = undefined;
    clearCapture(); el('moment-digest').textContent = '—'; el('moment-bounds').textContent = '';
    status(reason,'stale'); refresh();
  };
  const paintFrame = (index: number) => {
    const frame = projection?.frames[index];
    if (!frame || !compiled) return;
    el('moment-frame').textContent = `Captured tick ${frame.tick} · ${frame.simTimeSeconds.toFixed(3)} s`;
    el('moment-led').textContent = `Virtual LED ${frame.virtualLed} · display only`;
    el('moment-led').style.backgroundColor = frame.virtualLed;
    el('moment-values').replaceChildren(...compiled.tracks.map((t,i) => {
      const row = document.createElement('div');
      row.textContent = `${t.jointId}: target ${frame.targetRad[i].toFixed(6)} rad; observed ${frame.observedRad[i].toFixed(6)} rad; observed velocity ${frame.observedVelocityRadS[i].toFixed(6)} rad/s`;
      return row;
    }));
  };
  const retainReplay = (raw: unknown) => {
    const c = current();
    if (!retainedAttempt) throw new Error('No independently retained current attempt.');
    const checked = inspectGestureReplay(raw,c.model,retainedAttempt);
    replay = checked.replay; projection = checked.projection;
    el('moment-result').textContent = `${projection.disposition} · ${projection.capturedTicks}/${projection.plannedTicks} steps · ${replay.replayDigest} · unsigned simulation capture; no physical proof`;
    const slider = el<HTMLInputElement>('moment-tick'); slider.min = '0'; slider.max = String(Math.max(0,projection.frames.length-1)); slider.value = '0'; slider.disabled = !projection.frames.length;
    button('moment-export').disabled = false;
    if (projection.frames.length) paintFrame(0);
  };
  el<HTMLTextAreaElement>('moment-json').oninput = () => invalidate('Gesture edited. Previous compilation, attempt and replay invalidated.');
  button('moment-example').onclick = () => {
    invalidate('New synthetic example. Validate its full curves before rehearsal.');
    try { const c = host.current(); el<HTMLTextAreaElement>('moment-json').value = JSON.stringify(createTabletopGestureExample(c.model,c.binding),null,2); }
    catch (e) { status(String(e),'rejected'); }
  };
  button('moment-compile').onclick = () => {
    invalidate('Checking gesture…');
    try {
      const c = host.current(); compiled = compileGesture(el<HTMLTextAreaElement>('moment-json').value,c.model,c.binding);
      el('moment-digest').textContent = compiled.gestureDigest;
      el('moment-bounds').textContent = JSON.stringify(compiled.tracks,null,2);
      status(`Validated target curves · ${compiled.totalTicks} steps / ${(compiled.totalTicks*0.002).toFixed(3)} s · simulation only; no admission granted.`,'compiled');
    } catch (e) { status(e instanceof Error ? e.message : String(e),'rejected'); }
    refresh();
  };
  button('moment-run').onclick = () => {
    try {
      const c = current(), gesture = compiled!;
      if (document.hidden) throw new Error('Cannot rehearse a gesture in a hidden page.');
      host.stopOther(); terminate(); clearCapture(); retainedAttempt = undefined;
      const gen = ++generation;
      const pendingIdentity = {binding:{...c.binding},gestureDigest:gesture.gestureDigest,generation:gen};
      const runWorker = new Worker('/cw-s02-worker.js',{type:'module',name:'seedcore-cw-s04-moments'});
      worker = runWorker; button('moment-stop').disabled = false;
      status('Loading the pinned MuJoCo worker. Stop is available during startup.','loading'); refresh();
      timer = setTimeout(() => {
        if (gen !== generation) return;
        generation++; terminate(); clearCapture(); retainedAttempt = undefined;
        status('Worker timed out; capture unavailable. Start a fresh attempt.','failed'); refresh();
      },12000);
      runWorker.onmessage = ({data:m}) => {
        if (disposed || gen !== generation || worker !== runWorker || !m || m.protocol !== CW_S02_WORKER_PROTOCOL || m.generation !== gen) return;
        try {
          current();
          if (['ready','progress','complete'].includes(m.type) && m.gestureDigest !== gesture.gestureDigest) throw new Error('Worker gesture identity mismatch');
          if (m.type === 'ready' || m.type === 'progress') {
            if (stopping) return;
            status(`Running simulation gesture · ${m.summary.executedSubsteps}/${gesture.totalTicks} captured steps.`,'running'); return;
          }
          if (!['complete','stopped','error'].includes(m.type)) return;
          if (m.summary && m.samples) {
            // This pin comes from the original local worker capture, before any
            // replay import. Importing/re-hashing JSON cannot replace this identity.
            const expected = {...pendingIdentity,captureDigest:gestureCaptureDigest(m.summary,m.samples)};
            const next = createGestureReplay(gesture,m.summary,m.samples,c.model,expected);
            retainedAttempt = expected;
            retainReplay(next);
          } else clearCapture();
          terminate(); refresh();
          status(m.type === 'complete' ? 'Simulation capture completed. Scrub retained samples below.' :
            `${m.type === 'stopped' ? 'Stopped' : 'Worker fault'}: ${String(m.reason ?? m.error ?? 'interrupted')}. ${replay ? 'Partial capture retained.' : 'No capture available.'}`,
            m.type === 'complete' ? 'completed' : m.type === 'stopped' ? 'interrupted' : 'failed');
        } catch (e) {
          terminate(); clearCapture(); retainedAttempt = undefined;
          status(`Capture rejected: ${e instanceof Error ? e.message : String(e)}`,'failed'); refresh();
        }
      };
      runWorker.onerror = event => {
        event.preventDefault(); if (gen !== generation || worker !== runWorker) return;
        terminate(); clearCapture(); retainedAttempt = undefined;
        status(`Worker failed; no accepted capture: ${event.message}`,'failed'); refresh();
      };
      runWorker.postMessage({protocol:CW_S02_WORKER_PROTOCOL,type:'run',generation:gen,model:c.model,binding:c.binding,
        gesture:gesture.draft,gestureDigest:gesture.gestureDigest,totalSubsteps:gesture.totalTicks,policyDecimation:1});
    } catch (e) {
      terminate(); clearCapture(); retainedAttempt = undefined;
      status(e instanceof Error ? e.message : String(e),'rejected'); refresh();
    }
  };
  const interrupt = (type: 'stop' | 'hidden') => {
    if (!worker || stopping) return;
    stopping = true;
    worker.postMessage({protocol:CW_S02_WORKER_PROTOCOL,type,generation,reason:'Simulation gesture stopped by operator'});
    button('moment-stop').disabled = true;
    status(type === 'stop' ? 'Stop requested. Waiting for retained worker capture.' : 'Hidden page: fencing the simulation attempt.','stopping');
    clearTimeout(timer);
    const gen = generation;
    timer = setTimeout(() => {
      if (gen !== generation) return;
      generation++; terminate(); clearCapture(); retainedAttempt = undefined;
      status('Interrupted without a worker acknowledgement; capture unavailable.','interrupted'); refresh();
    },2000);
  };
  button('moment-stop').onclick = () => interrupt('stop');
  el<HTMLInputElement>('moment-tick').oninput = () => {
    try { current(); paintFrame(Number(el<HTMLInputElement>('moment-tick').value)); }
    catch { invalidate('Replay no longer matches the current build.'); }
  };
  button('moment-export').onclick = () => {
    try {
      current(); if (!replay) throw new Error('No current replay.');
      // Recheck integrity/bindings immediately before export.
      retainReplay(replay);
      const url = URL.createObjectURL(new Blob([canonicalAssemblyString(replay)+'\n'],{type:'application/json'}));
      const a = document.createElement('a'); a.href = url; a.download = 'gesture.cw-s04.replay.json'; a.click();
      setTimeout(() => URL.revokeObjectURL(url),1000);
    } catch (e) { status(String(e),'rejected'); }
  };
  button('moment-inspect-replay').onclick = () => {
    clearCapture();
    try { retainReplay(el<HTMLTextAreaElement>('moment-replay-json').value); status('Imported capture matches the independently retained current attempt; read-only simulation projection.','replayed'); }
    catch (e) { status(`Replay rejected: ${String(e)}`,'rejected'); }
  };
  const onHidden = () => { if (document.hidden) interrupt('hidden'); };
  document.addEventListener('visibilitychange',onHidden);
  return {invalidate,refresh,dispose() {disposed = true; invalidate('Disposed'); document.removeEventListener('visibilitychange',onHidden);}};
}
