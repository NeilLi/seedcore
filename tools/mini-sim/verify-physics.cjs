const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict');
const {spawnSync}=require('node:child_process'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'../..'), temp=fs.mkdtempSync(path.join(os.tmpdir(),'mini-physics-test-'));
const P=require('../../apps/mini-robot-simulator/physics.js');
const build=require('../../apps/mini-robot-simulator/physics-build.json');
const bytes=fs.readFileSync(path.join(root,'apps/mini-robot-simulator/mini-physics.wasm'));
assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),build.sha256);
assert.equal(bytes.length,build.bytes);
const W=require('../../apps/mini-robot-simulator/physics-wasm.js').create(bytes,build);
const cxx=process.env.MINI_CXX || 'clang++';
function run(exe,args,options={}) {
  const r=spawnSync(exe,args,{cwd:root,encoding:'utf8',maxBuffer:8*1024*1024,...options});
  if(r.error || r.status!==0) throw r.error || new Error(`${exe}: ${r.stderr}\n${r.stdout}`);
  return r.stdout;
}
try {
  const common=['-std=c++17','-O2','-ffp-contract=off','-fno-fast-math','-Ipackages/mini-physics/include','packages/mini-physics/src/mini_physics.cpp'];
  const cli=path.join(temp,'cli'),invariants=path.join(temp,'invariants');
  run(cxx,[...common,'packages/mini-physics/src/native_cli.cpp','-o',cli]);
  run(cxx,[...common,'packages/mini-physics/src/native_tests.cpp','-o',invariants]);
  console.log(run(invariants,[]).trim());
  run(process.execPath,['--test','apps/mini-robot-simulator/physics.test.cjs'],{env:{...process.env,MINI_TEST_WASM:'1'}});
  const results=[];
  for(const [lesson,mass,strength,motors] of [['reach',.7,16,true],['gravity',.7,16,false],['heavy',1.8,5,true]]) {
    const m=P.createModel({m2:mass}),control={target:[55*Math.PI/180,-70*Math.PI/180],strength,motors};
    let js=P.createState([15*Math.PI/180,45*Math.PI/180]),wasm=structuredClone(js);
    const buffer=[m.l1,m.l2,m.m1,m.m2,m.gravity,m.damping,...js.q,...js.velocity,js.time,0,0,1/480,...control.target,strength,Number(motors)];
    const trace=run(cli,['--trace'],{input:'6 '+buffer.join(' ')+'\n'}).trim().split('\n');
    assert.equal(trace.length,2880);
    let nativeError=0,wasmError=0;
    for(let tick=0;tick<2880;tick++) {
      js=P.step(m,js,s=>motors ? P.motor(m,s,control.target,strength) : [0,0],1/480);
      wasm=W.stepControlled(m,wasm,control,1/480);
      const [status,...native]=trace[tick].split(' ').map(Number);assert.equal(status,0);
      const expected=[...js.q,...js.velocity,js.time],actual=[...wasm.q,...wasm.velocity,wasm.time];
      for(let i=0;i<5;i++) {nativeError=Math.max(nativeError,Math.abs(expected[i]-native[i]));wasmError=Math.max(wasmError,Math.abs(expected[i]-actual[i]));}
    }
    assert.ok(nativeError<1e-8 && wasmError<1e-8);
    results.push({lesson,ticks:2880,nativeMaxAbsoluteError:nativeError,wasmMaxAbsoluteError:wasmError});
  }
  const module=new WebAssembly.Module(bytes),e=new WebAssembly.Instance(module,{env:{sin:Math.sin,cos:Math.cos}}).exports;
  const b=new Float64Array(e.memory.buffer,e.mini_scratch(),32);b.fill(0);b[20]=123;
  assert.equal(e.mini_eval(0,e.mini_scratch(),31),1);assert.equal(b[20],123);
  assert.equal(e.memory.buffer.byteLength,131072);assert.throws(()=>e.memory.grow(1));
  const report={schema:'seedcore.mini-physics.qualification.v1',date:new Date().toISOString(),platform:`${os.platform()} ${os.release()} ${os.arch()}`,node:process.version,build,
    tolerance:1e-8,units:'radians, rad/s, seconds (maximum over q, velocity, time)',nativeInvariantGroups:12,wasmInvariants:12,results};
  if(process.argv.includes('--report')) fs.writeFileSync(path.join(root,'tools/mini-sim/physics-qualification.json'),JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report,null,2));
} finally { fs.rmSync(temp,{recursive:true,force:true}); }
