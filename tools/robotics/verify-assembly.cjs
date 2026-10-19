// Builds from source and retains scoped, reproducible CW-ASM-01 evidence.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const root = path.resolve(__dirname, '../..');
const report = {scope:'offline_assembly_v2_authoring', physical_acceptance:false, node:process.version, checks:[]};
function run(label, command, args) {
  const result = spawnSync(command,args,{cwd:root,encoding:'utf8',env:{...process.env,SEEDCORE_TEST_PYTHON:python}});
  process.stdout.write(result.stdout || '');
  process.stderr.write(result.stderr || '');
  const count = label === 'Python conformance' ? result.stdout?.match(/(\d+) passed/) : result.stdout?.match(/# tests (\d+)/);
  report.checks.push({label,exit_code:result.status,tests:count ? Number(count[1]) : null,error:result.error?.message || null});
  if (result.status !== 0) throw new Error(`${label} failed`);
}
const python = process.env.SEEDCORE_TEST_PYTHON || (fs.existsSync(path.join(root,'.venv/bin/python')) ? path.join(root,'.venv/bin/python') : 'python3');
try {
  run('schema binding',process.execPath,['tools/robotics/generate-assembly-schema.cjs','--check']);
  run('contracts build',process.execPath,['ts/node_modules/typescript/bin/tsc','-p','ts/packages/contracts']);
  if (!process.argv.includes('--node-only')) run('Python conformance',python,['-m','pytest','tests/test_assembly_contracts.py','tests/test_component_registry.py','-q']);
  run('Node and live cross-language conformance',process.execPath,['--test','--test-reporter=tap','tests/mini-sim/assembly-contracts.test.cjs']);
  report.status = 'checks_passed';
} catch (error) {
  report.status = 'checks_failed';
  process.exitCode = 1;
  console.error(error.message);
} finally {
  report.python_suite_included = !process.argv.includes('--node-only');
  report.python = spawnSync(python,['--version'],{cwd:root,encoding:'utf8'}).stdout.trim();
  report.source_revision = spawnSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).stdout.trim();
  report.working_tree_dirty = Boolean(spawnSync('git',['status','--porcelain'],{cwd:root,encoding:'utf8'}).stdout.trim());
  report.artifacts = ['src/seedcore/robotics/assembly.py','packages/component-registry/catalog.json','packages/component-registry/schema/v2.sc-assembly.schema.json','packages/component-registry/assemblies/tabletop-starter.sc-assembly.json','tests/fixtures/assembly-v2/canonical.json','tests/fixtures/assembly-v2/conformance.json','tests/test_assembly_contracts.py','tests/mini-sim/assembly-contracts.test.cjs','ts/packages/contracts/src/robotAssemblyContracts.ts','ts/packages/contracts/src/robotAssemblySchema.ts','ts/packages/contracts/src/robotAssemblyValidator.ts','ts/packages/contracts/dist/robotAssemblyContracts.js','ts/packages/contracts/package.json','ts/package-lock.json','pyproject.toml','docker/requirements.base.txt','tools/robotics/verify-assembly.cjs','tools/robotics/generate-assembly-schema.cjs','.github/workflows/unit-tests.yml'].filter(file=>fs.existsSync(path.join(root,file))).map(file=>({path:file,sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(root,file))).digest('hex')}));
  const target = path.join(root,'artifacts/robotics/cw-a01/verification.json');
  fs.mkdirSync(path.dirname(target),{recursive:true});
  fs.writeFileSync(target,JSON.stringify(report,null,2)+'\n');
  console.log('CW-ASM-01 report: artifacts/robotics/cw-a01/verification.json');
}
