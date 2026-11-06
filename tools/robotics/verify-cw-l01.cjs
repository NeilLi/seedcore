// CW-L01 local curated gallery and guided synthetic lesson verification.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),{spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/robotics/cw-l01'),browser=process.argv.includes('--browser');
const report={review_id:'CW-GAL-01-LOCAL',scope:'offline_proxy_authoring',physical_acceptance:false,execution_authority:'none',browser_included:browser,checks:[]};
function run(label,command,args){const r=spawnSync(command,args,{cwd:root,encoding:'utf8',maxBuffer:16*1024*1024});process.stdout.write(r.stdout||'');process.stderr.write(r.stderr||'');const m=(r.stdout||'').match(/(?:# tests|ℹ tests) (\d+)/);report.checks.push({label,exit_code:r.status,tests:m?Number(m[1]):null});if(r.status!==0)throw Error(`${label}: ${r.error?.message||r.status}`);}
try{
 fs.mkdirSync(out,{recursive:true});
 for(const workspace of ['contracts','drc-solver','wasm-sim-bridge','robot-canvas','mini-studio']){
  fs.rmSync(path.join(root,`ts/${workspace==='mini-studio'?'apps':'packages'}/${workspace}/dist`),{recursive:true,force:true});
  run(`${workspace} source build`,'npm',['--prefix','ts','run','--workspace',`@seedcore/${workspace}`,'build']);
 }
 run('workspace typecheck','npm',['--prefix','ts','run','typecheck']);
 run('workspace tests','npm',['--prefix','ts','test']);
 if(browser){run('local gallery, fork, lesson and ZIP browser exercise',process.execPath,['ts/apps/mini-studio/gallery-browser.mjs']);
  const b=JSON.parse(fs.readFileSync(path.join(out,'browser-verification.json'),'utf8'));if(b.status!=='checks_passed'||b.physicalAcceptance!==false||b.executionAuthority!=='none')throw Error('Missing scoped browser results');report.browser_checks=b.checks.length;
 }
 report.status='checks_passed';
}catch(e){report.status='checks_failed';report.failure=e.message;process.exitCode=1;}
finally{
 report.source_revision=spawnSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).stdout.trim();
 report.working_tree_dirty=Boolean(spawnSync('git',['status','--porcelain'],{cwd:root,encoding:'utf8'}).stdout.trim());
 const paths=spawnSync('git',['ls-files','--cached','--others','--exclude-standard'],{cwd:root,encoding:'utf8'}).stdout.trim().split('\n');
 const prefixes=['ts/apps/mini-studio/','ts/packages/contracts/','ts/packages/drc-solver/','ts/packages/robot-canvas/','ts/packages/wasm-sim-bridge/','ts/tests/studio-gallery.test.ts','tools/robotics/verify-cw-l01.cjs','packages/component-registry/','packages/simulation-fixtures/cw-s01/','src/seedcore/robotics/mini_studio_api.py','scripts/robotics/serve_mini_studio.py','ts/package.json','ts/package-lock.json','ts/tsconfig.base.json','.github/workflows/unit-tests.yml'];
 const hash=p=>({path:p,sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(root,p))).digest('hex')});
 report.inputs=paths.filter(p=>prefixes.some(prefix=>p.startsWith(prefix))&&fs.statSync(path.join(root,p)).isFile()).sort().map(hash);
 report.outputs=fs.readdirSync(out).filter(n=>n!=='verification.json'&&fs.statSync(path.join(out,n)).isFile()).sort().map(n=>hash(path.relative(root,path.join(out,n))));
 fs.writeFileSync(path.join(out,'verification.json'),JSON.stringify(report,null,2)+'\n');console.log(`CW-L01 ${report.status}; browser: ${browser}; no hardware qualification.`);
}
