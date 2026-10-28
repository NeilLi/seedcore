// CW-MOM-01 source build, analytic refusal matrix, native parity and optional shipped-browser checks.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/robotics/cw-s04');
const python=process.env.SEEDCORE_TEST_PYTHON||(fs.existsSync(path.join(root,'.venv/bin/python'))?path.join(root,'.venv/bin/python'):'python3');
const browser=process.argv.includes('--browser');
const report={review_id:'CW-MOM-01',scope:'offline_simulation_only',physical_acceptance:false,execution_authority:'none',
  native_included:true,browser_included:browser,profile:{timestep_seconds:0.002,position_gain:1,max_joints:3,max_assembly_bodies:5,max_ticks:120,max_duration_seconds:0.24},checks:[]};
function run(label,command,args,env={}){
  const r=spawnSync(command,args,{cwd:root,encoding:'utf8',env:{...process.env,SEEDCORE_TEST_PYTHON:python,...env},maxBuffer:16*1024*1024});
  process.stdout.write(r.stdout||'');process.stderr.write(r.stderr||'');
  const count=r.stdout?.match(/(?:# tests|ℹ tests) (\d+)/)||r.stdout?.match(/(\d+) passed/);
  report.checks.push({label,exit_code:r.status,tests:count?Number(count[1]):null});
  if(r.status!==0)throw Error(`${label} failed: ${r.error?.message||r.status}`);
}
try{
  fs.mkdirSync(out,{recursive:true});
  for(const name of ['browser-verification.json','browser-replay.json','moments-inspector.png'])fs.rmSync(path.join(out,name),{force:true});
  fs.rmSync(path.join(out,'models'),{recursive:true,force:true});
  for(const workspace of ['contracts','drc-solver','wasm-sim-bridge','robot-canvas','mini-studio']){
    fs.rmSync(path.join(root,`ts/${workspace==='mini-studio'?'apps':'packages'}/${workspace}/dist`),{recursive:true,force:true});
    run(`${workspace} source build`,'npm',['--prefix','ts','run','--workspace',`@seedcore/${workspace}`,'build']);
  }
  run('gesture/Studio typecheck','npm',['--prefix','ts','run','typecheck']);
  run('CW-S04 curve, binding, replay and interruption matrix',path.join(root,'ts/node_modules/.bin/tsx'),['--test','ts/tests/gesture-cw-s04.test.ts']);
  run('export seven real Wasm gesture captures',path.join(root,'ts/node_modules/.bin/tsx'),['tools/robotics/export-cw-s04.ts',path.join(out,'models')]);
  run('independent native Hermite/120-step parity',python,['-m','pytest','tests/test_cw_s04_parity.py','-q','--tb=short'],
    {SEEDCORE_CW_S04_REQUIRE_NATIVE:'1',SEEDCORE_CW_S04_CASES_DIR:path.join(out,'models')});
  if(browser){
    run('full Studio source/browser regression',process.execPath,['tools/robotics/verify-authoring.cjs','--browser']);
    const b=JSON.parse(fs.readFileSync(path.join(out,'browser-verification.json'),'utf8'));
    if(b.status!=='checks_passed'||b.physicalAcceptance!==false||b.executionAuthority!=='none')throw Error('Missing CW-S04 browser acceptance');
  }
  const cases=JSON.parse(fs.readFileSync(path.join(out,'models/cases.json'),'utf8'));
  report.cases=cases.cases.map(c=>({name:c.name,model_digest:c.model.modelDigest,gesture_digest:c.replay.gesture.gestureDigest,
    trace_digest:c.replay.summary.traceDigest,captured_ticks:c.replay.samples.length}));
  report.starter_blocked=cases.starter.disposition==='blocked'&&!cases.starter.readiness.ready;
  if(!report.starter_blocked)throw Error('Actual starter readiness changed');
  report.status=browser?'checks_passed':'checks_passed_browser_not_run';
}catch(e){report.status='checks_failed';report.failure=e.message;process.exitCode=1;}
finally{
  report.source_revision=spawnSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).stdout.trim();
  report.working_tree_dirty=Boolean(spawnSync('git',['status','--porcelain'],{cwd:root,encoding:'utf8'}).stdout.trim());
  const files=spawnSync('git',['ls-files','--cached','--others','--exclude-standard'],{cwd:root,encoding:'utf8'}).stdout.trim().split('\n');
  const prefixes=['tools/robotics/verify-cw-s04.cjs','tools/robotics/export-cw-s04.ts','tools/robotics/verify-authoring.cjs','ts/packages/wasm-sim-bridge/',
    'ts/packages/contracts/src/','ts/packages/drc-solver/src/','ts/apps/mini-studio/','ts/tests/gesture-cw-s04.test.ts','ts/tests/fixtures/cw-s01.ts',
    'tests/test_cw_s04_parity.py','packages/simulation-fixtures/cw-s01/','ts/package-lock.json','.github/workflows/unit-tests.yml'];
  const digest=p=>({path:p,sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(root,p))).digest('hex')});
  report.inputs=files.filter(p=>prefixes.some(prefix=>p.startsWith(prefix))&&fs.statSync(path.join(root,p)).isFile()).map(digest);
  report.outputs=['artifacts/robotics/cw-s04/models/cases.json','artifacts/robotics/cw-s04/browser-verification.json','artifacts/robotics/cw-s04/browser-replay.json',
    'ts/apps/mini-studio/dist/app.js','ts/apps/mini-studio/dist/cw-s02-worker.js'].filter(p=>fs.existsSync(path.join(root,p))).map(digest);
  fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,'verification.json'),JSON.stringify(report,null,2)+'\n');
  console.log(`CW-MOM-01: ${report.status}; artifacts/robotics/cw-s04/verification.json`);
}
