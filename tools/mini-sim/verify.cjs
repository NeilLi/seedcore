// Dependency-free runner using the repository's locked TypeScript compiler.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const root = path.resolve(__dirname,'../..');
function run(args) {
  const result = spawnSync(process.execPath,args,{ cwd:root,stdio:'inherit' });
  if (result.status !== 0) throw new Error(`Verification failed: ${args.join(' ')}`);
}
const temp = fs.mkdtempSync(path.join(os.tmpdir(),'mini-sim-contracts-'));
try {
  run(['ts/node_modules/typescript/bin/tsc','-p','packages/mini-sim-contracts','--outFile',path.join(temp,'sim-contracts.js')]);
  for (const name of ['sim-contracts.js','sim-contracts.d.ts']) {
    if (!fs.readFileSync(path.join(temp,name)).equals(fs.readFileSync(path.join(root,'apps/mini-robot-simulator',name)))) {
      throw new Error(`Generated ${name} is stale. Run npm --prefix packages/mini-sim-contracts run build.`);
    }
  }
  for (const name of ['physics.js','physics-wasm.js','physics-worker-loader.js','physics-build.js','app.js','simulation-worker.js','sim-contracts.js']) {
    run(['--check',`apps/mini-robot-simulator/${name}`]);
  }
  run(['--check','tools/mini-sim/browser-qualification.js']);
  run(['--test','apps/mini-robot-simulator/physics.test.cjs','apps/mini-robot-simulator/simulation-worker.test.cjs',
    'apps/mini-robot-simulator/app-worker.test.cjs','tests/mini-sim/contracts.test.cjs']);
  run(['tools/mini-sim/verify-physics.cjs']);
} finally { fs.rmSync(temp,{ recursive:true,force:true }); }
