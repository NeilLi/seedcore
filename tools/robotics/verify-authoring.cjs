// CW-ASM-02 / CW-SNAP-01 / CW-DRC-01..03 source build, store/DRC/API checks and optional browser evidence.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'../..');
const python=process.env.SEEDCORE_TEST_PYTHON || (fs.existsSync(path.join(root,'.venv/bin/python'))?path.join(root,'.venv/bin/python'):'python3');
const report={scope:'offline_proxy_authoring',physical_acceptance:false,node:process.version,review_ids:['CW-SIM-02','CW-SIM-03','CW-SIM-04','CW-SIM-01-STUDIO','CW-ASM-02','CW-SNAP-01','CW-DRC-01','CW-DRC-02','CW-DRC-03'],checks:[]};
function run(label,command,args,env={}){
 const result=spawnSync(command,args,{cwd:root,encoding:'utf8',env:{...process.env,SEEDCORE_TEST_PYTHON:python,...env}});
 process.stdout.write(result.stdout||'');process.stderr.write(result.stderr||'');
 const count=result.stdout?.match(/(?:# tests|ℹ tests) (\d+)/)||result.stdout?.match(/(\d+) passed/);
 report.checks.push({label,exit_code:result.status,tests:count?Number(count[1]):null});
 if(result.status!==0) throw new Error(`${label} failed: ${result.error?.message||result.status}`);
}
try{
 run('generated schema and CSP validator',process.execPath,['tools/robotics/generate-assembly-schema.cjs','--check']);
 for(const workspace of ['contracts','drc-solver','wasm-sim-bridge','robot-canvas','mini-studio']) {
  fs.rmSync(path.join(root,`ts/${workspace==='mini-studio'?'apps':'packages'}/${workspace}/dist`),{recursive:true,force:true});
  run(`${workspace} source build`,'npm',['--prefix','ts','run','--workspace',`@seedcore/${workspace}`,'build']);
 }
 run('workspace typecheck','npm',['--prefix','ts','run','typecheck']);
 run('workspace and authoring regressions','npm',['--prefix','ts','test']);
 if(!process.argv.includes('--skip-python')) run('local authoring API',python,['-m','pytest','tests/test_mini_studio_api.py','-q']);
 if(process.argv.includes('--browser')) {
  run('fresh CW-S01 reference artifacts',path.join(root,'ts/node_modules/.bin/tsx'),['tools/robotics/export-cw-s01.ts','artifacts/robotics/cw-s01/models']);
  run('fresh CW-S02 parity artifacts',path.join(root,'ts/node_modules/.bin/tsx'),['tools/robotics/export-cw-s02.ts','artifacts/robotics/cw-s02/models']);
  run('Chrome authoring and CW-S01 handoff exercise','npm',['--prefix','ts','run','--workspace','@seedcore/mini-studio','test:browser']);
  if(!process.argv.includes('--skip-python')) run('downloaded Studio bundles in pinned native MuJoCo',python,['-m','pytest','tests/test_cw_s01_studio_native.py','-q'],{SEEDCORE_CW_S01_STUDIO_REQUIRED:'1'});
 }
 report.status='checks_passed';
}catch(error){report.status='checks_failed';report.failure=error.message;process.exitCode=1;}
finally{
 report.browser_included=process.argv.includes('--browser');report.python_included=!process.argv.includes('--skip-python');
 report.source_revision=spawnSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).stdout.trim();
 report.working_tree_dirty=Boolean(spawnSync('git',['status','--porcelain'],{cwd:root,encoding:'utf8'}).stdout.trim());
 const tracked=spawnSync('git',['ls-files','--cached','--others','--exclude-standard'],{cwd:root,encoding:'utf8'}).stdout.trim().split('\n');
 const prefixes=['packages/simulation-fixtures/cw-s01/','tests/test_cw_s01_studio_native.py','tests/test_cw_s02_parity.py','tools/robotics/export-cw-s01.ts','tools/robotics/export-cw-s02.ts','tools/robotics/verify-cw-s02.cjs','ts/tests/fixtures/cw-s01.ts','ts/tests/mujoco-cw-s02.test.ts','ts/packages/drc-solver/','ts/packages/robot-canvas/','ts/packages/wasm-sim-bridge/','ts/apps/mini-studio/','ts/packages/contracts/src/','ts/packages/contracts/package.json','ts/tsconfig.base.json','scripts/robotics/serve_mini_studio.py','.github/workflows/unit-tests.yml','ts/tests/assembly-','ts/tests/browser-pipeline','tests/test_mini_studio_api','src/seedcore/robotics/mini_studio_api','tools/robotics/verify-authoring','tools/robotics/generate-assembly-schema','ts/package-lock.json','apps/mini-robot-simulator/physics-build.json'];
 report.inputs=tracked.filter(p=>prefixes.some(prefix=>p.startsWith(prefix))).map(p=>({path:p,sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(root,p))).digest('hex')}));
 report.outputs=['ts/apps/mini-studio/dist/app.js','ts/apps/mini-studio/dist/cw-s02-worker.js','ts/apps/mini-studio/dist/mujoco.wasm','ts/apps/mini-studio/dist/index.html','ts/apps/mini-studio/dist/app.css','ts/apps/mini-studio/dist/third-party-notices.txt'].filter(p=>fs.existsSync(path.join(root,p))).map(p=>({path:p,sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(root,p))).digest('hex')}));
 for(const scope of ['cw-a02','cw-a03','cw-a04','cw-s01/studio']){const target=path.join(root,`artifacts/robotics/${scope}/verification.json`);fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,JSON.stringify(report,null,2)+'\n');}
 console.log(`CW-ASM-02 / CW-SNAP-01 / CW-DRC-01..03: ${report.status}; artifacts/robotics/cw-a04/verification.json`);
}
