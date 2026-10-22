// Display FK only. This shader is never a dynamics or execution authority.
export const fkShader = /* wgsl */ `
struct Params { chains:u32, columns:u32, rows:u32, unused:u32 }
@group(0) @binding(0) var<storage,read> angles:array<vec4f>;
@group(0) @binding(1) var<storage,read_write> transforms:array<mat4x4f>;
@group(0) @binding(2) var<uniform> params:Params;
@compute @workgroup_size(64)
fn fk(@builtin(global_invocation_id) id:vec3u) {
  let i=id.x; if(i>=params.chains) {return;}
  var lengths=array<f32,3>(0.10,0.08,0.06);
  var a=0.0; var x=0.0; var y=0.0;
  for(var j=0u;j<3u;j++) {
    a+=angles[i][j];let c=cos(a);let s=sin(a);let l=lengths[j];
    transforms[i*3u+j]=mat4x4f(vec4f(c*l,s*l,0,0),vec4f(-s*0.014,c*0.014,0,0),vec4f(0,0,0.014,0),vec4f(x+c*l*0.5,y+s*l*0.5,0,1));
    x+=c*l;y+=s*l;
  }
}`;
export const renderShader = /* wgsl */ `
struct Params { chains:u32, columns:u32, rows:u32, unused:u32 }
@group(0) @binding(0) var<storage,read> transforms:array<mat4x4f>;
@group(0) @binding(1) var<uniform> params:Params;
struct Vertex { @builtin(position) position:vec4f, @location(0) color:vec3f }
@vertex fn vertex(@location(0) xy:vec2f,@builtin(instance_index) instance:u32)->Vertex {
  let chain=instance/3u;let cell=vec2f(f32(chain%params.columns),f32(chain/params.columns));
  let p=transforms[instance]*vec4f(xy,0,1);
  // All orientations fit: total reach is 0.24 m, inside the padded cell.
  let uv=p.xy*vec2f(1.6,1.6)+vec2f(0.5,0.5);
  let clip=(cell+uv)/vec2f(f32(params.columns),f32(params.rows));
  var colors=array<vec3f,3>(vec3f(0.33,0.83,0.68),vec3f(0.39,0.68,0.93),vec3f(0.97,0.66,0.33));
  var out:Vertex;out.position=vec4f(clip.x*2.0-1.0,1.0-clip.y*2.0,0.0,1.0);out.color=colors[instance%3u];return out;
}
@fragment fn fragment(in:Vertex)->@location(0) vec4f {return vec4f(in.color,1);}
`;
