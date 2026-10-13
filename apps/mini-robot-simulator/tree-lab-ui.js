/* SeedCore Mini Robot Lab - SIM-3 UI & 3D Interaction Controller */
(() => {
  'use strict';

  const C = MiniSimContracts;
  const radians = deg => deg * Math.PI / 180;
  const degrees = rad => rad * 180 / Math.PI;

  const $ = id => document.getElementById(id);
  const canvas = $('viewport3d');
  const ctx = canvas.getContext('2d');

  let lab = null;
  let wasmEngine = null;
  let loading = false, failed = false;
  let lastDiagnostics = null;
  let width = 600, height = 440;

  function setTransport(status) {
    $('run-status').textContent = status;
    $('run').textContent = lab.isRunning ? '⏸ Pause' : '▶ Run Dynamics';
    for (const id of ['run', 'step', 'export-json', 'model-select', 'damping', 'gravity', 'motors']) {
      $(id).disabled = loading || failed || !wasmEngine;
    }
    for (let i = 0; i < lab.model.numLinks; i++) $(`q-target-${i}`).disabled = loading || failed || !wasmEngine;
    $('reset').disabled = loading;
    $('reset').textContent = !loading && !wasmEngine ? 'Retry loading' : 'Reset';
  }

  function stopWithError(err) {
    failed = true;
    lab.isRunning = false;
    $('error-message').textContent = `${err.message}. Use ${wasmEngine ? 'Reset' : 'Retry loading'} to recover.`;
    setTransport('Stopped · error');
  }

  function guarded(action) {
    if (!wasmEngine || failed || loading) return;
    try { action(); } catch (err) { stopWithError(err); }
  }

  async function initWasm() {
    if (loading) return;
    loading = true; failed = false;
    $('error-message').textContent = '';
    setTransport('Loading physics…');
    try {
      const res = await fetch('mini-physics.wasm');
      if (!res.ok) throw new Error(`HTTP ${res.status} fetching mini-physics.wasm`);
      const bytes = await res.arrayBuffer();
      if (C.sha256Bytes(new Uint8Array(bytes)) !== 'sha256:' + MiniPhysicsBuild.sha256) {
        throw new Error('Physics Wasm digest mismatch');
      }
      wasmEngine = MiniTreePhysicsWasm.create(bytes, MiniPhysicsBuild);
      lab.setWasmEngine(wasmEngine);
      loading = false;
      updateUI();
      setTransport('Ready');
    } catch (err) {
      loading = false; wasmEngine = null; lab.setWasmEngine(null);
      stopWithError(err);
    }
  }

  function setupControls() {
    lab = MiniTreeLab.createTreeLab({ defaultModel: '3-link' });

    $('model-select').addEventListener('change', e => guarded(() => {
      lab.setModel(e.target.value);
      buildJointSliders(); updateUI(); setTransport('Ready · model reset');
    }));
    $('run').addEventListener('click', () => guarded(() => {
      if (document.hidden) return;
      lab.isRunning = !lab.isRunning;
      if (lab.isRunning) lab.advanceFrame(performance.now());
      updateUI();
      setTransport(lab.isRunning ? 'Running' : 'Paused');
    }));
    $('step').addEventListener('click', () => guarded(() => {
      lab.isRunning = false;
      for (let i = 0; i < 8; i++) lab.step();
      updateUI(); setTransport('Paused · stepped 8 ticks');
    }));
    $('reset').addEventListener('click', () => {
      if (loading) return;
      if (!wasmEngine) { initWasm(); return; }
      try {
        lab.reset(); failed = false;
        $('error-message').textContent = '';
        buildJointSliders(); updateUI(); setTransport('Ready');
      } catch (err) { stopWithError(err); }
    });
    $('reset-cam').addEventListener('click', () => {
      Object.assign(lab.camera, { yaw: 0.55, pitch: 0.35, distance: 3.2 });
    });
    $('motors').addEventListener('change', e => guarded(() => { lab.motors = e.target.checked; }));
    $('gravity').addEventListener('change', e => guarded(() => {
      lab.gravityOn = e.target.checked;
      updateUI(); setTransport('Ready · gravity reset');
    }));
    $('damping').addEventListener('input', e => guarded(() => {
      lab.damping = Number(e.target.value);
      $('damping-val').textContent = lab.damping.toFixed(2);
      updateUI(); setTransport('Ready · damping reset');
    }));
    document.addEventListener('visibilitychange', () => guarded(() => {
      if (document.hidden && lab.isRunning) {
        lab.isRunning = false;
        updateUI();
        setTransport('Paused · tab hidden');
      }
    }));
    $('export-json').addEventListener('click', () => guarded(() => {
      const payload = lab.exportSnapshot();
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `tree-state-${lab.model.modelId}.json`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }));
    setupOrbitControls();
    buildJointSliders();
  }

  function setupOrbitControls() {
    let pointer = null, lastX = 0, lastY = 0;
    canvas.addEventListener('pointerdown', e => {
      if (pointer !== null || e.button !== 0) return;
      pointer = e.pointerId; lastX = e.clientX; lastY = e.clientY;
      canvas.setPointerCapture(pointer);
      canvas.style.cursor = 'grabbing';
    });
    canvas.addEventListener('pointermove', e => {
      if (e.pointerId !== pointer) return;
      lab.camera.yaw += (e.clientX - lastX) * 0.008;
      lab.camera.pitch = Math.max(-0.25, Math.min(1.4, lab.camera.pitch + (e.clientY - lastY) * 0.008));
      lastX = e.clientX; lastY = e.clientY;
    });
    const stopDrag = e => {
      if (e.pointerId !== pointer) return;
      if (canvas.hasPointerCapture(pointer)) canvas.releasePointerCapture(pointer);
      pointer = null; canvas.style.cursor = 'grab';
    };
    for (const event of ['pointerup', 'pointercancel', 'lostpointercapture']) canvas.addEventListener(event, stopDrag);
    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? height : 1;
      lab.camera.distance = Math.max(1.2, Math.min(6.5, lab.camera.distance + e.deltaY * unit * 0.003));
    }, { passive: false });
    canvas.addEventListener('keydown', e => {
      if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', '+', '=', '-'].includes(e.key)) return;
      e.preventDefault();
      if (e.key === 'ArrowLeft') lab.camera.yaw -= 0.1;
      if (e.key === 'ArrowRight') lab.camera.yaw += 0.1;
      if (e.key === 'ArrowUp') lab.camera.pitch = Math.max(-0.25, lab.camera.pitch - 0.1);
      if (e.key === 'ArrowDown') lab.camera.pitch = Math.min(1.4, lab.camera.pitch + 0.1);
      if (e.key === '+' || e.key === '=') lab.camera.distance = Math.max(1.2, lab.camera.distance - 0.2);
      if (e.key === '-') lab.camera.distance = Math.min(6.5, lab.camera.distance + 0.2);
    });
  }

  function buildJointSliders() {
    const container = $('joint-sliders');
    container.innerHTML = '';
    const n = lab.model.numLinks;

    for (let i = 0; i < n; i++) {
      const wrap = document.createElement('div');
      wrap.className = 'slider-group';

      const label = document.createElement('label');
      label.className = 'slider-label';
      label.htmlFor = `q-target-${i}`;
      label.innerHTML = `<span>Joint ${i} target</span><output id="q-target-${i}-val">${Math.round(degrees(lab.target[i]))}°</output>`;

      const input = document.createElement('input');
      input.type = 'range';
      input.min = '-180';
      input.max = '180';
      input.step = '5';
      input.value = Math.round(degrees(lab.target[i])).toString();
      input.id = `q-target-${i}`;

      input.addEventListener('input', e => guarded(() => {
        const degVal = parseInt(e.target.value, 10);
        const target = lab.target; target[i] = radians(degVal); lab.target = target;
        $(`q-target-${i}-val`).textContent = `${degVal}°`;
        updateUI();
      }));

      wrap.appendChild(label);
      wrap.appendChild(input);
      container.appendChild(wrap);
    }
  }

  function updateUI(diag = lab.getDiagnostics()) {
    if (!diag) return;
    lastDiagnostics = diag;

    $('time-val').textContent = `${lab.t.toFixed(2)} s`;
    $('tip-x-val').textContent = diag.pose.tip.x.toFixed(3);
    $('tip-y-val').textContent = diag.pose.tip.y.toFixed(3);
    $('tip-z-val').textContent = diag.pose.tip.z.toFixed(3);

    // Speed calculation
    const n = lab.model.numLinks;
    const J = diag.jacobian;
    let vx = 0, vy = 0;
    for (let i = 0; i < n; i++) {
      vx += J.Jx[i] * diag.v[i];
      vy += J.Jy[i] * diag.v[i];
    }
    const speed = Math.sqrt(vx * vx + vy * vy);
    $('tip-speed-val').textContent = `${speed.toFixed(2)} m/s`;

    // Energy
    $('energy-k').textContent = `${diag.energy.kinetic.toFixed(3)} J`;
    $('energy-u').textContent = `${diag.energy.potential.toFixed(3)} J`;
    $('energy-tot').textContent = `${diag.energy.total.toFixed(3)} J`;

    // Model digest badge
    $('model-digest-badge').textContent = lab.model.modelDigest.slice(0, 19) + '…';
    $('model-digest-badge').title = lab.model.modelDigest;

    // Joint table
    const tableBody = $('joint-table-body');
    tableBody.innerHTML = '';
    for (let i = 0; i < n; i++) {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td title="${lab.model.links[i].name}"><strong>q${i}</strong></td>
        <td title="${diag.q[i].toFixed(4)} rad">${degrees(diag.q[i]).toFixed(1)}°</td>
        <td>${diag.v[i].toFixed(2)} rad/s</td>
        <td>${degrees(lab.target[i]).toFixed(1)}°</td>
      `;
      tableBody.appendChild(tr);
    }

    // Mass matrix
    const massTable = $('mass-matrix-table');
    massTable.innerHTML = '';
    const M = diag.terms.M;
    for (let i = 0; i < n; i++) {
      const tr = document.createElement('tr');
      for (let j = 0; j < n; j++) {
        const td = document.createElement('td');
        td.textContent = M[i][j].toFixed(3);
        tr.appendChild(td);
      }
      massTable.appendChild(tr);
    }

    // Jacobian
    const jacTable = $('jacobian-table');
    jacTable.innerHTML = '';
    const trX = document.createElement('tr');
    const tdXName = document.createElement('td');
    tdXName.innerHTML = '<strong>Jx</strong>';
    trX.appendChild(tdXName);
    for (let j = 0; j < n; j++) {
      const td = document.createElement('td');
      td.textContent = J.Jx[j].toFixed(3);
      trX.appendChild(td);
    }
    jacTable.appendChild(trX);

    const trY = document.createElement('tr');
    const tdYName = document.createElement('td');
    tdYName.innerHTML = '<strong>Jy</strong>';
    trY.appendChild(tdYName);
    for (let j = 0; j < n; j++) {
      const td = document.createElement('td');
      td.textContent = J.Jy[j].toFixed(3);
      trY.appendChild(td);
    }
    jacTable.appendChild(trY);
  }

  let lastUiUpdate = 0;
  function loop(now) {
    try {
      if (wasmEngine && !failed) {
        lab.advanceFrame(now);
        lastDiagnostics = lab.getDiagnostics();
        if (lab.isRunning && now - lastUiUpdate > 80) {
          updateUI(lastDiagnostics);
          lastUiUpdate = now;
        }
      }
      if (lastDiagnostics) {
        MiniTreeLab.renderScene(ctx, width, height, lab.camera,
          lastDiagnostics.pose, lastDiagnostics.targetPose, lab.trail, { gravity: lab.gravityOn });
      }
    } catch (err) { stopWithError(err); }
    // A physics failure must not kill rendering or Reset recovery.
    requestAnimationFrame(loop);
  }

  // Canvas ResizeObserver
  new ResizeObserver(() => {
    const box = canvas.getBoundingClientRect();
    width = box.width;
    height = box.height;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  }).observe(canvas);

  setupControls();
  initWasm();
  requestAnimationFrame(loop);
})();
