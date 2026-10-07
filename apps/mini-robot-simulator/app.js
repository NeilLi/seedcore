/* Local learning UI; worker computes physics, UI renders recorded snapshots. */
(() => {
  'use strict';
  const P = globalThis.MiniRobotPhysics;
  const C = MiniSimContracts;
  const $ = (id) => document.getElementById(id);
  const canvas = $('world'), ctx = canvas.getContext('2d');
  const { DT, TOTAL_TICKS: TICKS, CHUNK_TICKS: SAMPLE_EVERY, PROTOCOL } = C;
  const radians = (degrees) => degrees * Math.PI / 180;
  const degrees = (r) => r * 180 / Math.PI;
  const initial = () => P.createState([radians(15), radians(45)]);
  const controls = ['shoulder', 'elbow', 'strength', 'mass', 'motors', 'gravity'];
  let settings, model, state, tick = 0, mode = 'ready', samples = [], replayIndex = 0;
  let accumulator = 0, previousTime = null, width = 600, height = 420, revision = 0;
  let lastStatusUpdate = 0, trialPrediction = null;
  let worker = null, runId = 0, sequence = 0, pending = null, acknowledgementTimer = null;
  let compiled, lastFrameSequence = 0, workerTick = 0, diagnostics = null, appliedInputs = [];

  function failWorker(message) {
    clearTimeout(acknowledgementTimer);
    worker?.terminate(); worker = null; pending = null; mode = 'error';
    $('feedback').textContent = `Experiment stopped: ${message}`;
    updateButtons();
  }
  function send(type, extra = {}) {
    pending = ++sequence;
    clearTimeout(acknowledgementTimer);
    acknowledgementTimer = setTimeout(() => failWorker('The simulator did not acknowledge the command. Reset to try again.'), 5000);
    worker.postMessage({ protocol: PROTOCOL, type, runId, revision, sequence, applicationTick: workerTick,
      modelDigest: compiled.modelDigest, recipeDigest: compiled.recipeDigest, ...extra });
    updateButtons();
  }
  function connectWorker() {
    if (worker) return true;
    try {
      if (location.protocol === 'file:') throw new Error('Open the lab through a local HTTP server; see the README.');
      worker = new Worker('simulation-worker.js');
      const connection = worker;
      worker.onerror = () => { if (worker === connection) failWorker('The simulator worker could not run. Reset to try again.'); };
      worker.onmessageerror = () => { if (worker === connection) failWorker('The simulator response could not be read.'); };
      worker.onmessage = ({ data: message }) => {
        // Even obsolete snapshots must return their ownership to the pool.
        const current = worker === connection && message?.protocol === PROTOCOL && message.runId === runId &&
          message.revision === revision && message.modelDigest === compiled.modelDigest && message.recipeDigest === compiled.recipeDigest;
        const fresh = current && Number.isSafeInteger(message.frameSequence) && message.frameSequence > lastFrameSequence;
        let incoming = [];
        try {
          if (fresh && message.buffer) incoming = C.unpack(message.buffer, message.sampleCount);
        } catch (error) { if (worker === connection) failWorker(error.message); return; }
        finally {
          if (message?.buffer instanceof ArrayBuffer && worker === connection) connection.postMessage({ protocol: PROTOCOL, type: 'recycle',
            bufferId: message.bufferId, frameSequence: message.frameSequence, buffer: message.buffer }, [message.buffer]);
        }
        if (!current) return;
        if (message.type === 'rejected') { if (message.sequence === pending) failWorker(message.error); return; }
        if (!fresh) return;
        if (!Number.isSafeInteger(message.sequence) || message.sequence > sequence ||
            !Number.isSafeInteger(message.tick) || message.tick < workerTick || message.tick > TICKS) {
          failWorker('Invalid simulator response sequence or tick.'); return;
        }
        lastFrameSequence = message.frameSequence;
        if (message.type === 'error') { failWorker(message.error); return; }
        if (!['update','queued','applied'].includes(message.type) ||
            !['ready','running','paused','complete'].includes(message.status) || !C.validState(message.state, message.tick) ||
            (message.sampleCount !== 0 && incoming.length !== message.sampleCount)) {
          failWorker('Invalid simulator snapshot. Reset to try again.'); return;
        }
        for (const sample of incoming) {
          const expectedTick = samples.length*SAMPLE_EVERY;
          if (Math.round(sample.time/DT) !== expectedTick) { failWorker('Observation coverage is incomplete. Reset to try again.'); return; }
          samples.push(sample);
        }
        state = message.state; tick = workerTick = message.tick; diagnostics = message.diagnostics;
        if (message.input) appliedInputs.push(message.input);
        if (message.status === 'complete' && (tick !== TICKS || samples.length !== TICKS/SAMPLE_EVERY+1)) {
          failWorker('The experiment ended without all observations. Reset to try again.'); return;
        }
        // A pause can be requested while a previous chunk is in flight. Keep
        // its samples, but do not show "Paused" before the worker acknowledges.
        if (pending === null || message.sequence === pending) {
          clearTimeout(acknowledgementTimer); pending = null;
          mode = message.status;
          if (mode === 'complete') conclude();
        }
        updateReadouts(); updateButtons(); draw();
        if (document.hidden && mode === 'running' && pending === null) pause();
      };
      return true;
    } catch (error) { failWorker(error.message); return false; }
  }
  function readSettings() {
    return { target: [radians(+$('shoulder').value), radians(+$('elbow').value)], strength: +$('strength').value, mass: +$('mass').value, motors: $('motors').checked, gravity: $('gravity').checked };
  }
  function updateLabels() {
    $('shoulder-value').textContent = `${$('shoulder').value}°`;
    $('elbow-value').textContent = `${$('elbow').value}°`;
    $('strength-value').textContent = `${$('strength').value} N·m`;
    $('mass-value').textContent = `${Number($('mass').value).toFixed(1)} kg`;
  }
  function reset(newRevision = false) {
    settings = readSettings(); compiled = C.compile(settings); model = P.createModel(compiled.parameters);
    state = initial(); tick = 0; mode = 'ready'; accumulator = 0; samples = []; replayIndex = 0; trialPrediction = null;
    workerTick = 0; lastFrameSequence = 0; diagnostics = null; appliedInputs = [];
    if (newRevision) revision++;
    runId++;
    $('feedback').textContent = 'Choose your prediction, then try the move. You can pause and advance one small step at a time.';
    updateLabels(); updateReadouts(); updateButtons(); draw();
    if (connectWorker()) send('reset', { settings });
  }
  function measure(s) {
    const tip = P.forward(model, s.q).tip, goal = P.forward(model, settings.target).tip;
    const [q1, q2] = s.q, [v1, v2] = s.velocity;
    const vx = -model.l1 * Math.sin(q1) * v1 - model.l2 * Math.sin(q1 + q2) * (v1 + v2);
    const vy = model.l1 * Math.cos(q1) * v1 + model.l2 * Math.cos(q1 + q2) * (v1 + v2);
    return { distance: Math.hypot(tip[0] - goal[0], tip[1] - goal[1]), speed: Math.hypot(vx, vy) };
  }
  function predict() {
    if (!samples.length) trialPrediction = document.querySelector('input[name=prediction]:checked')?.value || 'unsure';
  }
  function begin() {
    if (tick >= TICKS || mode === 'replay' || mode === 'replayed' || mode === 'error') reset();
    if (!worker) return;
    predict();
    $('feedback').textContent = 'Watch the tip and the star. The motors apply torque; gravity and inertia shape the motion.';
    send('start');
  }
  function pause() {
    if (mode === 'replay') { mode = 'replayed'; updateButtons(); }
    else if (worker) send('pause');
  }
  function conclude() {
    // Require the entire final half-second window, not one lucky crossing.
    const tail = samples.filter((s) => s.time >= 5.5 - 1e-8);
    const settled = tail.length >= 30 && tail.every((s) => { const m = measure(s); return m.distance < 0.03 && m.speed < 0.05; });
    const m = measure(state);
    let text = settled ? 'It reached and settled near the star!' : 'It did not settle at the star within six simulated seconds.';
    text += ` The final gap was ${(100 * m.distance).toFixed(1)} cm.`;
    if (trialPrediction === 'yes' || trialPrediction === 'no') text += (settled === (trialPrediction === 'yes')) ? ' Your prediction matched this experiment.' : ' This differed from your prediction. What could explain it?';
    if (!settings.motors) text += ' With motors off, gravity and damping drive the motion. Turn the motors on and compare.';
    else if (!settled) text += ' Try more motor strength or a lighter outer arm, changing one setting at a time.';
    else text += ' Next, lower the motor strength. Will it still reach?';
    $('feedback').textContent = text;
  }
  function updateButtons() {
    const busy = pending !== null;
    $('run').disabled = busy || mode === 'running' || mode === 'replay';
    $('run').textContent = mode === 'paused' ? '▶ Continue' : tick >= TICKS || mode === 'replayed' ? '▶ Try again' : '▶ Try my move';
    $('pause').disabled = busy || (mode !== 'running' && mode !== 'replay');
    $('step').disabled = busy || mode === 'running' || mode === 'replay' || tick >= TICKS || mode === 'error' || mode === 'replayed';
    $('replay').disabled = busy || samples.length < 2 || mode === 'running' || mode === 'replay' || mode === 'error';
    $('download').disabled = busy || samples.length < 2 || mode === 'running' || mode === 'replay' || mode === 'error';
    $('run-status').textContent = busy ? 'Updating…' : ({ ready:'Ready', running:'Running', paused:'Paused', complete:'Finished', replay:'Replay · recorded', replayed:'Replay finished', error:'Stopped · error' })[mode];
    // Freeze the submitted prediction during an attempt; settings create a new revision.
    document.querySelectorAll('input[name=prediction]').forEach((input) => { input.disabled = busy || samples.length > 0; });
  }
  function updateReadouts() {
    const { distance, speed } = measure(state);
    $('time').textContent = `${state.time.toFixed(2)} s`;
    $('error').textContent = `${(distance * 100).toFixed(1)} cm`;
    $('speed').textContent = `${speed.toFixed(2)} m/s`;
    $('q1').textContent = `${degrees(state.q[0]).toFixed(1)}°`;
    $('q2').textContent = `${degrees(state.q[1]).toFixed(1)}°`;
    $('energy').textContent = `${P.energy(model, state).total.toFixed(2)} J`;
    $('runtime-detail').textContent = diagnostics?.realtimeRatio < 0.95 && workerTick >= 240
      ? 'Simulation is running slower than real time. Every physics step and observation is retained.' : '';
  }
  function draw() {
    ctx.clearRect(0, 0, width, height);
    const scale = Math.min(width / 3.35, height / 3.25);
    const origin = [width * 0.48, height * 0.51];
    const screen = (p) => [origin[0] + p[0] * scale, origin[1] - p[1] * scale];
    ctx.strokeStyle = '#e0e9dc'; ctx.lineWidth = 1;
    for (let x = -1.5; x <= 1.51; x += 0.25) { const a = screen([x, -1.5]), b = screen([x, 1.5]); ctx.beginPath(); ctx.moveTo(...a); ctx.lineTo(...b); ctx.stroke(); }
    for (let y = -1.5; y <= 1.51; y += 0.25) { const a = screen([-1.5, y]), b = screen([1.5, y]); ctx.beginPath(); ctx.moveTo(...a); ctx.lineTo(...b); ctx.stroke(); }
    // Sampled positions are drawn as dots, never treated as collision geometry.
    ctx.fillStyle = '#74a896';
    const visible = mode === 'replay' || mode === 'replayed' ? samples.slice(0, replayIndex + 1) : samples;
    visible.forEach((s, index) => { if (index % 3 === 0) { const p = screen(P.forward(model, s.q).tip); ctx.beginPath(); ctx.arc(...p, 2, 0, 2*Math.PI); ctx.fill(); } });
    const goal = screen(P.forward(model, settings.target).tip);
    ctx.fillStyle = '#f1dfb5'; ctx.beginPath(); ctx.arc(...goal, 24, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#b56d17'; ctx.beginPath();
    for (let i=0;i<10;i++) { const angle = -Math.PI/2 + i*Math.PI/5, r=i%2?6:13; const p=[goal[0]+Math.cos(angle)*r,goal[1]+Math.sin(angle)*r]; if(i===0)ctx.moveTo(...p);else ctx.lineTo(...p); }
    ctx.closePath();ctx.fill();
    const points = P.forward(model, state.q), elbow=screen(points.elbow), tip=screen(points.tip);
    function line(a,b,color,w) { ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.lineWidth=w;ctx.strokeStyle=color;ctx.lineCap='round';ctx.stroke(); }
    line([origin[0]-20,origin[1]+19],[origin[0]+20,origin[1]+19],'#bdcabb',10);
    line(origin,elbow,'#176858',19); line(elbow,tip,'#7caa88',15);
    [origin,elbow,tip].forEach((p,i)=>{ctx.beginPath();ctx.arc(...p,i===2?9:14,0,Math.PI*2);ctx.fillStyle='#fff';ctx.fill();ctx.strokeStyle='#25493d';ctx.lineWidth=3;ctx.stroke();if(i<2){ctx.beginPath();ctx.arc(...p,4,0,Math.PI*2);ctx.fillStyle='#25493d';ctx.fill();}});
    ctx.fillStyle='#536e60';ctx.font='12px system-ui';ctx.textAlign='left';
    ctx.fillText('SHOULDER',origin[0]-30,origin[1]+45);
    ctx.fillText('ELBOW',elbow[0]+18,elbow[1]-17);
    ctx.fillText(settings.gravity?'↓ gravity':'gravity off',20,28);
    ctx.textAlign='right';ctx.fillText('grid = 25 cm',width-18,height-17);
  }
  function frame(now) {
    const elapsed = previousTime === null ? 0 : Math.min((now - previousTime) / 1000, 0.1);
    previousTime = now;
    if (mode === 'replay') {
      accumulator += elapsed;
      while (accumulator >= DT*SAMPLE_EVERY && mode === 'replay') {
        accumulator -= DT*SAMPLE_EVERY; replayIndex++;
        if (replayIndex >= samples.length) { replayIndex=samples.length-1;mode='replayed';updateButtons(); }
        state=samples[replayIndex];
      }
    }
    if(now-lastStatusUpdate>100){updateReadouts();lastStatusUpdate=now;}
    draw(); requestAnimationFrame(frame);
  }
  $('run').addEventListener('click',begin);
  $('pause').addEventListener('click',pause);
  $('reset').addEventListener('click',()=>reset());
  $('step').addEventListener('click',()=>{predict();send('step');});
  $('replay').addEventListener('click',()=>{mode='replay';replayIndex=0;state=samples[0];accumulator=0;previousTime=null;$('feedback').textContent='Replaying recorded observations. No new physics steps or robot commands are being issued.';updateButtons();});
  $('download').addEventListener('click',()=>{
    const payload={schema:'seedcore.mini-lab.experiment.v2',engine:P.VERSION,source:'local_research_simulation',lesson:$('lesson').value,runId,revision,workerProtocol:PROTOCOL,dt:DT,duration:samples.at(-1).time,complete:workerTick>=TICKS&&samples.length===TICKS/SAMPLE_EVERY+1,prediction:trialPrediction,compiled,model,settings,appliedInputs,diagnostics,samples,limitations:['planar fixed-base two-link arm','no contacts or joint stops','ideal torque motors','recorded playback only, not a resumable checkpoint','not SeedCore verified execution evidence']};
    const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download='mini-robot-experiment.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  controls.forEach(id=>$(id).addEventListener('input',()=>reset(true)));
  $('lesson').addEventListener('change',()=>{
    const lesson=$('lesson').value;
    $('shoulder').value='55';$('elbow').value='-70';$('strength').value=lesson==='heavy'?'5':'16';$('mass').value=lesson==='heavy'?'1.8':'0.7';$('motors').checked=lesson!=='gravity';$('gravity').checked=true;
    const copy={reach:['Reach the star','Two motors work together to move the tip of the arm. Can they reach the star and settle there?'],gravity:['Let gravity pull','The motors are off. Predict where the arm will go, then watch gravity pull it downward.'],heavy:['A heavier arm','The outer arm is heavier and the motors are weaker. Can the same target still be reached?']};
    [$('lesson-title').textContent,$('lesson-copy').textContent]=copy[lesson];
    document.querySelectorAll('input[name=prediction]').forEach(input=>input.checked=false);reset(true);
  });
  document.addEventListener('visibilitychange',()=>{if(document.hidden&&(mode==='running'||mode==='replay')&&pending===null)pause();});
  new ResizeObserver(()=>{const box=canvas.getBoundingClientRect();width=box.width;height=box.height;const ratio=window.devicePixelRatio||1;canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);ctx.setTransform(ratio,0,0,ratio,0,0);draw();}).observe(canvas);
  reset();requestAnimationFrame(frame);
})();
