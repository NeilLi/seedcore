// CW-G01 candidate/preparation slice only. No live admission/claim/dispatch acceptance.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/robotics/cw-g01');
const python=process.env.SEEDCORE_TEST_PYTHON||(fs.existsSync(path.join(root,'.venv/bin/python'))?path.join(root,'.venv/bin/python'):'python3');
const browser=process.argv.includes('--browser');
const report={review_id:'CW-AUTH-01-PREP',scope:'offline_simulation_candidate_and_policy_preparation',physical_acceptance:false,
  execution_authority:'none',live_admission_verified:false,dispatch_available:false,browser_included:browser,checks:[]};
function run(label,command,args,env={}){
  const r=spawnSync(command,args,{cwd:root,encoding:'utf8',env:{...process.env,SEEDCORE_TEST_PYTHON:python,...env},maxBuffer:16*1024*1024});
  process.stdout.write(r.stdout||'');process.stderr.write(r.stderr||'');
  const count=r.stdout?.match(/(?:# tests|ℹ tests) (\d+)/)||r.stdout?.match(/(\d+) passed/);
  report.checks.push({label,exit_code:r.status,tests:count?Number(count[1]):null});
  if(r.status!==0)throw Error(`${label} failed: ${r.error?.message||r.status}`);
}
try{
  fs.mkdirSync(out,{recursive:true});
  for(const name of ['browser-verification.json','browser-candidate.json'])fs.rmSync(path.join(out,name),{force:true});
  for(const workspace of ['contracts','drc-solver','wasm-sim-bridge','robot-canvas','mini-studio']){
    fs.rmSync(path.join(root,`ts/${workspace==='mini-studio'?'apps':'packages'}/${workspace}/dist`),{recursive:true,force:true});
    run(`${workspace} source build`,'npm',['--prefix','ts','run','--workspace',`@seedcore/${workspace}`,'build']);
  }
  run('workspace typecheck','npm',['--prefix','ts','run','typecheck']);
  run('candidate identity, full-curve bounds and edit refusal',path.join(root,'ts/node_modules/.bin/tsx'),['--test','ts/tests/build-admission.test.ts']);
  run('fresh compiler-generated candidate',path.join(root,'ts/node_modules/.bin/tsx'),['tools/robotics/export-cw-g01.ts',out]);
  run('Python intake, per-joint intersection and existing PDP denials',python,['-m','pytest','tests/test_cw_g01_admission.py','-q','--tb=short'],
    {SEEDCORE_CW_G01_CANDIDATE:path.join(out,'candidate.json')});
  if(browser){
    run('CW-S04/native/full Studio browser regressions',process.execPath,['tools/robotics/verify-cw-s04.cjs','--browser']);
    const b=JSON.parse(fs.readFileSync(path.join(out,'browser-verification.json'),'utf8'));
    if(b.status!=='checks_passed'||b.physicalAcceptance!==false||b.executionAuthority!=='none'||b.admissionRequests!==0||b.dispatchAvailable!==false)
      throw Error('Missing candidate-only browser evidence');
    run('actual Chrome download parsed independently in Python',python,['-m','pytest','tests/test_cw_g01_admission.py','-q','-k','actual_browser_export','--tb=short'],
      {SEEDCORE_CW_G01_BROWSER_CANDIDATE:path.join(out,'browser-candidate.json')});
  }
  const candidate=JSON.parse(fs.readFileSync(path.join(out,'candidate.json'),'utf8'));
  report.candidate_digest=candidate.candidateDigest;
  report.runtime=candidate.runtime;
  report.remaining=['trusted service/Agent intake and registered profile resolution','live PDP allow/token verification at the actual adapter',
    'durable claim, revocation/refresh and per-substep dispatch enforcement','negative token/claim/dispatch matrix; physical qualification remains separate'];
  report.status=browser?'checks_passed':'checks_passed_browser_not_run';
}catch(e){report.status='checks_failed';report.failure=e.message;process.exitCode=1;}
finally{
  report.source_revision=spawnSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).stdout.trim();
  report.working_tree_dirty=Boolean(spawnSync('git',['status','--porcelain'],{cwd:root,encoding:'utf8'}).stdout.trim());
  const files=spawnSync('git',['ls-files','--cached','--others','--exclude-standard'],{cwd:root,encoding:'utf8'}).stdout.trim().split('\n');
  const prefixes=['src/seedcore/robotics/build_admission.py','src/seedcore/robotics/assembly.py','src/seedcore/robotics/component_registry.py',
    'src/seedcore/coordinator/core/governance.py','src/seedcore/models/action_intent.py','tests/test_cw_g01_admission.py','ts/tests/build-admission.test.ts',
    'tools/robotics/export-cw-g01.ts','tools/robotics/verify-cw-g01.cjs','tools/robotics/verify-authoring.cjs','ts/packages/wasm-sim-bridge/',
    'ts/apps/mini-studio/','ts/packages/contracts/src/','ts/packages/drc-solver/src/','ts/tests/fixtures/cw-s01.ts',
    'packages/simulation-fixtures/cw-s01/','docs/development/robotics/central_world_cw_g01_admission.md','.github/workflows/unit-tests.yml'];
  const hash=p=>({path:p,sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(root,p))).digest('hex')});
  report.inputs=files.filter(p=>prefixes.some(prefix=>p.startsWith(prefix))&&fs.statSync(path.join(root,p)).isFile()).map(hash);
  report.outputs=['artifacts/robotics/cw-g01/candidate.json','artifacts/robotics/cw-g01/browser-candidate.json',
    'artifacts/robotics/cw-g01/browser-verification.json','ts/apps/mini-studio/dist/app.js','ts/apps/mini-studio/dist/index.html'].filter(p=>fs.existsSync(path.join(root,p))).map(hash);
  fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,'verification.json'),JSON.stringify(report,null,2)+'\n');
  console.log(`CW-AUTH-01-PREP: ${report.status}; live admission remains open; artifacts/robotics/cw-g01/verification.json`);
}
