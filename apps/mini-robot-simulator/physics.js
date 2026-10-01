/* SeedCore Mini Physics 0.1: planar, fixed-base, two-link rigid arm.
 * SI units. q1 is measured from +x; q2 is relative to link 1; +y is up.
 * Uniform rods, viscous damping, torque actuation, no contacts/joint stops.
 * Independent of the DOM and of any external physics library.
 */
(function (root) {
  'use strict';
  const VERSION = '0.1.0-planar-arm';
  const finite = (x) => typeof x === 'number' && Number.isFinite(x);
  function pair(value, name) {
    if (!Array.isArray(value) || value.length !== 2 || !value.every(finite)) {
      throw new Error(`${name} must contain two finite numbers.`);
    }
  }
  function createModel(options = {}) {
    const model = { l1: 0.75, l2: 0.6, m1: 1, m2: 0.7, gravity: 9.81, damping: 0.12, ...options };
    for (const key of ['l1', 'l2', 'm1', 'm2']) {
      if (!finite(model[key]) || model[key] <= 0 || model[key] > 10) {
        throw new Error(`${key} must be positive and at most 10 in this research profile.`);
      }
    }
    for (const key of ['gravity', 'damping']) {
      if (!finite(model[key]) || model[key] < 0 || model[key] > 100) throw new Error(`Invalid ${key}.`);
    }
    model.c1 = model.l1 / 2;
    model.c2 = model.l2 / 2;
    model.i1 = model.m1 * model.l1 ** 2 / 12;
    model.i2 = model.m2 * model.l2 ** 2 / 12;
    return Object.freeze(model);
  }
  function createState(q = [0, 0], velocity = [0, 0], time = 0) {
    pair(q, 'Joint positions'); pair(velocity, 'Joint velocities');
    if (!finite(time) || time < 0) throw new Error('Invalid simulation time.');
    return { q: [...q], velocity: [...velocity], time };
  }
  function terms(m, q, v = [0, 0]) {
    pair(q, 'Joint positions'); pair(v, 'Joint velocities');
    const b = m.m2 * m.l1 * m.c2;
    const d = m.i2 + m.m2 * m.c2 ** 2;
    const a = m.i1 + m.m1 * m.c1 ** 2 + m.m2 * m.l1 ** 2 + d;
    const h = b * Math.sin(q[1]);
    const common = m.m2 * m.c2 * m.gravity * Math.cos(q[0] + q[1]);
    return {
      mass: [a + 2 * b * Math.cos(q[1]), d + b * Math.cos(q[1]), d],
      coriolis: [-h * (2 * v[0] * v[1] + v[1] ** 2), h * v[0] ** 2],
      gravity: [(m.m1 * m.c1 + m.m2 * m.l1) * m.gravity * Math.cos(q[0]) + common, common],
    };
  }
  function acceleration(m, state, torque) {
    pair(torque, 'Motor torque');
    const { mass: [a, b, d], coriolis: c, gravity: g } = terms(m, state.q, state.velocity);
    const determinant = a * d - b * b;
    if (!(determinant > 1e-14)) throw new Error('Mass matrix is singular at this scale.');
    const r0 = torque[0] - c[0] - g[0] - m.damping * state.velocity[0];
    const r1 = torque[1] - c[1] - g[1] - m.damping * state.velocity[1];
    return [(d * r0 - b * r1) / determinant, (a * r1 - b * r0) / determinant];
  }
  function step(m, state, torque, dt) {
    if (!finite(dt) || dt <= 0 || dt > 1 / 120) throw new Error('Step must be in (0, 1/120] seconds.');
    createState(state.q, state.velocity, state.time);
    const initial = [...state.q, ...state.velocity];
    function derivative(y, time) {
      const s = { q: y.slice(0, 2), velocity: y.slice(2), time };
      const u = typeof torque === 'function' ? torque(s) : torque;
      return [...s.velocity, ...acceleration(m, s, u)];
    }
    const add = (base, delta, factor) => base.map((v, i) => v + delta[i] * factor);
    // Classical RK4 for this smooth, contact-free dynamics problem.
    const k1 = derivative(initial, state.time);
    const k2 = derivative(add(initial, k1, dt / 2), state.time + dt / 2);
    const k3 = derivative(add(initial, k2, dt / 2), state.time + dt / 2);
    const k4 = derivative(add(initial, k3, dt), state.time + dt);
    const next = initial.map((v, i) => v + dt * (k1[i] + 2 * k2[i] + 2 * k3[i] + k4[i]) / 6);
    if (!next.every(finite) || next.some((v) => Math.abs(v) > 1e6)) {
      throw new Error('Numerical divergence: experiment stopped.');
    }
    return createState(next.slice(0, 2), next.slice(2), state.time + dt);
  }
  function forward(m, q) {
    pair(q, 'Joint positions');
    const elbow = [m.l1 * Math.cos(q[0]), m.l1 * Math.sin(q[0])];
    return { elbow, tip: [elbow[0] + m.l2 * Math.cos(q[0] + q[1]), elbow[1] + m.l2 * Math.sin(q[0] + q[1])] };
  }
  function energy(m, state) {
    const [a, b, d] = terms(m, state.q).mass;
    const [v0, v1] = state.velocity;
    const kinetic = (a * v0 * v0 + 2 * b * v0 * v1 + d * v1 * v1) / 2;
    const potential = m.gravity * ((m.m1 * m.c1 + m.m2 * m.l1) * Math.sin(state.q[0]) + m.m2 * m.c2 * Math.sin(state.q[0] + state.q[1]));
    return { kinetic, potential, total: kinetic + potential };
  }
  function motor(m, state, target, limit = 16) {
    pair(target, 'Joint targets');
    if (!finite(limit) || limit <= 0 || limit > 100) throw new Error('Invalid motor limit.');
    const g = terms(m, state.q).gravity;
    // Torque-limited PD with gravity compensation; idealized, not a servo model.
    return state.q.map((q, i) => Math.max(-limit, Math.min(limit, 24 * (target[i] - q) - 5 * state.velocity[i] + g[i])));
  }
  const api = { VERSION, createModel, createState, terms, acceleration, step, forward, energy, motor };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.MiniRobotPhysics = api;
})(globalThis);
