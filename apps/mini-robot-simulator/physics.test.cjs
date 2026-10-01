const test = require('node:test');
const assert = require('node:assert/strict');
const P = require('./physics.js');
const close = (a,b,tolerance=1e-8) => assert.ok(Math.abs(a-b)<tolerance, `${a} != ${b} (tolerance ${tolerance})`);
function simulate(model, state, torque, duration, dt=1/480) {
  for(let i=0;i<Math.round(duration/dt);i++) state=P.step(model,state,torque,dt);
  return state;
}
test('forward kinematics preserves lengths for folded and extended arms',()=>{
  const m=P.createModel();
  const p=P.forward(m,[0,0]);close(p.tip[0],1.35);close(p.tip[1],0);
  for(let a=-3;a<3;a+=.21){const p=P.forward(m,[a,a/2]);close(Math.hypot(...p.elbow),m.l1);close(Math.hypot(p.tip[0]-p.elbow[0],p.tip[1]-p.elbow[1]),m.l2);}
});
test('mass matrix is positive definite across relative joint angles',()=>{
  const m=P.createModel();for(let q=-Math.PI;q<Math.PI;q+=.02){const [a,b,d]=P.terms(m,[0,q]).mass;assert.ok(a>0&&d>0&&a*d-b*b>0);}
});
test('gravity is the gradient of potential energy',()=>{
  const m=P.createModel(),q=[.37,-.83],epsilon=1e-6,g=P.terms(m,q).gravity;
  for(let i=0;i<2;i++){const plus=[...q],minus=[...q];plus[i]+=epsilon;minus[i]-=epsilon;close((P.energy(m,P.createState(plus)).potential-P.energy(m,P.createState(minus)).potential)/(2*epsilon),g[i],1e-7);}
});
test('Coriolis terms satisfy the kinetic energy identity',()=>{
  const m=P.createModel(),q=[.4,-.7],v=[1.2,-.3],eps=1e-6;
  const plus=P.terms(m,q.map((x,i)=>x+eps*v[i])).mass,minus=P.terms(m,q.map((x,i)=>x-eps*v[i])).mass;
  const mdot=plus.map((x,i)=>(x-minus[i])/(2*eps));
  const c=P.terms(m,q,v).coriolis;
  close(v[0]*c[0]+v[1]*c[1],.5*(mdot[0]*v[0]**2+2*mdot[1]*v[0]*v[1]+mdot[2]*v[1]**2),1e-8);
});
test('gravity-compensating torque maintains an arbitrary resting pose',()=>{
  const m=P.createModel(),s=P.createState([.3,-.9]);
  const end=simulate(m,s,P.terms(m,s.q).gravity,1);
  end.q.forEach((v,i)=>close(v,s.q[i]));end.velocity.forEach(v=>close(v,0));
});
test('unforced undamped motion conserves energy within the declared numerical tolerance',()=>{
  const m=P.createModel({damping:0}),s=P.createState([.6,-.9],[.3,-.2]);
  const start=P.energy(m,s).total,end=simulate(m,s,[0,0],2,1/960);
  close(P.energy(m,end).total,start,1e-5);
});
test('viscous damping dissipates mechanical energy without motor input',()=>{
  const m=P.createModel({damping:.5}),s=P.createState([.6,-.9],[.3,-.2]);
  assert.ok(P.energy(m,simulate(m,s,[0,0],2)).total < P.energy(m,s).total);
});
test('controlled arm reaches the lesson target with low terminal velocity',()=>{
  const m=P.createModel(),target=[55*Math.PI/180,-70*Math.PI/180],s=P.createState([15*Math.PI/180,45*Math.PI/180]);
  const end=simulate(m,s,x=>P.motor(m,x,target,16),6);
  end.q.forEach((v,i)=>close(v,target[i],.01));end.velocity.forEach(v=>close(v,0,.01));
});
test('motor output respects limits and its initial acceleration matches external work',()=>{
  const m=P.createModel(),s=P.createState([0,0]),u=P.motor(m,s,[2,2],2);
  assert.ok(u.every(v=>Math.abs(v)<=2));
  const torque=[2,-1],a=P.acceleration(m,s,torque),[m00,m01,m11]=P.terms(m,s.q).mass,g=P.terms(m,s.q).gravity;
  close(m00*a[0]+m01*a[1]+g[0],torque[0]);close(m01*a[0]+m11*a[1]+g[1],torque[1]);
});
test('step refinement converges on a smooth trajectory',()=>{
  const m=P.createModel({damping:0}),s=P.createState([.3,-.1],[.1,.2]);
  const end=(dt)=>simulate(m,s,[.2,-.1],.5,dt);
  const ref=end(1/7680),error=(e)=>Math.hypot(...e.q.map((x,i)=>x-ref.q[i]),...e.velocity.map((x,i)=>x-ref.velocity[i]));
  assert.ok(error(end(1/960)) < error(end(1/240))/8);
});
test('identical runs reproduce state, and stepping leaves the input snapshot unchanged',()=>{
  const m=P.createModel(),s=P.createState([.1,.2]),copy=JSON.stringify(s);
  assert.deepEqual(simulate(m,s,[0,0],.2),simulate(m,s,[0,0],.2));assert.equal(JSON.stringify(s),copy);assert.ok(Object.isFrozen(m));
});
test('invalid inputs stop explicitly rather than silently generating a trajectory',()=>{
  assert.throws(()=>P.createModel({m1:0}));assert.throws(()=>P.createModel({l1:NaN}));assert.throws(()=>P.createState([Infinity,0]));
  const m=P.createModel(),s=P.createState();assert.throws(()=>P.step(m,s,[0,0],0));assert.throws(()=>P.step(m,s,[0,0],1));assert.throws(()=>P.step(m,s,[NaN,0],1/480));
});
