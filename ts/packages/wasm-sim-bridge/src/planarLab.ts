/** Bounded synthetic SIM-3 load fixture, distinct from CW-S01 MJCF models. */
export const LAB_PROFILE = 'seedcore.planar-performance.v1';
export const LINK_LENGTHS = [.10,.08,.06] as const;
type Exports = {memory:WebAssembly.Memory;mini_tree_abi:()=>number;mini_tree_scratch:()=>number;mini_tree_eval:(op:number,ptr:number,n:number)=>number};
export class PlanarLab {
  readonly state: Float64Array;
  private b: Float64Array;
  private ptr: number;
  private e: Exports;
  constructor(bytes: BufferSource, readonly chains: number, readonly hz:500|1000) {
    if(!Number.isInteger(chains)||chains<1||chains>256||![500,1000].includes(hz)) throw new Error('Invalid planar fixture size');
    const module=new WebAssembly.Module(bytes);
    if(WebAssembly.Module.imports(module).some(i=>i.module!=='env'||!['sin','cos'].includes(i.name))) throw new Error('Unexpected physics import');
    this.e=new WebAssembly.Instance(module,{env:{sin:Math.sin,cos:Math.cos}}).exports as Exports;
    if(this.e.mini_tree_abi()!==2 || this.e.memory.buffer.byteLength!==131072) throw new Error('Incompatible SIM-3 Wasm');
    this.ptr=this.e.mini_tree_scratch();this.b=new Float64Array(this.e.memory.buffer,this.ptr,64);
    this.b[0]=3;
    for(let j=0;j<3;j++) {const l=LINK_LENGTHS[j];this.b[1+j]=l;this.b[4+j]=.05;this.b[7+j]=l/2;this.b[10+j]=.05*l*l/12;this.b[13+j]=.02;}
    this.b[16]=9.81;this.b[27]=1/hz;this.b[31]=.6;this.b[32]=1;
    this.b[28]=.5;this.b[29]=-.4;this.b[30]=.3;
    this.state=new Float64Array(chains*6);
    for(let i=0;i<chains;i++) {this.state[i*6]=.3+(i%7)*.01;this.state[i*6+1]=-.6;this.state[i*6+2]=.4;}
  }
  step(tick: number): void {
    this.b[23]=tick/this.hz;
    for(let i=0;i<this.chains;i++) {
      const k=i*6;
      for(let j=0;j<3;j++) {this.b[17+j]=this.state[k+j];this.b[20+j]=this.state[k+3+j];}
      const status=this.e.mini_tree_eval(6,this.ptr,64);
      if(status) throw new Error(`Planar Wasm step failed (${status})`);
      for(let j=0;j<3;j++) {this.state[k+j]=this.b[34+j];this.state[k+3+j]=this.b[37+j];}
    }
  }
  pack(out: Float32Array, gpu: boolean): void {
    if(out.length!==this.chains*(gpu?4:48)) throw new Error('Invalid snapshot shape');
    for(let i=0;i<this.chains;i++) {
      if(gpu) {for(let j=0;j<3;j++) out[i*4+j]=this.state[i*6+j];out[i*4+3]=0;}
      else writePlanarMatrices(this.state,i*6,out,i*48);
    }
  }
}
/** Column-major, meters, planar XY. Layout is mirrored by the WGSL FK kernel. */
export function writePlanarMatrices(q: ArrayLike<number>, qOffset: number, out: Float32Array, offset=0): void {
  let angle=0,x=0,y=0;
  for(let j=0;j<3;j++) {
    angle+=q[qOffset+j];const c=Math.cos(angle),s=Math.sin(angle),l=LINK_LENGTHS[j],k=offset+j*16;
    out.fill(0,k,k+16);out[k]=c*l;out[k+1]=s*l;out[k+4]=-s*.014;out[k+5]=c*.014;out[k+10]=.014;
    out[k+12]=x+c*l/2;out[k+13]=y+s*l/2;out[k+15]=1;x+=c*l;y+=s*l;
  }
}
