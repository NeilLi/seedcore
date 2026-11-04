// CW-G02 independent verification and optional bounded local Studio/browser evidence.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/robotics/cw-g02');
const python=process.env.SEEDCORE_TEST_PYTHON||(fs.existsSync(path.join(root,'.venv/bin/python'))?path.join(root,'.venv/bin/python'):'python3');
const browser=process.argv.includes('--browser');
const report={review_id:'CW-G02-STUDIO-LOCAL',scope:'local_simulation_only',physical_acceptance:false,
  execution_authority:'none',rust_cw_receipt_adapter:false,parity_included:false,browser_included:browser,studio_browser_verified:false,checks:[]};
function run(label,command,args){
  const r=spawnSync(command,args,{cwd:root,encoding:'utf8',maxBuffer:16*1024*1024,env:{...process.env,
    SEEDCORE_CW_G01_REQUIRE_NATIVE:'1',SEEDCORE_CW_G02_REQUIRE_NATIVE:'1',SEEDCORE_CW_G02_REQUIRE_RUST:'1',
    SEEDCORE_CW_G02_PARITY_OUT:path.join(out,'parity'),
    SEEDCORE_VERIFY_BIN:path.join(root,'rust/target/debug/seedcore-verify')}});
  process.stdout.write(r.stdout||'');process.stderr.write(r.stderr||'');
  const count=r.stdout?.match(/(\d+) passed/);
  const rustCounts=[...(r.stdout||'').matchAll(/test result: ok\. (\d+) passed/g)];
  const composed=command===process.execPath&&args[0]?.endsWith('.cjs');
  report.checks.push({label,exit_code:r.status,tests:composed?null:(rustCounts.length?rustCounts.reduce((n,c)=>n+Number(c[1]),0):(count?Number(count[1]):null))});
  if(r.status!==0)throw Error(`${label} failed: ${r.error?.message||r.status}`);
}
try{
  fs.mkdirSync(out,{recursive:true});
  fs.rmSync(path.join(out,'parity'),{recursive:true,force:true});
  for(const workspace of ['contracts','drc-solver','wasm-sim-bridge']){
    fs.rmSync(path.join(root,'ts/packages',workspace,'dist'),{recursive:true,force:true});
    run(`${workspace} source build`,'npm',['--prefix','ts','run','--workspace',`@seedcore/${workspace}`,'build']);
  }
  run('independent Rust CW verifier source build','cargo',['build','--manifest-path',path.join(root,'rust/Cargo.toml'),'--locked','-p','seedcore-verify']);
  run('Rust CW canonicalization and existing verifier/proof/token/type contracts','cargo',['test','--manifest-path',path.join(root,'rust/Cargo.toml'),'--locked',
    '-p','seedcore-verify','-p','seedcore-proof-core','-p','seedcore-token-core','-p','seedcore-kernel-types']);
  run('CW-G02 independent Python/Rust parity, original exports and semantic refusals',python,['-m','pytest','tests/test_cw_g02_evidence.py','-q','--tb=short']);
  run('Studio trusted context, snapshot, read-only API and verifier failure boundary',python,['-m','pytest','tests/test_cw_g02_studio.py','-q','--tb=short']);
  run('CW-G01 admission/native and existing Fast Spine receipt regressions',python,['-m','pytest',
    'tests/test_cw_g01_runtime.py','tests/test_cw_g01_admission.py','tests/test_fast_spine_sessions.py','tests/test_fast_spine_rust.py','-q','--tb=short']);
  run('fresh compiler source fixture',path.join(root,'ts/node_modules/.bin/tsx'),['tools/robotics/export-cw-g01.ts',path.join(out,'source')]);
  run('retain actual PDP/native signed exports and quarantine fixtures',python,['tools/robotics/export-cw-g02-evidence.py',
    '--source',path.join(out,'source/endpoint-source.json'),'--out',out]);
  report.rust_cw_receipt_adapter=true;report.parity_included=true;
  report.canonical_vectors=JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/cw-g02/canonical.json'),'utf8')).length;
  const parity=[];
  function checkParity(directory){for(const item of fs.readdirSync(directory,{withFileTypes:true})){
    const file=path.join(directory,item.name);if(item.isDirectory())checkParity(file);
    else if(item.name==='parity.json')parity.push(JSON.parse(fs.readFileSync(file,'utf8')));
  }}
  checkParity(path.join(out,'parity'));checkParity(path.join(out,'terminal-parity'));
  if(!parity.length||parity.some(p=>p.agreement!==true))throw Error('Missing or disagreeing cross-language evidence');
  report.parity_cases=parity.length;
  if(browser){
    run('full Studio/source/native/browser regressions',process.execPath,['tools/robotics/verify-cw-g01.cjs','--browser']);
    run('actual Chrome signed evidence inspector and same-attempt imports',process.execPath,['ts/apps/mini-studio/evidence-browser.mjs']);
    const b=JSON.parse(fs.readFileSync(path.join(out,'studio/browser-verification.json'),'utf8'));
    if(b.status!=='checks_passed'||b.physicalAcceptance!==false||b.executionAuthority!=='none'||b.fixtureContext!==true)
      throw Error('Missing scoped Studio browser evidence');
    run('actual browser downloads match both independent CLIs and native replay',python,['tools/robotics/verify-cw-g02-studio-downloads.py','--directory',path.join(out,'studio')]);
    const independent=JSON.parse(fs.readFileSync(path.join(out,'studio/independent-verification.json'),'utf8'));
    if(independent.status!=='checks_passed'||independent.physicalAcceptance!==false||independent.cases.length!==2)
      throw Error('Missing independent completed/stopped browser download evidence');
    report.studio_browser_checks=b.checks.length;report.independent_browser_cases=independent.cases.length;
    report.studio_browser_verified=true;
  }
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
    'tools/robotics/verify-cw-g02.cjs','tools/robotics/verify-cw-g02-studio-downloads.py','tools/robotics/cw_g02_parity.py',
    'tools/robotics/serve-cw-g01-test.py','ts/apps/mini-studio/','ts/tests/studio-evidence.test.ts','tests/fixtures/cw-g02/',
    'ts/packages/contracts/','ts/packages/drc-solver/','ts/packages/wasm-sim-bridge/',
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
  console.log(`CW-G02 local Studio/evidence: ${report.status}; browser included: ${browser}; production/physical qualification remains open.`);
}
