/* Owned C++ f64 core. JS reference supplies only validation and callback bridge.
 * Prepared lessons use stepControlled: controller and every RK4 stage are C++.
 * Each adapter owns separate Wasm memory. Live memory is never transferred.
 */
(function(root) {
  'use strict';
  const reference = root.MiniRobotPhysics || (typeof require === 'function' ? require('./physics.js') : null);
  function create(bytes, build) {
    const module = new WebAssembly.Module(bytes);
    const instance = new WebAssembly.Instance(module, {env:{sin:Math.sin,cos:Math.cos}});
    const e=instance.exports;
    if(e.mini_abi()!==1) throw new Error('Unsupported physics ABI.');
    const b=new Float64Array(e.memory.buffer,e.mini_scratch(),32);
    function evaluate(op,m,s,extra=[]) {
      reference.createState(s.q,s.velocity,s.time);
      b.fill(0); b.set([m.l1,m.l2,m.m1,m.m2,m.gravity,m.damping,...s.q,...s.velocity,s.time]);
      b.set(extra,11);
      const status=e.mini_eval(op,e.mini_scratch(),32);
      if(status!==0) throw new Error(['','Invalid physics input.','Mass matrix is singular at this scale.','Numerical divergence: experiment stopped.'][status] || 'Physics failure.');
      return Array.from(b.subarray(20,27));
    }
    const api={...reference, BACKEND:'cpp-wasm', BUILD:build,
      terms(m,q,v=[0,0]) {const a=evaluate(0,m,reference.createState(q,v));return {mass:a.slice(0,3),coriolis:a.slice(3,5),gravity:a.slice(5,7)};},
      acceleration(m,s,u) {if(!Array.isArray(u)||u.length!==2) throw new Error('Invalid torque.');return evaluate(1,m,s,u).slice(0,2);},
      forward(m,q) {const a=evaluate(3,m,reference.createState(q));return {elbow:a.slice(0,2),tip:a.slice(2,4)};},
      energy(m,s) {const a=evaluate(4,m,s);return {kinetic:a[0],potential:a[1],total:a[2]};},
      motor(m,s,target,limit=16) {reference.motor(m,s,target,limit);return evaluate(5,m,s,[0,0,0,...target,limit]).slice(0,2);},
      step(m,s,u,dt) {
        if(typeof u==='function') {
          // General JS callbacks remain developer reference compatibility only.
          const y=[...s.q,...s.velocity];
          const derivative=(v,t)=>{const z=reference.createState(v.slice(0,2),v.slice(2),t);return [...z.velocity,...api.acceleration(m,z,u(z))];};
          if(!Number.isFinite(dt)||dt<=0||dt>1/120) throw new Error('Invalid timestep.');
          const add=(k,f)=>y.map((v,i)=>v+k[i]*f);
          const a=derivative(y,s.time),c=derivative(add(a,dt/2),s.time+dt/2),d=derivative(add(c,dt/2),s.time+dt/2),f=derivative(add(d,dt),s.time+dt);
          const next=y.map((v,i)=>v+dt*(a[i]+2*c[i]+2*d[i]+f[i])/6);
          if(next.some(v=>!Number.isFinite(v)||Math.abs(v)>1e6)) throw new Error('Numerical divergence.');
          return reference.createState(next.slice(0,2),next.slice(2),s.time+dt);
        }
        if(!Array.isArray(u)||u.length!==2) throw new Error('Invalid torque.');
        const a=evaluate(2,m,s,[...u,dt]);return reference.createState(a.slice(0,2),a.slice(2,4),a[4]);
      },
      stepControlled(m,s,control,dt) {
        reference.motor(m,s,control.target,control.strength);
        if(typeof control.motors!=='boolean') throw new Error('Invalid motor switch.');
        const a=evaluate(6,m,s,[0,0,dt,...control.target,control.strength,Number(control.motors)]);
        return reference.createState(a.slice(0,2),a.slice(2,4),a[4]);
      }
    };
    return Object.freeze(api);
  }
  if(typeof module!=='undefined' && module.exports) module.exports={create};
  else root.MiniPhysicsWasm={create};
})(globalThis);
