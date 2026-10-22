// Original, synthetic mini-workbench visuals. No physical collision/part data.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {createRequire}=require('node:module');
const root=path.resolve(__dirname,'../..'),requireTs=createRequire(path.join(root,'ts/apps/mini-studio/package.json'));
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const target=path.join(root,'packages/scene-fixtures/mini-workbench');
function geometry(boxes) {
 const positions=[],normals=[],indices=[];
 const faces=[[[1,0,0],[[1,-1,-1],[1,1,-1],[1,1,1],[1,-1,1]]],[[-1,0,0],[[-1,1,-1],[-1,-1,-1],[-1,-1,1],[-1,1,1]]],[[0,1,0],[[1,1,-1],[-1,1,-1],[-1,1,1],[1,1,1]]],[[0,-1,0],[[-1,-1,-1],[1,-1,-1],[1,-1,1],[-1,-1,1]]],[[0,0,1],[[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]]],[[0,0,-1],[[-1,1,-1],[1,1,-1],[1,-1,-1],[-1,-1,-1]]]];
 for(const [x,y,z,sx,sy,sz] of boxes)for(const [normal,corners] of faces){const base=positions.length/3;for(const p of corners){positions.push(x+p[0]*sx/2,y+p[1]*sy/2,z+p[2]*sz/2);normals.push(...normal);}indices.push(base,base+1,base+2,base,base+2,base+3);}
 // glTF is Y-up; tileset boxes and the studio are Z-up. NASA applies Rx(+pi/2).
 for(let i=0;i<positions.length;i+=3){const y=positions[i+1],ny=normals[i+1];positions[i+1]=positions[i+2];positions[i+2]=-y;normals[i+1]=normals[i+2];normals[i+2]=-ny;}
 return {positions:new Float32Array(positions),normals:new Float32Array(normals),indices:new Uint32Array(indices)};
}
async function main() {
 const d=await requireTs('draco3d').createEncoderModule({}),files=new Map(),assets=[];
 function glb(name,boxes,color) {
  const g=geometry(boxes),mesh=new d.Mesh(),builder=new d.MeshBuilder(),encoder=new d.Encoder(),encoded=new d.DracoInt8Array();
  try {
   builder.AddFacesToMesh(mesh,g.indices.length/3,g.indices);const p=builder.AddFloatAttributeToMesh(mesh,d.POSITION,g.positions.length/3,3,g.positions),n=builder.AddFloatAttributeToMesh(mesh,d.NORMAL,g.normals.length/3,3,g.normals);
   encoder.SetEncodingMethod(d.MESH_SEQUENTIAL_ENCODING);encoder.SetSpeedOptions(5,5);encoder.SetAttributeQuantization(d.POSITION,16);encoder.SetAttributeQuantization(d.NORMAL,10);
   const count=encoder.EncodeMeshToDracoBuffer(mesh,encoded);if(count<=0)throw Error('Draco encoding failed');
   const compressed=Buffer.alloc(count);for(let i=0;i<count;i++)compressed[i]=encoded.GetValue(i);
   const min=[0,1,2].map(axis=>Math.min(...g.positions.filter((_,i)=>i%3===axis))),max=[0,1,2].map(axis=>Math.max(...g.positions.filter((_,i)=>i%3===axis)));
   const doc={asset:{version:'2.0',generator:'SeedCore synthetic static fixture v1'},extensionsUsed:['KHR_draco_mesh_compression'],extensionsRequired:['KHR_draco_mesh_compression'],scene:0,scenes:[{nodes:[0]}],nodes:[{mesh:0}],meshes:[{primitives:[{attributes:{POSITION:0,NORMAL:1},indices:2,material:0,mode:4,extensions:{KHR_draco_mesh_compression:{bufferView:0,attributes:{POSITION:p,NORMAL:n}}}}]}],materials:[{pbrMetallicRoughness:{baseColorFactor:[...color,1],metallicFactor:0,roughnessFactor:.8},doubleSided:false}],buffers:[{byteLength:count}],bufferViews:[{buffer:0,byteOffset:0,byteLength:count}],accessors:[{componentType:5126,count:g.positions.length/3,type:'VEC3',min,max},{componentType:5126,count:g.normals.length/3,type:'VEC3'},{componentType:5125,count:g.indices.length,type:'SCALAR'}]};
   let json=Buffer.from(JSON.stringify(doc));json=Buffer.concat([json,Buffer.alloc((4-json.length%4)%4,32)]);const bin=Buffer.concat([compressed,Buffer.alloc((4-count%4)%4)]),header=Buffer.alloc(20),binHeader=Buffer.alloc(8);
   header.writeUInt32LE(0x46546c67,0);header.writeUInt32LE(2,4);header.writeUInt32LE(28+json.length+bin.length,8);header.writeUInt32LE(json.length,12);header.writeUInt32LE(0x4e4f534a,16);binHeader.writeUInt32LE(bin.length,0);binHeader.writeUInt32LE(0x004e4942,4);
   const data=Buffer.concat([header,json,binHeader,bin]);files.set(name,data);assets.push({uri:name,bytes:data.length,sha256:hash(data),triangles:g.indices.length/3,decodedGeometryBytes:g.positions.byteLength+g.normals.byteLength+g.indices.byteLength});
  }finally{for(const o of [mesh,builder,encoder,encoded])d.destroy(o);}
 }
 const centers=[[-.3,-.3],[.3,-.3],[-.3,.3],[.3,.3]];
 glb('coarse.glb',centers.map(([x,y])=>[x,y,-.055,.56,.56,.025]),[.24,.40,.37]);
 const children=centers.map(([x,y],i)=>{
  const boxes=[[x,y,-.055,.56,.56,.025]];
  for(let a=0;a<8;a++)for(let b=0;b<8;b++)boxes.push([x+(a-3.5)*.067,y+(b-3.5)*.067,-.03,.016,.016,.025]);
  glb(`detail-${i}.glb`,boxes,[.46,.58,.53]);
  return {boundingVolume:{box:[x,y,-.04,.29,0,0,0,.29,0,0,0,.04]},geometricError:0,refine:'REPLACE',content:{uri:`detail-${i}.glb`}};
 });
 const tileset={asset:{version:'1.1'},geometricError:.06,root:{boundingVolume:{box:[0,0,-.04,.6,0,0,0,.6,0,0,0,.04]},geometricError:.06,refine:'REPLACE',content:{uri:'coarse.glb'},children}};
 const raw=Buffer.from(JSON.stringify(tileset,null,2)+'\n');files.set('tileset.json',raw);
 const manifest={schema:'seedcore.static-scene.v1',scope:'visual_only',physicalAcceptance:false,executionAuthority:'none',origin_m:[6371000,1000000,-2000000],tileset:{uri:'tileset.json',bytes:raw.length,sha256:hash(raw)},assets};
 files.set('scene.json',Buffer.from(JSON.stringify(manifest,null,2)+'\n'));
 for(const [name,data] of files)if(process.argv.includes('--check')) {if(!fs.existsSync(path.join(target,name))||!fs.readFileSync(path.join(target,name)).equals(data))throw Error(`Generated static fixture stale: ${name}`);}else{fs.mkdirSync(target,{recursive:true});fs.writeFileSync(path.join(target,name),data);}
 console.log(`Static scene: ${assets.length} original Draco GLBs, ${assets.reduce((s,a)=>s+a.triangles,0)} total source triangles; ${process.argv.includes('--check')?'matches source':'generated'}`);
}
main().catch(e=>{console.error(e);process.exitCode=1;});
