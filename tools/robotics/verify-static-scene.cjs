// Build-bound synthetic HLOD/RTC checks. Browser evidence requires an actual browser.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),{spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'../..'),browser=process.argv.includes('--browser');
const python=process.env.SEEDCORE_TEST_PYTHON||(fs.existsSync(path.join(root,'.venv/bin/python'))?path.join(root,'.venv/bin/python'):'python3');
const report={schema:'seedcore.static-scene-verification.v1',scope:'synthetic_visual_streaming',physicalAcceptance:false,executionAuthority:'none',browserIncluded:browser,checks:[]};
function run(label,cmd,args){const r=spawnSync(cmd,args,{cwd:root,encoding:'utf8',env:{...process.env,SEEDCORE_TEST_PYTHON:python}});process.stdout.write(r.stdout||'');process.stderr.write(r.stderr||'');report.checks.push({label,exitCode:r.status});if(r.status!==0)throw Error(`${label}: ${r.error?.message||r.status}`);}
try {
 run('original Draco fixture reproducibility',process.execPath,['tools/robotics/generate-static-scene.cjs','--check']);
 for(const name of ['contracts','drc-solver','wasm-sim-bridge','robot-canvas','mini-studio']){fs.rmSync(path.join(root,`ts/${name==='mini-studio'?'apps':'packages'}/${name}/dist`),{recursive:true,force:true});run(`${name} source build`,'npm',['--prefix','ts','run','--workspace',`@seedcore/${name}`,'build']);}
 run('workspace types','npm',['--prefix','ts','run','typecheck']);
 run('pinned ingestion, native Draco, SSE and RTC',path.join(root,'ts/node_modules/.bin/tsx'),['--test','ts/tests/static-scene.test.ts']);
 if(!process.argv.includes('--skip-python'))run('local static allowlist and CSP',python,['-m','pytest','tests/test_mini_studio_api.py','-q']);
 if(browser)run('real browser HLOD, cache, fault and lifecycle','npm',['--prefix','ts','run','--workspace','@seedcore/mini-studio','test:scene']);
 report.status=browser?'browser_checks_passed':'core_checks_passed_browser_not_run';
}catch(e){report.status='checks_failed';report.failure=e.message;process.exitCode=1;}
finally{
 report.sourceRevision=spawnSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).stdout.trim();report.workingTreeDirty=Boolean(spawnSync('git',['status','--porcelain'],{cwd:root,encoding:'utf8'}).stdout.trim());
 const paths=spawnSync('git',['ls-files','--cached','--others','--exclude-standard'],{cwd:root,encoding:'utf8'}).stdout.trim().split('\n');
 const prefixes=['packages/scene-fixtures/','ts/packages/robot-canvas/','ts/packages/wasm-sim-bridge/','ts/apps/mini-studio/','ts/tests/static-scene','tools/robotics/generate-static-scene','tools/robotics/verify-static-scene','src/seedcore/robotics/mini_studio_api.py','tests/test_mini_studio_api.py','ts/package-lock.json','.github/workflows/unit-tests.yml'];
 const hash=p=>({path:p,sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(root,p))).digest('hex')});
 report.inputs=[...new Set([...paths.filter(p=>prefixes.some(x=>p.startsWith(x))),'apps/mini-robot-simulator/mini-physics.wasm','apps/mini-robot-simulator/physics-build.json'])].sort().map(hash);
 report.outputs=['scene.html','scene.css','scene.js','scene-worker.js','scene-build.json','scene-decoders/draco_wasm_wrapper.js','scene-decoders/draco_decoder.wasm'].map(p=>`ts/apps/mini-studio/dist/${p}`).filter(p=>fs.existsSync(path.join(root,p))).map(hash);
 const out=path.join(root,'artifacts/robotics/static-scene');fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,'verification.json'),JSON.stringify(report,null,2)+'\n');console.log(`Static scene: ${report.status}; artifacts/robotics/static-scene/verification.json`);
}
