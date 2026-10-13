/* SeedCore Mini Tree Physics Wasm Bridge (SIM-3)
 * Provides high-level JS wrapper for 1-, 2-, and 3-link kinematic tree dynamics.
 * Direct memory layout matching mini_tree_physics.h (ABI 2).
 */
(function(root) {
  'use strict';

  function create(bytes, build) {
    const module = new WebAssembly.Module(bytes);
    const instance = new WebAssembly.Instance(module, { env: { sin: Math.sin, cos: Math.cos } });
    const e = instance.exports;

    if (typeof e.mini_tree_abi !== 'function' || e.mini_tree_abi() !== 2) {
      throw new Error('Unsupported tree physics ABI.');
    }

    const scratchPtr = e.mini_tree_scratch();
    const b = new Float64Array(e.memory.buffer, scratchPtr, 64);

    function validateVector(values, n, name, allowEmpty = false) {
      if (!Array.isArray(values) || (values.length !== n && !(allowEmpty && values.length === 0))) {
        throw new Error(`${name} dimension mismatch`);
      }
      for (const value of values) {
        if (!Number.isFinite(value)) throw new Error(`Invalid ${name} component`);
      }
    }

    function packInputs(model, q, v, t, tau, dt, target, tauMax, motors) {
      if (!model || !Number.isInteger(model.numLinks) || model.numLinks < 1 || model.numLinks > 3 ||
          !Array.isArray(model.links) || model.links.length !== model.numLinks) {
        throw new Error('Invalid tree model dimensions');
      }
      validateVector(q, model.numLinks, 'q');
      validateVector(v, model.numLinks, 'v', true);
      validateVector(tau, model.numLinks, 'tau', true);
      validateVector(target, model.numLinks, 'target', true);
      if (!Number.isFinite(t) || !Number.isFinite(dt) || !Number.isFinite(tauMax) || typeof motors !== 'boolean') {
        throw new Error('Invalid tree time or control input');
      }
      b.fill(0);
      b[0] = model.numLinks;
      for (let i = 0; i < model.numLinks; i++) {
        const link = model.links[i];
        if (!link || !['length', 'mass', 'com', 'inertia', 'damping'].every(key => Number.isFinite(link[key]))) {
          throw new Error('Invalid tree link parameters');
        }
        b[1 + i] = model.links[i].length;
        b[4 + i] = model.links[i].mass;
        b[7 + i] = model.links[i].com;
        b[10 + i] = model.links[i].inertia;
        b[13 + i] = model.links[i].damping;
      }
      if (!Number.isFinite(model.gravity)) throw new Error('Invalid tree gravity');
      b[16] = model.gravity;

      for (let i = 0; i < model.numLinks; i++) {
        b[17 + i] = q[i];
        b[20 + i] = v.length === 0 ? 0 : v[i];
        b[24 + i] = tau.length === 0 ? 0 : tau[i];
        b[28 + i] = target.length === 0 ? 0 : target[i];
      }
      b[23] = t;
      b[27] = dt;
      b[31] = tauMax;
      b[32] = motors ? 1.0 : 0.0;
    }

    function evaluate(op) {
      const status = e.mini_tree_eval(op, scratchPtr, 64);
      if (status !== 0) {
        const msgs = [
          '',
          'Invalid tree physics input parameters or dimensions.',
          'Tree mass matrix is singular or non-positive-definite.',
          'Numerical divergence in tree physics integration.'
        ];
        throw new Error(msgs[status] || `Tree physics error code ${status}`);
      }
    }

    const api = {
      BACKEND: 'cpp-wasm-tree',
      ABI: 2,
      BUILD: build,

      terms(model, q, v = []) {
        packInputs(model, q, v, 0, [], 0, [], 0, false);
        evaluate(0);
        const n = model.numLinks;
        // M matrix: M00, M01, M02, M11, M12, M22
        const rawM = Array.from(b.subarray(34, 40));
        const M = [];
        if (n === 1) {
          M.push([rawM[0]]);
        } else if (n === 2) {
          M.push([rawM[0], rawM[1]]);
          M.push([rawM[1], rawM[3]]);
        } else {
          M.push([rawM[0], rawM[1], rawM[2]]);
          M.push([rawM[1], rawM[3], rawM[4]]);
          M.push([rawM[2], rawM[4], rawM[5]]);
        }
        const coriolis = Array.from(b.subarray(40, 40 + n));
        const gravity = Array.from(b.subarray(43, 43 + n));
        return { M, coriolis, gravity };
      },

      acceleration(model, q, v, tau = []) {
        packInputs(model, q, v, 0, tau, 0, [], 0, false);
        evaluate(1);
        return Array.from(b.subarray(34, 34 + model.numLinks));
      },

      step(model, q, v, t, tau, dt) {
        packInputs(model, q, v, t, tau, dt, [], 0, false);
        evaluate(2);
        const n = model.numLinks;
        return {
          q: Array.from(b.subarray(34, 34 + n)),
          v: Array.from(b.subarray(37, 37 + n)),
          t: b[40]
        };
      },

      forward(model, q) {
        packInputs(model, q, [], 0, [], 0, [], 0, false);
        evaluate(3);
        const n = model.numLinks;
        const pts = [];
        for (let i = 0; i <= n; i++) {
          pts.push({ x: b[34 + 2 * i], y: b[35 + 2 * i], z: 0 });
        }
        return {
          origin: pts[0],
          joints: pts.slice(1),
          tip: pts[pts.length - 1]
        };
      },

      energy(model, q, v) {
        packInputs(model, q, v, 0, [], 0, [], 0, false);
        evaluate(4);
        return {
          kinetic: b[34],
          potential: b[35],
          total: b[36]
        };
      },

      jacobian(model, q) {
        packInputs(model, q, [], 0, [], 0, [], 0, false);
        evaluate(5);
        const n = model.numLinks;
        return {
          Jx: Array.from(b.subarray(34, 34 + n)),
          Jy: Array.from(b.subarray(37, 37 + n))
        };
      },

      stepControlled(model, q, v, t, dt, target, tauMax = 16.0, motors = true) {
        validateVector(target, model.numLinks, 'target');
        packInputs(model, q, v, t, [], dt, target, tauMax, motors);
        evaluate(6);
        const n = model.numLinks;
        return {
          q: Array.from(b.subarray(34, 34 + n)),
          v: Array.from(b.subarray(37, 37 + n)),
          t: b[40],
          appliedTau: Array.from(b.subarray(41, 41 + n))
        };
      }
    };

    return Object.freeze(api);
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { create };
  } else {
    root.MiniTreePhysicsWasm = { create };
  }
})(globalThis);
