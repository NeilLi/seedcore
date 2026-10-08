/* Developer-only build. No SDK/runtime/package is needed by learners. */
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const { spawnSync } = require('node:child_process');
const root = path.resolve(__dirname,'../..');
const cxx = process.env.MINI_CXX || 'clang++';
const linker = process.env.MINI_WASM_LD || (fs.existsSync('/opt/homebrew/opt/lld/bin/wasm-ld') ? '/opt/homebrew/opt/lld/bin/wasm-ld' : 'wasm-ld');
function run(exe,args) {
  const result=spawnSync(exe,args,{cwd:root,stdio:'inherit'});
  if(result.error || result.status!==0) throw result.error || new Error(`${exe} failed`);
}
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'mini-physics-build-'));
try {
  const object=path.join(temp,'physics.o');
  run(cxx,['--target=wasm32-unknown-unknown','-std=c++17','-O2','-ffp-contract=off','-fno-fast-math',
    '-fno-exceptions','-fno-rtti','-fno-builtin','-nostdlib','-Ipackages/mini-physics/include',
    '-c','packages/mini-physics/src/mini_physics.cpp','-o',object]);
  run(linker,[object,'--no-entry','--allow-undefined','--export=mini_abi','--export=mini_eval',
    '--export=mini_scratch','--export-memory','--initial-memory=131072','--max-memory=131072',
    '--strip-all','-o','apps/mini-robot-simulator/mini-physics.wasm']);
  const bytes=fs.readFileSync(path.join(root,'apps/mini-robot-simulator/mini-physics.wasm'));
  const module=new WebAssembly.Module(bytes);
  const imports=WebAssembly.Module.imports(module);
  if(imports.some(i=>i.module!=='env' || !['sin','cos'].includes(i.name))) throw new Error('Unexpected Wasm import');
  const crypto=require('node:crypto');
  const sha256=crypto.createHash('sha256').update(bytes).digest('hex');
  const manifest={schema:'seedcore.mini-physics.build.v1',abi:1,profile:'planar-rk4-f64',bytes:bytes.length,sha256,
    compiler:spawnSync(cxx,['--version'],{encoding:'utf8'}).stdout.split('\n')[0],
    linker:spawnSync(linker,['--version'],{encoding:'utf8'}).stdout.trim(),
    math:'host sin/cos; no cross-platform bitwise guarantee',memoryBytes:131072};
  fs.writeFileSync(path.join(root,'apps/mini-robot-simulator/physics-build.json'),JSON.stringify(manifest,null,2)+'\n');
  fs.writeFileSync(path.join(root,'apps/mini-robot-simulator/physics-build.js'),`globalThis.MiniPhysicsBuild = ${JSON.stringify(manifest)};\n`);
  console.log(`Built ${bytes.length} bytes, SHA-256 ${sha256}`);
} finally { fs.rmSync(temp,{recursive:true,force:true}); }
