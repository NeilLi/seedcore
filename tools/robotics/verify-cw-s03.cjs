// CW-S03 compatibility preflight software evidence; a successful verifier can report runtime BLOCKED.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/robotics/cw-s03');
const python=process.env.SEEDCORE_TEST_PYTHON||(fs.existsSync(path.join(root,'.venv/bin/python'))?path.join(root,'.venv/bin/python'):'python3');
const requireReplay=process.argv.includes('--require-artifact-replay');
const report={review_id:'CW-POL-01-PREFLIGHT',scope:'offline_policy_compatibility_preflight',physical_acceptance:false,execution_authority:'none',runtime_qualification:'not_granted',require_artifact_replay:requireReplay,checks:[]};
function run(label,command,args){
 const r=spawnSync(command,args,{cwd:root,encoding:'utf8',env:{...process.env},maxBuffer:16*1024*1024});
 process.stdout.write(r.stdout||'');process.stderr.write(r.stderr||'');
 const tests=r.stdout?.match(/(?:# tests|ℹ tests) (\d+)/)||r.stdout?.match(/(\d+) passed/);
 const skips=r.stdout?.match(/(\d+) skipped/);
 report.checks.push({label,exit_code:r.status,tests:tests?Number(tests[1]):null,skipped:skips?Number(skips[1]):0});
 if(r.status!==0)throw new Error(`${label} failed: ${r.error?.message||r.status}`);
}
try{
 fs.mkdirSync(out,{recursive:true});
 for(const name of ['inventory.json','compatibility.json'])fs.rmSync(path.join(out,name),{force:true});
 for(const workspace of ['contracts','drc-solver','wasm-sim-bridge']){
  fs.rmSync(path.join(root,`ts/packages/${workspace}/dist`),{recursive:true,force:true});
  run(`${workspace} source build`,'npm',['--prefix','ts','run','--workspace',`@seedcore/${workspace}`,'build']);
 }
 run('policy compatibility typecheck','npm',['--prefix','ts','run','--workspace','@seedcore/wasm-sim-bridge','typecheck']);
 run('CW-S03 contract and refusal matrix',path.join(root,'ts/node_modules/.bin/tsx'),['--test','ts/tests/policy-compatibility.test.ts']);
 run('CW-S03 local inventory, pin and CPU evidence regressions',python,['-m','pytest','tests/test_policy_preflight_inventory.py','-q','--tb=short']);
 run('inspect pinned local artifacts and replay available CPU goldens',python,['-m','seedcore.robotics.policy_preflight_inventory',path.join(out,'inventory.json')]);
 const inventory=JSON.parse(fs.readFileSync(path.join(out,'inventory.json'),'utf8'));
 report.policy_inspection_included=inventory.policy.status==='verified';
 report.artifact_replay_included=inventory.artifactReplay.status==='verified';
 report.artifact_replay_cases=inventory.artifactReplay.caseCount;
 report.training_checkpoint_parity=inventory.unresolved.trainingCheckpointParity;
 report.browser_policy_qualified=false;
 if(inventory.policy.status==='failed'||inventory.artifactReplay.status==='failed')throw new Error(`Local policy inspection/replay failed: ${inventory.artifactReplay.detail}`);
 if(requireReplay&&!report.artifact_replay_included)throw new Error('Pinned CPU artifact replay is required but was not executed; missing cache/dependencies cannot count as acceptance.');
 run('build exact policy/model/adapter refusal reports',path.join(root,'ts/node_modules/.bin/tsx'),['tools/robotics/export-cw-s03.ts',out]);
 const first=fs.readFileSync(path.join(out,'compatibility.json'));
 run('repeat report generation from the same independently pinned inventory',path.join(root,'ts/node_modules/.bin/tsx'),['tools/robotics/export-cw-s03.ts',out]);
 if(!first.equals(fs.readFileSync(path.join(out,'compatibility.json'))))throw new Error('Compatibility report is not byte-deterministic');
 const matrix=JSON.parse(first);
 report.matrix_digest=matrix.matrixDigest;
 report.candidates=matrix.cases.map(c=>({name:c.name,decision:c.report.decision,report_digest:c.report.reportDigest,blocking_codes:[...new Set(c.report.findings.map(f=>f.code))]}));
 report.status=report.artifact_replay_included?'checks_passed_runtime_blocked':'checks_passed_artifact_replay_not_run_runtime_blocked';
}catch(error){report.status='checks_failed';report.failure=error.message;process.exitCode=1;}
finally{
 fs.mkdirSync(out,{recursive:true});
 report.source_revision=spawnSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).stdout.trim();
 report.working_tree_dirty=Boolean(spawnSync('git',['status','--porcelain'],{cwd:root,encoding:'utf8'}).stdout.trim());
 const files=spawnSync('git',['ls-files','--cached','--others','--exclude-standard'],{cwd:root,encoding:'utf8'}).stdout.trim().split('\n');
 const prefixes=['tools/robotics/verify-cw-s03.cjs','tools/robotics/export-cw-s03.ts','src/seedcore/robotics/policy_preflight_inventory.py','src/seedcore/robotics/microduck_contract.py','src/seedcore/robotics/model_package/',
  'ts/packages/wasm-sim-bridge/','ts/packages/contracts/src/','ts/packages/drc-solver/src/','ts/tests/policy-compatibility.test.ts','ts/tests/fixtures/policy-compatibility.ts','ts/tests/fixtures/cw-s01.ts','tests/test_policy_preflight_inventory.py',
  'packages/robotics-profiles/microduck-sim-v1.json','packages/robotics-profiles/reviews/cw-s03-preflight-inputs-v1.json','packages/models/microduck/0.1.0/','packages/simulation-fixtures/cw-s01/','tests/fixtures/microduck/golden-v1.json','ts/package-lock.json','pyproject.toml'];
 report.inputs=files.filter(p=>prefixes.some(prefix=>p.startsWith(prefix))&&fs.statSync(path.join(root,p)).isFile()).map(p=>({path:p,sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(root,p))).digest('hex')}));
 report.outputs=['inventory.json','compatibility.json'].filter(p=>fs.existsSync(path.join(out,p))).map(p=>({path:`artifacts/robotics/cw-s03/${p}`,sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(out,p))).digest('hex')}));
 fs.writeFileSync(path.join(out,'verification.json'),JSON.stringify(report,null,2)+'\n');
 console.log(`CW-POL-01 preflight: ${report.status}; artifacts/robotics/cw-s03/verification.json`);
}
