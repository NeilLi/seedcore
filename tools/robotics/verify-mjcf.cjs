// CW-SIM-01 source build, negative matrix and independent native compile/FK parity.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'../..');
const out=path.join(root,'artifacts/robotics/cw-s01');
const python=process.env.SEEDCORE_TEST_PYTHON || (fs.existsSync(path.join(root,'.venv/bin/python'))?path.join(root,'.venv/bin/python'):'python3');
const skipNative=process.argv.includes('--skip-native');
const report={scope:'offline_simulation_only',physical_acceptance:false,execution_authority:'none',review_id:'CW-SIM-01',native_included:!skipNative,checks:[]};
function run(label,command,args,env={}) {
 const r=spawnSync(command,args,{cwd:root,encoding:'utf8',env:{...process.env,...env},maxBuffer:16*1024*1024});
 process.stdout.write(r.stdout||'');process.stderr.write(r.stderr||'');
 const count=r.stdout?.match(/(?:# tests|ℹ tests) (\d+)/)||r.stdout?.match(/(\d+) passed/);
 report.checks.push({label,exit_code:r.status,tests:count?Number(count[1]):null});
 if(r.status!==0)throw new Error(`${label} failed: ${r.error?.message||r.status}`);
}
try {
 fs.mkdirSync(out,{recursive:true});
 run('generated assembly/component validators',process.execPath,['tools/robotics/generate-assembly-schema.cjs','--check']);
 for(const workspace of ['contracts','drc-solver','wasm-sim-bridge']) {
  fs.rmSync(path.join(root,`ts/packages/${workspace}/dist`),{recursive:true,force:true});
  run(`${workspace} source build`,'npm',['--prefix','ts','run','--workspace',`@seedcore/${workspace}`,'build']);
 }
 run('CW-S01 compiler and negative matrix',path.join(root,'ts/node_modules/.bin/tsx'),['--test','ts/tests/assembly-mjcf.test.ts']);
 run('export pinned synthetic models',path.join(root,'ts/node_modules/.bin/tsx'),['tools/robotics/export-cw-s01.ts',path.join(out,'models')]);
 if(!skipNative) run('independent Python semantics and native MuJoCo parity',python,['-m','pytest','tests/test_cw_s01_native.py','-q','--tb=short'],{
  SEEDCORE_CW_S01_REQUIRE_NATIVE:'1',SEEDCORE_CW_S01_CASES_DIR:path.join(out,'models'),
 });
 const cases=JSON.parse(fs.readFileSync(path.join(out,'models/cases.json'),'utf8'));
 report.starter={drc_disposition:cases.starter.drc.disposition,simulation_ready:cases.starter.readiness.ready,blocked_findings:cases.starter.readiness.blockingFindings.length};
 report.models=cases.models.map(c=>({name:c.name,model_digest:c.model.modelDigest,assembly_digest:c.model.manifest.assemblyDigest,catalog_provenance:c.model.manifest.catalogProvenance}));
 report.status=skipNative?'compiler_checks_passed_native_not_run':'checks_passed';
} catch(error) {report.status='checks_failed';report.failure=error.message;process.exitCode=1;}
finally {
 fs.mkdirSync(out,{recursive:true});
 report.source_revision=spawnSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).stdout.trim();
 report.working_tree_dirty=Boolean(spawnSync('git',['status','--porcelain'],{cwd:root,encoding:'utf8'}).stdout.trim());
 const tracked=spawnSync('git',['ls-files','--cached','--others','--exclude-standard'],{cwd:root,encoding:'utf8'}).stdout.trim().split('\n');
 const prefixes=['packages/simulation-fixtures/cw-s01/','ts/apps/mini-studio/src/simulation.ts','ts/packages/wasm-sim-bridge/','ts/packages/contracts/src/','ts/packages/drc-solver/src/','ts/tests/assembly-mjcf','ts/tests/fixtures/cw-s01','tools/robotics/verify-mjcf','tools/robotics/export-cw-s01','tools/robotics/generate-assembly-schema','tests/test_cw_s01_native','src/seedcore/robotics/assembly.py','src/seedcore/robotics/component_registry.py','packages/component-registry/','ts/package-lock.json'];
 report.inputs=tracked.filter(p=>prefixes.some(prefix=>p.startsWith(prefix))&&fs.statSync(path.join(root,p)).isFile()).map(p=>({path:p,sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(root,p))).digest('hex')}));
 fs.writeFileSync(path.join(out,'verification.json'),JSON.stringify(report,null,2)+'\n');
 console.log(`CW-SIM-01: ${report.status}; artifacts/robotics/cw-s01/verification.json`);
}
