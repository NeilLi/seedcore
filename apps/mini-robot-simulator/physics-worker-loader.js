/* Synchronous loading is confined to worker startup, never the UI thread. */
'use strict';
importScripts('physics-build.js','physics-wasm.js');
const request = new XMLHttpRequest();
request.open('GET','mini-physics.wasm',false);
request.responseType='arraybuffer';
request.send();
if(request.status!==200 || !(request.response instanceof ArrayBuffer)) throw new Error('C++ physics module could not load.');
if (MiniSimContracts.sha256Bytes(new Uint8Array(request.response)) !== 'sha256:'+MiniPhysicsBuild.sha256) throw new Error('Physics build digest mismatch.');
globalThis.MiniRobotPhysics=MiniPhysicsWasm.create(request.response,MiniPhysicsBuild);
