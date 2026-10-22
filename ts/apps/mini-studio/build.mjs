import {build} from 'esbuild';
import {mkdir,copyFile,readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
await mkdir('dist',{recursive:true});
await build({entryPoints:['src/app.ts'],outfile:'dist/app.js',bundle:true,format:'esm',platform:'browser',target:'es2022',legalComments:'inline'});
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
const notices = await Promise.all(['three/LICENSE','three/examples/jsm/libs/draco/README.md','3d-tiles-renderer/LICENSE','ajv/LICENSE','fast-deep-equal/LICENSE'].map(async name=>`${name}\n${await readFile(`../../node_modules/${name}`,'utf8')}`));
await writeFile('dist/third-party-notices.txt',notices.join('\n\n'));
