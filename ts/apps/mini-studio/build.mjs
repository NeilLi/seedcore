import {build} from 'esbuild';
import {mkdir,copyFile,readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';

const MUJOCO_WASM_BYTES = 10370402;
const MUJOCO_WASM_SHA256 = 'd59c489dd521c80af6965756c5b90daff549fa281566544e4540c170d937633d';
const MUJOCO_JS_BYTES = 293619;
const MUJOCO_JS_SHA256 = 'a5d5f00c4c16d327cf8275f88ddd47c857a5e9baec8ca4174d676fe299267a0c';

const mujocoCspPlugin = {
  name: 'mujoco-csp-browser',
  setup(b) {
    b.onLoad({filter: /@mujoco\/mujoco\/mujoco\.js$/}, async args => {
      const raw = await readFile(args.path, 'utf8');
      if (Buffer.byteLength(raw, 'utf8') !== MUJOCO_JS_BYTES || createHash('sha256').update(raw).digest('hex') !== MUJOCO_JS_SHA256) {
        throw new Error('Pinned @mujoco/mujoco JS SHA-256 or byte-length mismatch');
      }
      const contents = raw
        .replace(
          "const { createRequire } = await import('module');\n  /** @suppress{duplicate} */\n  var require = createRequire(import.meta.url);",
          "var require = () => { throw new Error('Node require disabled in browser worker'); };",
        )
        .replace(
          'let [args, invokerFnBody] = createJsInvoker(argTypes, isClassMethodFunc, returns, isAsync);\n      var invokerFn = new Function(...args, invokerFnBody)(...closureArgs);',
          `var invokerFn = function(...jsArgs) {
        checkArgCount(jsArgs.length, minArgs, expectedArgCount, humanName, throwBindingError);
        var destructors = needsDestructorStack ? [] : null;
        var wired = [cppTargetFunc];
        if (isClassMethodFunc) wired.push(argTypes[1].toWireType(destructors, this));
        for (var i = 0; i < expectedArgCount; ++i) wired.push(argTypes[i + 2].toWireType(destructors, jsArgs[i]));
        var rv = cppInvokerFunc(...wired);
        if (needsDestructorStack) runDestructors(destructors);
        else {
          for (var i = isClassMethodFunc ? 1 : 2; i < argTypes.length; ++i) {
            if (argTypes[i].destructorFunction !== null) argTypes[i].destructorFunction(wired[isClassMethodFunc ? i : i - 1]);
          }
        }
        if (returns) return argTypes[0].fromWireType(rv);
      };`,
        )
        .replace(
          'var invokerFunction = new Function(...params, functionBody)(...args);',
          `var invokerFunction = function(obj, func, destructorsRef, rawArgs) {
        var offset = 0, callArgs = [];
        for (var i = 0; i < argCount; ++i) {
          callArgs.push(types[i].readValueFromPointer(rawArgs + offset));
          offset += types[i].argPackAdvance;
        }
        var rv = kind === 1 ? new func(...callArgs) : func.apply(obj, callArgs);
        if (!retType.isVoid) return emval_returnValue(retType, destructorsRef, rv);
      };`,
        );
      if (contents.includes('new Function') || contents.includes('eval(')) {
        throw new Error('CSP violation: remaining dynamic code generation in @mujoco/mujoco worker bundle');
      }
      return {contents, loader: 'js'};
    });
  },
};

await mkdir('dist',{recursive:true});
await build({entryPoints:['src/app.ts'],outfile:'dist/app.js',bundle:true,format:'esm',platform:'browser',target:'es2022',legalComments:'inline',plugins:[mujocoCspPlugin]});

const mujocoWasm = await readFile('../../node_modules/@mujoco/mujoco/mujoco.wasm');
if (mujocoWasm.length !== MUJOCO_WASM_BYTES || createHash('sha256').update(mujocoWasm).digest('hex') !== MUJOCO_WASM_SHA256) {
  throw new Error('Pinned @mujoco/mujoco@3.15.0 Wasm binary mismatch');
}
await build({
  entryPoints: {'cw-s02-worker': 'src/cw-s02-worker.ts'},
  outdir: 'dist',
  bundle: true,
  format: 'esm',
  platform: 'browser',
  target: 'es2022',
  legalComments: 'inline',
  plugins: [mujocoCspPlugin],
  define: {
    __MUJOCO_WASM_SHA256__: JSON.stringify(MUJOCO_WASM_SHA256),
    __MUJOCO_WASM_BYTES__: String(MUJOCO_WASM_BYTES),
  },
});
await writeFile('dist/mujoco.wasm', mujocoWasm);

const workerJs = await readFile('dist/cw-s02-worker.js', 'utf8');
if (workerJs.includes('new Function') || workerJs.includes('eval(')) {
  throw new Error('dist/cw-s02-worker.js contains dynamic JS eval');
}

const physicsRoot='../../../apps/mini-robot-simulator';
const pin=JSON.parse(await readFile(`${physicsRoot}/physics-build.json`,'utf8'));
const wasm=await readFile(`${physicsRoot}/mini-physics.wasm`);
if(wasm.length!==pin.bytes||createHash('sha256').update(wasm).digest('hex')!==pin.sha256) throw new Error('Rebuild pinned SIM-3 physics before building the performance lab');
await build({entryPoints:{performance:'src/performance/app.ts','lab-physics':'src/performance/physics-worker.ts','lab-render':'src/performance/render-worker.ts'},outdir:'dist',bundle:true,format:'esm',platform:'browser',target:'es2022',legalComments:'inline',define:{__LAB_PHYSICS_SHA256__:JSON.stringify(pin.sha256),__LAB_PHYSICS_BYTES__:String(pin.bytes)}});
await writeFile('dist/lab-physics.wasm',wasm);
const fixtureRoot='../../../packages/scene-fixtures/mini-workbench',manifestRaw=await readFile(`${fixtureRoot}/scene.json`),manifest=JSON.parse(manifestRaw);
for(const asset of [manifest.tileset,...manifest.assets]) {if(!/^[a-z0-9-]+\.(json|glb)$/.test(asset.uri))throw Error('Invalid static asset name');const bytes=await readFile(`${fixtureRoot}/${asset.uri}`);if(bytes.length!==asset.bytes||createHash('sha256').update(bytes).digest('hex')!==asset.sha256)throw Error(`Static asset pin mismatch: ${asset.uri}`);}
const manifestPin={uri:'scene.json',bytes:manifestRaw.length,sha256:createHash('sha256').update(manifestRaw).digest('hex')};
await mkdir('dist/scene-decoders',{recursive:true});
const decoderRuntime=JSON.parse(await readFile('../../../packages/scene-fixtures/decoder-runtime.json','utf8')),decoderPins=decoderRuntime.assets;
if(decoderRuntime.schema!=='seedcore.scene-decoder-runtime.v1'||decoderRuntime.threeVersion!=='0.181.1'||JSON.stringify(decoderPins.map(p=>p.uri))!=='["draco_wasm_wrapper.js","draco_decoder.wasm"]')throw Error('Unsupported reviewed decoder runtime');
for(const pin of decoderPins) {const bytes=await readFile(`../../node_modules/three/examples/jsm/libs/draco/gltf/${pin.uri}`);if(bytes.length!==pin.bytes||createHash('sha256').update(bytes).digest('hex')!==pin.sha256)throw Error(`Decoder differs from reviewed runtime: ${pin.uri}`);await writeFile(`dist/scene-decoders/${pin.uri}`,bytes);}
await build({entryPoints:{scene:'src/scene/app.ts','scene-worker':'src/scene/scene-worker.ts'},outdir:'dist',bundle:true,format:'esm',platform:'browser',target:'es2022',legalComments:'inline',define:{__STATIC_MANIFEST_PIN__:JSON.stringify(manifestPin),__STATIC_DECODER_PINS__:JSON.stringify(decoderPins)}});
await writeFile('dist/scene-build.json',JSON.stringify({profile:'seedcore.static-scene.v1',manifestPin,decoderPins},null,2)+'\n');
for(const file of ['index.html','app.css','favicon.svg','performance.html','performance.css','scene.html','scene.css']) await copyFile(`src/${file}`,`dist/${file}`);
const notices = await Promise.all(['@mujoco/mujoco/package.json','@mujoco/mujoco/README.md','three/LICENSE','three/examples/jsm/libs/draco/README.md','3d-tiles-renderer/LICENSE','ajv/LICENSE','fast-deep-equal/LICENSE'].map(async name=>`${name}\n${await readFile(`../../node_modules/${name}`,'utf8')}`));
notices.unshift(`@mujoco/mujoco 3.15.0 · Google DeepMind · Apache-2.0\nSource: https://github.com/google-deepmind/mujoco/tree/main/wasm\nSeedCore modifies the generated JS invokers into static closures for CSP; Wasm bytes are unchanged.\n\n${await readFile('../../../LICENSE','utf8')}`);
await writeFile('dist/third-party-notices.txt',notices.join('\n\n'));
