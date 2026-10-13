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
  let width = 600, height = 440;

  async function initWasm() {
    try {
      $('run-status').textContent = 'Loading Wasm...';
      const res = await fetch('mini-physics.wasm');
      if (!res.ok) throw new Error(`HTTP ${res.status} fetching mini-physics.wasm`);
      const bytes = await res.arrayBuffer();
      const digest = C.sha256Bytes(new Uint8Array(bytes));
      if (digest !== 'sha256:' + MiniPhysicsBuild.sha256) {
        throw new Error('Physics Wasm digest mismatch');
      }
      wasmEngine = MiniTreePhysicsWasm.create(bytes, MiniPhysicsBuild);
      lab.setWasmEngine(wasmEngine);
      $('run-status').textContent = 'Ready (Wasm ABI 2)';
      $('run').disabled = false;
      $('step').disabled = false;
      updateUI();
    } catch (err) {
      $('run-status').textContent = `Wasm Error: ${err.message}`;
      console.error(err);
    }
  }

  function setupControls() {
    lab = MiniTreeLab.createTreeLab({ defaultModel: '3-link' });

    // Model Selector
    $('model-select').addEventListener('change', e => {
      lab.setModel(e.target.value);
      buildJointSliders();
      updateUI();
    });

    // Transport buttons
    $('run').addEventListener('click', () => {
      lab.isRunning = !lab.isRunning;
      $('run').textContent = lab.isRunning ? '⏸ Pause' : '▶ Run Dynamics';
      $('run-status').textContent = lab.isRunning ? 'Running (480 Hz)' : 'Paused';
    });

    $('step').addEventListener('click', () => {
      if (lab.isRunning) lab.isRunning = false;
      $('run').textContent = '▶ Run Dynamics';
      $('run-status').textContent = 'Stepped';
      for (let i = 0; i < 8; i++) lab.step(1 / 480);
      updateUI();
    });

    $('reset').addEventListener('click', () => {
      lab.isRunning = false;
      $('run').textContent = '▶ Run Dynamics';
      $('run-status').textContent = 'Ready';
      lab.reset(false);
      buildJointSliders();
      updateUI();
    });

    $('reset-cam').addEventListener('click', () => {
      lab.camera.yaw = 0.55;
      lab.camera.pitch = 0.35;
      lab.camera.distance = 3.2;
    });

    // Motors & Gravity
    $('motors').addEventListener('change', e => {
      lab.motors = e.target.checked;
    });

    $('gravity').addEventListener('change', e => {
      lab.gravityOn = e.target.checked;
      updateUI();
    });

    // Damping
    $('damping').addEventListener('input', e => {
      lab.damping = parseFloat(e.target.value);
      $('damping-val').textContent = lab.damping.toFixed(2);
    });

    // Export JSON
    $('export-json').addEventListener('click', () => {
      const diag = lab.getDiagnostics();
      const payload = {
        schema: 'seedcore.mini-sim.tree-experiment.v1',
        modelId: lab.model.modelId,
        modelDigest: lab.model.modelDigest,
        numLinks: lab.model.numLinks,
        time: lab.t,
        state: { q: lab.q, v: lab.v },
        target: lab.target,
        energy: diag?.energy,
        jacobian: diag?.jacobian,
        date: new Date().toISOString()
      };
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `tree-experiment-${lab.model.modelId}.json`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });

    setupOrbitControls();
    buildJointSliders();
  }

  function setupOrbitControls() {
    let isDragging = false;
    let lastX = 0, lastY = 0;

    canvas.addEventListener('mousedown', e => {
      isDragging = true;
      lastX = e.clientX;
      lastY = e.clientY;
      canvas.style.cursor = 'grabbing';
    });

    window.addEventListener('mouseup', () => {
      isDragging = false;
      canvas.style.cursor = 'grab';
    });

    window.addEventListener('mousemove', e => {
      if (!isDragging) return;
      const dx = e.clientX - lastX;
      const dy = e.clientY - lastY;
      lastX = e.clientX;
      lastY = e.clientY;

      lab.camera.yaw += dx * 0.008;
      lab.camera.pitch = Math.max(-0.25, Math.min(1.4, lab.camera.pitch + dy * 0.008));
    });

    // Touch orbit support
    canvas.addEventListener('touchstart', e => {
      if (e.touches.length === 1) {
        isDragging = true;
        lastX = e.touches[0].clientX;
        lastY = e.touches[0].clientY;
      }
    }, { passive: true });

    window.addEventListener('touchend', () => { isDragging = false; });

    canvas.addEventListener('touchmove', e => {
      if (!isDragging || e.touches.length !== 1) return;
      const dx = e.touches[0].clientX - lastX;
      const dy = e.touches[0].clientY - lastY;
      lastX = e.touches[0].clientX;
      lastY = e.touches[0].clientY;

      lab.camera.yaw += dx * 0.008;
      lab.camera.pitch = Math.max(-0.25, Math.min(1.4, lab.camera.pitch + dy * 0.008));
    }, { passive: true });

    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      lab.camera.distance = Math.max(1.2, Math.min(6.5, lab.camera.distance + e.deltaY * 0.003));
    }, { passive: false });
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
      label.innerHTML = `<span>Joint ${i} target</span><output id="q-target-${i}-val">${Math.round(degrees(lab.target[i]))}°</output>`;

      const input = document.createElement('input');
      input.type = 'range';
      input.min = '-180';
      input.max = '180';
      input.step = '5';
      input.value = Math.round(degrees(lab.target[i])).toString();
      input.id = `q-target-${i}`;

      input.addEventListener('input', e => {
        const degVal = parseInt(e.target.value, 10);
        lab.target[i] = radians(degVal);
        $(`q-target-${i}-val`).textContent = `${degVal}°`;
      });

      wrap.appendChild(label);
      wrap.appendChild(input);
      container.appendChild(wrap);
    }
  }

  function updateUI() {
    const diag = lab.getDiagnostics();
    if (!diag) return;

    $('time-val').textContent = `${lab.t.toFixed(2)} s`;
    $('tip-x-val').textContent = diag.pose.tip.x.toFixed(3);
    $('tip-y-val').textContent = diag.pose.tip.y.toFixed(3);
    $('tip-z-val').textContent = diag.pose.tip.z.toFixed(3);

    // Speed calculation
    const n = lab.model.numLinks;
    const J = diag.jacobian;
    let vx = 0, vy = 0;
    for (let i = 0; i < n; i++) {
      vx += J.Jx[i] * lab.v[i];
      vy += J.Jy[i] * lab.v[i];
    }
    const speed = Math.sqrt(vx * vx + vy * vy);
    $('tip-speed-val').textContent = `${speed.toFixed(2)} m/s`;

    // Energy
    $('energy-k').textContent = `${diag.energy.kinetic.toFixed(3)} J`;
    $('energy-u').textContent = `${diag.energy.potential.toFixed(3)} J`;
    $('energy-tot').textContent = `${diag.energy.total.toFixed(3)} J`;

    // Model digest badge
    $('model-digest-badge').textContent = lab.model.modelDigest.slice(0, 15) + '...';

    // Joint table
    const tableBody = $('joint-table-body');
    tableBody.innerHTML = '';
    for (let i = 0; i < n; i++) {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><strong>q${i}</strong> (${lab.model.links[i].name})</td>
        <td>${degrees(lab.q[i]).toFixed(1)}° (${lab.q[i].toFixed(2)} rad)</td>
        <td>${lab.v[i].toFixed(2)} rad/s</td>
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
    if (lab && lab.isRunning && wasmEngine) {
      // Step 8 ticks (8 * 1/480 = 1/60s)
      for (let i = 0; i < 8; i++) {
        lab.step(1 / 480);
      }
    }

    if (lab) {
      const diag = lab.getDiagnostics();
      if (diag) {
        MiniTreeLab.renderScene(
          ctx,
          width,
          height,
          lab.camera,
          diag.pose,
          diag.targetPose,
          lab.trail,
          { gravity: lab.gravityOn }
        );
      }
    }

    if (now - lastUiUpdate > 80) {
      updateUI();
      lastUiUpdate = now;
    }

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
