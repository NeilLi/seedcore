/* SeedCore Mini Robot Lab - SIM-3 Kinematic Tree 3D Studio & Inspector
 * Zero-dependency interactive 3D perspective viewport for 1-, 2-, and 3-link tree dynamics.
 * Powered by Wasm ABI 2 engine (MiniTreePhysicsWasm) and MiniSimContracts.Tree.
 */
(function(root) {
  'use strict';

  const C = typeof module !== 'undefined' && module.exports ? require('./sim-contracts.js') : root.MiniSimContracts;
  const radians = deg => deg * Math.PI / 180;
  const DT = 1 / 480;
  const MAX_FRAME_TICKS = 48;

  // Preset model specifications for SIM-3
  const PRESET_MODELS = {
    '1-link': {
      name: '1-Link Nonlinear Pendulum',
      defaultQ: [radians(60)],
      defaultTarget: [0],
      model: {
        schema: C.Tree.SCHEMA,
        modelId: 'pendulum-1link',
        numLinks: 1,
        links: [
          { name: 'pole', length: 1.0, mass: 2.0, com: 0.5, inertia: 0.16666667, damping: 0.08, jointLimits: [-Math.PI, Math.PI] }
        ],
        gravity: 9.81
      }
    },
    '2-link': {
      name: '2-Link Articulated Arm',
      defaultQ: [radians(15), radians(45)],
      defaultTarget: [radians(55), radians(-70)],
      model: {
        schema: C.Tree.SCHEMA,
        modelId: 'planar-arm-2link',
        numLinks: 2,
        links: [
          { name: 'shoulder_link', length: 0.75, mass: 1.0, com: 0.375, inertia: 0.046875, damping: 0.10, jointLimits: [-Math.PI, Math.PI] },
          { name: 'elbow_link', length: 0.60, mass: 0.7, com: 0.300, inertia: 0.021000, damping: 0.10, jointLimits: [-Math.PI, Math.PI] }
        ],
        gravity: 9.81
      }
    },
    '3-link': {
      name: '3-Link Articulated Manipulator',
      defaultQ: [radians(20), radians(30), radians(-40)],
      defaultTarget: [radians(45), radians(-30), radians(20)],
      model: {
        schema: C.Tree.SCHEMA,
        modelId: 'robot-tree-3link',
        numLinks: 3,
        links: [
          { name: 'base_link', length: 0.60, mass: 1.2, com: 0.300, inertia: 0.036000, damping: 0.08, jointLimits: [-Math.PI, Math.PI] },
          { name: 'middle_link', length: 0.50, mass: 0.9, com: 0.250, inertia: 0.018750, damping: 0.08, jointLimits: [-Math.PI, Math.PI] },
          { name: 'distal_link', length: 0.40, mass: 0.6, com: 0.200, inertia: 0.008000, damping: 0.08, jointLimits: [-Math.PI, Math.PI] }
        ],
        gravity: 9.81
      }
    }
  };

  // 3D Perspective Projector
  class Projector3D {
    static project(point, width, height, camera) {
      const dx = point.x - camera.target[0];
      const dy = point.y - camera.target[1];
      const dz = point.z - camera.target[2];

      // Rotate around Y axis (yaw)
      const cosY = Math.cos(camera.yaw), sinY = Math.sin(camera.yaw);
      const x1 = dx * cosY - dz * sinY;
      const z1 = dx * sinY + dz * cosY;
      const y1 = dy;

      // Rotate around X' axis (pitch)
      const cosP = Math.cos(camera.pitch), sinP = Math.sin(camera.pitch);
      const y2 = y1 * cosP - z1 * sinP;
      const z2 = y1 * sinP + z1 * cosP + camera.distance;

      if (z2 <= 0.1) return null; // Behind camera clip plane

      const f = Math.min(width, height) * 0.95;
      const sx = width * 0.5 + (x1 * f) / z2;
      const sy = height * 0.52 - (y2 * f) / z2;
      return { x: sx, y: sy, depth: z2, scale: f / z2 };
    }
  }

  // 3D Viewport Renderer
  function renderScene(ctx, width, height, camera, treePose, targetPose, trail, options = {}) {
    ctx.clearRect(0, 0, width, height);

    // 1. Draw 3D Ground Grid (XZ plane at Y = 0)
    const gridRange = 1.6;
    const gridStep = 0.4;
    ctx.strokeStyle = '#dce6d8';
    ctx.lineWidth = 1;

    for (let x = -gridRange; x <= gridRange + 1e-5; x += gridStep) {
      const p1 = Projector3D.project({ x, y: 0, z: -gridRange }, width, height, camera);
      const p2 = Projector3D.project({ x, y: 0, z: gridRange }, width, height, camera);
      if (p1 && p2) {
        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.stroke();
      }
    }
    for (let z = -gridRange; z <= gridRange + 1e-5; z += gridStep) {
      const p1 = Projector3D.project({ x: -gridRange, y: 0, z }, width, height, camera);
      const p2 = Projector3D.project({ x: gridRange, y: 0, z }, width, height, camera);
      if (p1 && p2) {
        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.stroke();
      }
    }

    // 2. Draw 3D Origin Axes
    const orig = Projector3D.project({ x: 0, y: 0, z: 0 }, width, height, camera);
    const axisX = Projector3D.project({ x: 0.35, y: 0, z: 0 }, width, height, camera);
    const axisY = Projector3D.project({ x: 0, y: 0.35, z: 0 }, width, height, camera);
    const axisZ = Projector3D.project({ x: 0, y: 0, z: 0.35 }, width, height, camera);

    if (orig) {
      function drawAxis(to, color) {
        if (!to) return;
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(orig.x, orig.y);
        ctx.lineTo(to.x, to.y);
        ctx.stroke();
      }
      drawAxis(axisX, '#cc4e46'); // +X red
      drawAxis(axisY, '#368a48'); // +Y green
      drawAxis(axisZ, '#3b6ab5'); // +Z blue
    }

    // 3. Draw 3D End-Effector Trajectory Trail
    if (trail && trail.length > 1) {
      ctx.fillStyle = '#74a896';
      for (let i = 0; i < trail.length; i += 2) {
        const pt = Projector3D.project(trail[i], width, height, camera);
        if (pt) {
          const r = Math.max(1.5, Math.min(4, 2.5 * pt.scale * 0.003));
          ctx.beginPath();
          ctx.arc(pt.x, pt.y, r, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }

    // 4. Draw 3D Target Star / Marker
    if (targetPose && targetPose.tip) {
      const tg = Projector3D.project(targetPose.tip, width, height, camera);
      if (tg) {
        ctx.fillStyle = 'rgba(241, 223, 181, 0.45)';
        ctx.beginPath();
        ctx.arc(tg.x, tg.y, 22 * tg.scale * 0.003, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = '#b56d17';
        ctx.beginPath();
        const rOut = 13 * tg.scale * 0.003;
        const rIn = 6 * tg.scale * 0.003;
        for (let i = 0; i < 10; i++) {
          const angle = -Math.PI / 2 + (i * Math.PI) / 5;
          const r = i % 2 === 0 ? rOut : rIn;
          const px = tg.x + Math.cos(angle) * r;
          const py = tg.y + Math.sin(angle) * r;
          if (i === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        }
        ctx.closePath();
        ctx.fill();
      }
    }

    // 5. Draw 3D Base Pedestal
    if (orig) {
      ctx.fillStyle = '#bdcabb';
      ctx.beginPath();
      const baseR = 24 * orig.scale * 0.003;
      ctx.ellipse(orig.x, orig.y + 6, baseR, baseR * 0.45, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = '#859987';
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    // 6. Draw Articulated Tree Links and Joint Hubs in 3D
    if (treePose && treePose.joints) {
      const allPoints = [treePose.origin, ...treePose.joints];
      const projected = allPoints.map(p => Projector3D.project(p, width, height, camera));

      const linkColors = ['#176858', '#25846f', '#44a38b'];
      for (let i = 0; i < projected.length - 1; i++) {
        const pA = projected[i];
        const pB = projected[i + 1];
        if (!pA || !pB) continue;

        // Draw link cylinder segment
        const linkWidth = Math.max(6, Math.min(22, 16 * ((pA.scale + pB.scale) / 2) * 0.003));
        ctx.strokeStyle = linkColors[i % linkColors.length];
        ctx.lineWidth = linkWidth;
        ctx.lineCap = 'round';
        ctx.beginPath();
        ctx.moveTo(pA.x, pA.y);
        ctx.lineTo(pB.x, pB.y);
        ctx.stroke();

        // Inner highlight
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.35)';
        ctx.lineWidth = Math.max(2, linkWidth * 0.28);
        ctx.beginPath();
        ctx.moveTo(pA.x, pA.y);
        ctx.lineTo(pB.x, pB.y);
        ctx.stroke();
      }

      // Draw Joint Hubs
      for (let i = 0; i < projected.length; i++) {
        const p = projected[i];
        if (!p) continue;
        const isTip = i === projected.length - 1;
        const hubRadius = isTip ? 7 * p.scale * 0.003 : 11 * p.scale * 0.003;

        ctx.fillStyle = '#ffffff';
        ctx.beginPath();
        ctx.arc(p.x, p.y, Math.max(3, hubRadius), 0, Math.PI * 2);
        ctx.fill();

        ctx.strokeStyle = '#25493d';
        ctx.lineWidth = 2.5;
        ctx.stroke();

        if (!isTip) {
          ctx.fillStyle = '#25493d';
          ctx.beginPath();
          ctx.arc(p.x, p.y, Math.max(1.5, hubRadius * 0.4), 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }

    // Viewport HUD indicators
    ctx.fillStyle = '#536e60';
    ctx.font = '11px system-ui';
    ctx.textAlign = 'left';
    ctx.fillText('PLANAR CHAIN · XY', 16, 24);
    ctx.textAlign = 'right';
    ctx.fillText(options.gravity ? '↓ Gravity (9.81 m/s²)' : 'Gravity off', width - 16, 24);
  }

  // Freeze public presets so one consumer cannot change future experiments.
  function freeze(value) {
    if (value && typeof value === 'object') {
      Object.values(value).forEach(freeze);
      Object.freeze(value);
    }
    return value;
  }
  freeze(PRESET_MODELS);

  function requirePreset(key) {
    if (!Object.prototype.hasOwnProperty.call(PRESET_MODELS, key)) throw new Error(`Unknown model: ${key}`);
    return PRESET_MODELS[key];
  }

  // Fixed-step controller. Wall-clock pacing is bounded separately from physics.
  function createTreeLab(opts = {}) {
    let wasmEngine = opts.wasmEngine || null;
    let selectedKey = opts.defaultModel || '3-link';
    const initial = requirePreset(selectedKey);
    let compiledModel;
    let q, v, target;
    let tick = 0;
    const tauMax = 20;
    let motors = true, gravityOn = true, damping = initial.model.links[0].damping;
    let isRunning = false, lastFrame = null, accumulator = 0;
    let trail = [];
    const maxTrailPoints = 300;
    const camera = { yaw: 0.55, pitch: 0.35, distance: 3.2, target: [0, 0.45, 0] };

    function pauseClock() { lastFrame = null; accumulator = 0; }
    function configure(key, gravity, nextDamping, keepTarget) {
      const preset = requirePreset(key);
      // Compile first: rejected changes cannot poison the current experiment.
      const nextModel = C.Tree.compileTreeModel({
        ...preset.model, gravity: gravity ? 9.81 : 0,
        links: preset.model.links.map(link => ({ ...link, damping: nextDamping }))
      });
      selectedKey = key; gravityOn = gravity; damping = nextDamping;
      compiledModel = nextModel;
      q = [...preset.defaultQ]; v = new Array(nextModel.numLinks).fill(0);
      if (!keepTarget) target = [...preset.defaultTarget];
      tick = 0; trail = []; isRunning = false; pauseClock();
    }
    function reset(keepTarget = false) { configure(selectedKey, gravityOn, damping, keepTarget); }
    function setModel(key) { configure(key, gravityOn, damping, false); }
    function requireBoolean(value) {
      if (typeof value !== 'boolean') throw new Error('Expected a boolean control');
      return value;
    }
    function step(dt = DT) {
      if (!wasmEngine) throw new Error('Wasm engine not initialized');
      if (dt !== DT) throw new Error('Tree studio requires a fixed 1/480 s step');
      const next = wasmEngine.stepControlled(compiledModel, q, v, tick * DT, DT, target, tauMax, motors);
      const pose = C.Tree.forwardKinematics3D(compiledModel, next.q);
      q = [...next.q]; v = [...next.v]; tick++;
      trail.push({ ...pose.tip });
      if (trail.length > maxTrailPoints) trail.shift();
      return { q: [...q], v: [...v], t: tick * DT, appliedTau: [...next.appliedTau], pose };
    }
    function advanceFrame(now) {
      if (!Number.isFinite(now)) throw new Error('Invalid frame timestamp');
      if (!isRunning) { pauseClock(); return 0; }
      if (lastFrame === null) { lastFrame = now; return 0; }
      // Rebase after a stall: keep fixed dt, bound work, discard wall-time debt.
      const elapsed = Math.max(0, now - lastFrame) / 1000;
      lastFrame = now;
      accumulator = Math.min(accumulator + elapsed, MAX_FRAME_TICKS * DT);
      const steps = Math.min(MAX_FRAME_TICKS, Math.floor((accumulator + 1e-12) / DT));
      for (let i = 0; i < steps; i++) {
        step();
        accumulator = Math.max(0, accumulator - DT);
      }
      return steps;
    }
    function getDiagnostics() {
      if (!wasmEngine) return null;
      return {
        model: compiledModel, q: [...q], v: [...v], t: tick * DT, target: [...target],
        pose: C.Tree.forwardKinematics3D(compiledModel, q),
        targetPose: C.Tree.forwardKinematics3D(compiledModel, target),
        energy: wasmEngine.energy(compiledModel, q, v),
        terms: wasmEngine.terms(compiledModel, q, v),
        jacobian: wasmEngine.jacobian(compiledModel, q)
      };
    }
    function exportSnapshot() {
      const diag = getDiagnostics();
      if (!diag) throw new Error('Wasm engine not initialized');
      return {
        schema: 'seedcore.mini-sim.tree-experiment.v1',
        source: 'local_research_simulation', kind: 'state_snapshot',
        modelId: compiledModel.modelId, modelDigest: compiledModel.modelDigest,
        numLinks: compiledModel.numLinks, model: compiledModel,
        engine: { backend: wasmEngine.BACKEND, abi: wasmEngine.ABI, build: { ...wasmEngine.BUILD } },
        tick, dt: DT, time: tick * DT, state: { q: [...q], v: [...v] }, target: [...target],
        control: { target: [...target], tauMax, motors, controller: 'gravity-compensated-pd-24-5-v1' },
        energy: diag.energy, jacobian: diag.jacobian, date: new Date().toISOString(),
        limitations: ['current state only; no replay or checkpoint restore',
          'planar fixed-base simulation; no contacts, joint stops or hardware authority']
      };
    }
    reset();
    return {
      get camera() { return camera; },
      get model() { return compiledModel; },
      get q() { return [...q]; },
      get v() { return [...v]; },
      get t() { return tick * DT; },
      get tick() { return tick; },
      get target() { return [...target]; },
      set target(value) {
        if (!Array.isArray(value) || value.length !== compiledModel.numLinks) throw new Error('Target dimension mismatch');
        for (const angle of value) if (!Number.isFinite(angle) || Math.abs(angle) > Math.PI) throw new Error('Invalid joint target');
        target = [...value];
      },
      get motors() { return motors; },
      set motors(value) { motors = requireBoolean(value); },
      get gravityOn() { return gravityOn; },
      set gravityOn(value) { configure(selectedKey, requireBoolean(value), damping, true); },
      get damping() { return damping; },
      set damping(value) { configure(selectedKey, gravityOn, value, true); },
      get isRunning() { return isRunning; },
      set isRunning(value) {
        requireBoolean(value);
        if (value && !wasmEngine) throw new Error('Wasm engine not initialized');
        isRunning = value; pauseClock();
      },
      get trail() { return trail.map(point => ({ ...point })); },
      setWasmEngine(engine) { wasmEngine = engine; isRunning = false; pauseClock(); },
      setModel, reset, step, advanceFrame, getDiagnostics, exportSnapshot
    };
  }

  // Export module for browser & Node.js
  const TreeLabModule = {
    PRESET_MODELS,
    Projector3D,
    renderScene,
    createTreeLab
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = TreeLabModule;
  } else {
    root.MiniTreeLab = TreeLabModule;
  }
})(globalThis);
