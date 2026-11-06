// CW-PACK-01 draft source build, deterministic ZIP exports and independent extraction.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/robotics/cw-e01');
const python=process.env.SEEDCORE_TEST_PYTHON||(fs.existsSync(path.join(root,'.venv/bin/python'))?path.join(root,'.venv/bin/python'):'python3');
const browser=process.argv.includes('--browser');
const report={review_id:'CW-PACK-01-DRAFT',scope:'offline_design_only',physical_acceptance:false,execution_authority:'none',browser_included:browser,checks:[]};
function run(label,command,args){
  const r=spawnSync(command,args,{cwd:root,encoding:'utf8',maxBuffer:16*1024*1024,env:{...process.env,SEEDCORE_TEST_PYTHON:python}});
  process.stdout.write(r.stdout||'');process.stderr.write(r.stderr||'');
  const count=(r.stdout||'').match(/(?:# tests|ℹ tests) (\d+)/);
  report.checks.push({label,exit_code:r.status,tests:count?Number(count[1]):null});
  if(r.status!==0)throw Error(`${label} failed: ${r.error?.message||r.status}`);
}
const independent=String.raw`import csv,hashlib,io,json,pathlib,sys,zipfile,xml.etree.ElementTree as ET
directory=pathlib.Path(sys.argv[1]); cases=[]
for name in ['starter','synthetic-reference']:
 file=directory/(name+'.zip'); source=json.loads((directory/(name+'.input.json')).read_text()); payload=file.read_bytes()
 assert len(payload)<=8*1024*1024
 with zipfile.ZipFile(io.BytesIO(payload)) as z:
  infos=z.infolist(); names=z.namelist(); assert z.testzip() is None and len(names)==len(set(names)) and len(names)<=288
  assert all(not pathlib.PurePosixPath(p).is_absolute() and '..' not in pathlib.PurePosixPath(p).parts and '\\' not in p for p in names)
  assert all(i.compress_type==zipfile.ZIP_STORED and i.file_size==i.compress_size and i.date_time==(1980,1,1,0,0,0) and i.file_size<=2*1024*1024 for i in infos)
  m=json.loads(z.read('manifest.json')); assert m['schemaVersion']=='seedcore.cw-e01.build-pack.v1' and m['status']=='draft'
  assert m['physicalAcceptance'] is False and m['executionAuthority']=='none' and len(m['files'])==len(names)-1
  assert set(f['path'] for f in m['files'])==set(names)-{'manifest.json'}
  for f in m['files']:
   b=z.read(f['path']); assert len(b)==f['bytes'] and hashlib.sha256(b).hexdigest()==f['sha256']
  assert json.loads(z.read('assembly.sc-assembly.json'))==source['assembly']
  assert json.loads(z.read('drc-report.json'))==source['drcReport']
  assert z.read('source/catalog.json').decode()==source['catalog']['catalogRawJson']
  for mapping in json.loads(z.read('source/part-map.json')):
   original=next(p for p in source['catalog']['partDocuments'] if p['part_id']==mapping['partId'])
   assert z.read(mapping['path']).decode()==original['raw_json']
  rows=list(csv.reader(io.StringIO(z.read('bom.csv').decode()))); assert len(rows)==len(source['drcReport']['bom']['lines'])+1
  ET.fromstring(z.read('wiring.svg'))
  assert all(not p.lower().endswith(('.stl','.step','.glb','.bin','.pem')) for p in names)
  refs=json.loads(z.read('asset-references.json')); assert all(p['assetBytesIncluded'] is False and p['assetBytesVerified'] is False and p['printReady'] is False for p in refs['parts'])
  if name=='starter': assert m['model']['included'] is False and m['bom']['unpricedPartCount']>0 and 'model.mjcf.xml' not in names
  else:
   assert m['model']['included'] is True
   model=json.loads(z.read('model.cw-s01.json')); assert z.read('model.mjcf.xml').decode()==model['xml'] and model['modelDigest']==m['model']['modelDigest']
   ET.fromstring(model['xml'])
  cases.append({'name':name,'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest(),'files':len(names),'modelIncluded':m['model']['included']})
result={'status':'checks_passed','scope':'offline_design_only','physicalAcceptance':False,'executionAuthority':'none','cases':cases}
(directory/'independent-verification.json').write_text(json.dumps(result,indent=2)+'\n')
print('Independent Python ZIP/CRC/SHA/source/CSV/XML verification passed for both draft packs.')
`;
try{
  fs.mkdirSync(out,{recursive:true});
  for(const workspace of ['contracts','drc-solver','wasm-sim-bridge','robot-canvas','mini-studio']){
    fs.rmSync(path.join(root,`ts/${workspace==='mini-studio'?'apps':'packages'}/${workspace}/dist`),{recursive:true,force:true});
    run(`${workspace} source build`,'npm',['--prefix','ts','run','--workspace',`@seedcore/${workspace}`,'build']);
  }
  run('workspace typecheck','npm',['--prefix','ts','run','typecheck']);
  run('workspace source regression tests','npm',['--prefix','ts','test']);
  run('deterministic draft starter and synthetic-reference exports',path.join(root,'ts/node_modules/.bin/tsx'),['tools/robotics/export-cw-e01.ts',out]);
  run('independent ZIP/CRC/SHA/source/CSV/XML checks',python,['-c',independent,out]);
  if(browser){
    run('actual Chrome draft build-pack downloads and stale UI fencing',process.execPath,['ts/apps/mini-studio/build-pack-browser.mjs']);
    const b=JSON.parse(fs.readFileSync(path.join(out,'studio/browser-verification.json'),'utf8'));
    if(b.status!=='checks_passed'||b.physicalAcceptance!==false||b.executionAuthority!=='none')throw Error('Missing scoped build-pack browser report');
    report.browser_checks=b.checks.length;
  }
  report.status='checks_passed';
}catch(error){report.status='checks_failed';report.failure=error.message;process.exitCode=1;}
finally{
  report.source_revision=spawnSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).stdout.trim();
  report.working_tree_dirty=Boolean(spawnSync('git',['status','--porcelain'],{cwd:root,encoding:'utf8'}).stdout.trim());
  const files=spawnSync('git',['ls-files','--cached','--others','--exclude-standard'],{cwd:root,encoding:'utf8'}).stdout.trim().split('\n');
  const prefixes=['ts/packages/wasm-sim-bridge/','ts/packages/contracts/','ts/packages/drc-solver/','ts/packages/robot-canvas/',
    'ts/apps/mini-studio/','ts/tests/build-pack.test.ts','ts/tests/studio-build-pack.test.ts','ts/tests/fixtures/cw-s01.ts',
    'tools/robotics/export-cw-e01.ts','tools/robotics/verify-cw-e01.cjs','packages/component-registry/','packages/simulation-fixtures/cw-s01/',
    'ts/package.json','ts/package-lock.json','ts/tsconfig.base.json','src/seedcore/robotics/mini_studio_api.py',
    'src/seedcore/robotics/assembly.py','src/seedcore/robotics/component_registry.py','scripts/robotics/serve_mini_studio.py','.github/workflows/unit-tests.yml'];
  const hash=p=>({path:p,sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(root,p))).digest('hex')});
  report.inputs=files.filter(p=>prefixes.some(prefix=>p.startsWith(prefix))&&fs.statSync(path.join(root,p)).isFile()).sort().map(hash);
  const outputs=[];
  function collect(directory){for(const item of fs.readdirSync(directory,{withFileTypes:true})){const file=path.join(directory,item.name);if(item.isDirectory())collect(file);else if(item.isFile()&&file!==path.join(out,'verification.json'))outputs.push(path.relative(root,file));}}
  collect(out);report.outputs=outputs.sort().map(hash);
  fs.writeFileSync(path.join(out,'verification.json'),JSON.stringify(report,null,2)+'\n');
  console.log(`CW-E01 draft design pack: ${report.status}; browser included: ${browser}; no physical/runtime qualification.`);
}
