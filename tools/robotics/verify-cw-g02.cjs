// CW-G02 Python evidence foundation only. No Rust CW receipt adapter/browser acceptance.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/robotics/cw-g02');
const python=process.env.SEEDCORE_TEST_PYTHON||(fs.existsSync(path.join(root,'.venv/bin/python'))?path.join(root,'.venv/bin/python'):'python3');
const report={review_id:'CW-G02-PYTHON-FOUNDATION',scope:'local_simulation_only',physical_acceptance:false,
  execution_authority:'none',rust_cw_receipt_adapter:false,browser_included:false,checks:[]};
function run(label,command,args){
  const r=spawnSync(command,args,{cwd:root,encoding:'utf8',maxBuffer:16*1024*1024,env:{...process.env,
    SEEDCORE_CW_G01_REQUIRE_NATIVE:'1',SEEDCORE_CW_G02_REQUIRE_NATIVE:'1',
    SEEDCORE_VERIFY_BIN:path.join(root,'rust/target/debug/seedcore-verify')}});
  process.stdout.write(r.stdout||'');process.stderr.write(r.stderr||'');
  const count=r.stdout?.match(/(\d+) passed/);
  report.checks.push({label,exit_code:r.status,tests:count?Number(count[1]):null});
  if(r.status!==0)throw Error(`${label} failed: ${r.error?.message||r.status}`);
}
try{
  fs.mkdirSync(out,{recursive:true});
  for(const workspace of ['contracts','drc-solver','wasm-sim-bridge']){
    fs.rmSync(path.join(root,'ts/packages',workspace,'dist'),{recursive:true,force:true});
    run(`${workspace} source build`,'npm',['--prefix','ts','run','--workspace',`@seedcore/${workspace}`,'build']);
  }
  run('existing Rust token verifier build','cargo',['build','--manifest-path',path.join(root,'rust/Cargo.toml'),'--locked','-p','seedcore-verify']);
  run('CW-G02 original exports, independent CLI, trust and semantic refusals',python,['-m','pytest','tests/test_cw_g02_evidence.py','-q','--tb=short']);
  run('CW-G01 admission/native and existing Fast Spine receipt regressions',python,['-m','pytest',
    'tests/test_cw_g01_runtime.py','tests/test_cw_g01_admission.py','tests/test_fast_spine_sessions.py','tests/test_fast_spine_rust.py','-q','--tb=short']);
  run('fresh compiler source fixture',path.join(root,'ts/node_modules/.bin/tsx'),['tools/robotics/export-cw-g01.ts',path.join(out,'source')]);
  run('retain actual PDP/native signed exports and quarantine fixtures',python,['tools/robotics/export-cw-g02-evidence.py',
    '--source',path.join(out,'source/endpoint-source.json'),'--out',out]);
  report.status='checks_passed';
}catch(error){report.status='checks_failed';report.failure=error.message;process.exitCode=1;}
finally{
  report.source_revision=spawnSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).stdout.trim();
  report.working_tree_dirty=Boolean(spawnSync('git',['status','--porcelain'],{cwd:root,encoding:'utf8'}).stdout.trim());
  const files=spawnSync('git',['ls-files','--cached','--others','--exclude-standard'],{cwd:root,encoding:'utf8'}).stdout.trim().split('\n');
  const prefixes=['src/seedcore/robotics/cw_','src/seedcore/robotics/fast_spine/','src/seedcore/robotics/build_admission.py',
    'src/seedcore/robotics/assembly.py','src/seedcore/robotics/component_registry.py','src/seedcore/coordinator/core/governance.py',
    'src/seedcore/integrations/rust_kernel.py','src/seedcore/models/action_intent.py','src/seedcore/robotics/mini_studio_api.py',
    'tests/test_cw_g0','tests/test_fast_spine','tools/robotics/cw_g01_test_fixture.py','tools/robotics/export-cw-g0',
    'tools/robotics/verify-cw-g02.cjs','ts/packages/contracts/','ts/packages/drc-solver/','ts/packages/wasm-sim-bridge/',
    'ts/tests/fixtures/cw-s01.ts','packages/simulation-fixtures/cw-s01/','rust/Cargo',
    'rust/crates/seedcore-verify/','rust/crates/seedcore-token-core/','rust/crates/seedcore-proof-core/','rust/crates/seedcore-kernel-types/',
    'docs/development/robotics/central_world_cw_g02_evidence.md','.github/workflows/unit-tests.yml'];
  const hash=p=>({path:p,sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(root,p))).digest('hex')});
  report.inputs=files.filter(p=>prefixes.some(prefix=>p.startsWith(prefix))&&fs.statSync(path.join(root,p)).isFile()).map(hash);
  const outputs=[];
  function collect(directory){for(const item of fs.readdirSync(directory,{withFileTypes:true})){
    const file=path.join(directory,item.name);if(item.isDirectory())collect(file);
    else if(item.isFile()&&file!==path.join(out,'verification.json'))outputs.push(path.relative(root,file));
  }}
  collect(out);report.outputs=outputs.sort().map(hash);
  fs.writeFileSync(path.join(out,'verification.json'),JSON.stringify(report,null,2)+'\n');
  console.log(`CW-G02 Python foundation: ${report.status}; Rust/Studio/browser and physical gates remain open.`);
}
