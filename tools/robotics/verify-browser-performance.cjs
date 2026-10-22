// Source-built visual pipeline checks. Browser/GPU qualification is opt-in and explicit.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'../..'),browser=process.argv.includes('--browser');
const python=process.env.SEEDCORE_TEST_PYTHON||(fs.existsSync(path.join(root,'.venv/bin/python'))?path.join(root,'.venv/bin/python'):'python3');
const report={schema:'seedcore.browser-performance-verification.v1',scope:'synthetic_simulation_measurement',physicalAcceptance:false,executionAuthority:'none',browserIncluded:browser,checks:[]};
function run(label,cmd,args) {
 const r=spawnSync(cmd,args,{cwd:root,encoding:'utf8',env:{...process.env,SEEDCORE_TEST_PYTHON:python}});process.stdout.write(r.stdout||'');process.stderr.write(r.stderr||'');
 report.checks.push({label,exitCode:r.status});if(r.status!==0)throw Error(`${label}: ${r.error?.message||r.status}`);
}
try {
 for(const name of ['contracts','drc-solver','wasm-sim-bridge','robot-canvas','mini-studio']) {
  fs.rmSync(path.join(root,`ts/${name==='mini-studio'?'apps':'packages'}/${name}/dist`),{recursive:true,force:true});
  run(`${name} source build`,'npm',['--prefix','ts','run','--workspace',`@seedcore/${name}`,'build']);
 }
 run('workspace typecheck','npm',['--prefix','ts','run','typecheck']);
 run('transport concurrency and independent planar FK',path.join(root,'ts/node_modules/.bin/tsx'),['--test','ts/tests/browser-pipeline.test.ts']);
 if(!process.argv.includes('--skip-python'))run('localhost allowlist and CSP',python,['-m','pytest','tests/test_mini_studio_api.py','-q']);
 if(browser)run('real Chrome WebGPU pipelines and diagnostic FK parity','npm',['--prefix','ts','run','--workspace','@seedcore/mini-studio','test:performance']);
 report.status=browser?'browser_checks_passed':'core_checks_passed_browser_not_run';
}catch(e){report.status='checks_failed';report.failure=e.message;process.exitCode=1;}
finally {
 report.sourceRevision=spawnSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).stdout.trim();
 report.workingTreeDirty=Boolean(spawnSync('git',['status','--porcelain'],{cwd:root,encoding:'utf8'}).stdout.trim());
 const files=spawnSync('git',['ls-files','--cached','--others','--exclude-standard'],{cwd:root,encoding:'utf8'}).stdout.trim().split('\n');
 const prefixes=['ts/packages/wasm-sim-bridge/','ts/apps/mini-studio/','ts/tests/browser-pipeline','src/seedcore/robotics/mini_studio_api.py','tests/test_mini_studio_api.py','tools/robotics/verify-browser-performance','apps/mini-robot-simulator/physics-build.json','packages/mini-physics/','tools/mini-sim/build-physics.cjs','ts/package-lock.json'];
 const hash=p=>({path:p,sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(root,p))).digest('hex')});
 report.inputs=[...new Set([...files.filter(p=>prefixes.some(prefix=>p.startsWith(prefix))),'apps/mini-robot-simulator/mini-physics.wasm'])].sort().map(hash);
 report.outputs=['performance.html','performance.js','performance.css','lab-physics.js','lab-render.js','lab-physics.wasm'].map(p=>`ts/apps/mini-studio/dist/${p}`).filter(p=>fs.existsSync(path.join(root,p))).map(hash);
 const out=path.join(root,'artifacts/robotics/browser-performance');fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,'verification.json'),JSON.stringify(report,null,2)+'\n');console.log(`Browser performance: ${report.status}; artifacts/robotics/browser-performance/verification.json`);
}
