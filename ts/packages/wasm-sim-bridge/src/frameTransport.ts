/** Experimental, visual-only transport. No command or authority travels here. */
export const FRAME_PROTOCOL = 'seedcore.visual-frames.v1';
export type LabMode = 'transfer' | 'shared' | 'gpu';
export interface LabConfig { mode: LabMode; chains: number; hz: 500 | 1000; seconds: number }
export function validateLabConfig(value: unknown): LabConfig {
  const c = value as LabConfig;
  if (!c || Object.keys(c).sort().join(',') !== 'chains,hz,mode,seconds'
    || !['transfer','shared','gpu'].includes(c.mode) || !Number.isInteger(c.chains)
    || c.chains < 1 || c.chains > 256 || ![500,1000].includes(c.hz)
    || !Number.isInteger(c.seconds) || c.seconds < 2 || c.seconds > 30) throw new Error('Invalid bounded lab configuration');
  return {...c};
}
export const FRAME_SLOTS = 3;
const FREE = 0, WRITING = 1, READY = 2, READING = 3;
const HEADER_WORDS = FRAME_SLOTS * 4;
export function frameFloats(c: LabConfig): number { validateLabConfig(c); return c.chains * (c.mode === 'gpu' ? 4 : 48); }
export interface SharedFrames { buffer: SharedArrayBuffer; header: Int32Array; views: Float32Array[] }
export function sharedFrames(config: LabConfig, existing?: SharedArrayBuffer): SharedFrames {
  const n = frameFloats(config), bytes = HEADER_WORDS * 4 + FRAME_SLOTS * n * 4;
  const buffer = existing ?? new SharedArrayBuffer(bytes);
  if (!(buffer instanceof SharedArrayBuffer) || buffer.byteLength !== bytes) throw new Error('Shared frame size mismatch');
  return {buffer, header: new Int32Array(buffer,0,HEADER_WORDS),
    views: Array.from({length:FRAME_SLOTS},(_,i)=>new Float32Array(buffer,HEADER_WORDS*4+i*n*4,n))};
}
/** Single producer: only recycle FREE/READY slots, never a renderer-owned slot. */
export function publishFrame(f: SharedFrames, sequence: number, tick: number, fill: (view: Float32Array)=>void): boolean {
  if (!Number.isInteger(sequence) || sequence < 1 || sequence > 0x7fffffff || !Number.isInteger(tick) || tick < 0 || tick > 30000) throw new Error('Invalid frame stamp');
  let slot = -1;
  for (const state of [FREE, READY]) {
    for (let i=0;i<FRAME_SLOTS;i++) if (Atomics.compareExchange(f.header,i*4,state,WRITING) === state) {slot=i;break;}
    if (slot >= 0) break;
  }
  if (slot < 0) return false; // Dropping a visual snapshot never drops a physics tick.
  try { fill(f.views[slot]); Atomics.store(f.header,slot*4+1,sequence); Atomics.store(f.header,slot*4+2,tick); }
  catch (error) { Atomics.store(f.header,slot*4,FREE); throw error; }
  Atomics.store(f.header,slot*4,READY); return true;
}
export function acquireLatestFrame(f: SharedFrames, after: number): number {
  let slot=-1, newest=after;
  for(let i=0;i<FRAME_SLOTS;i++) if(Atomics.load(f.header,i*4)===READY) {
    const sequence=Atomics.load(f.header,i*4+1); if(sequence>newest) {slot=i;newest=sequence;}
  }
  if(slot<0 || Atomics.compareExchange(f.header,slot*4,READY,READING)!==READY) return -1;
  // A producer may have replaced the selected READY slot before the CAS. It is
  // still a complete snapshot; read its stamp only after ownership is acquired.
  if(Atomics.load(f.header,slot*4+1)<=after) {releaseFrame(f,slot);return -1;}
  return slot;
}
export function releaseFrame(f: SharedFrames, slot: number): void {
  if(!Number.isInteger(slot)||slot<0||slot>=FRAME_SLOTS||Atomics.compareExchange(f.header,slot*4,READING,FREE)!==READING) throw new Error('Invalid or duplicate frame release');
}
/** Three transferable loans, with exact sequence checks on return. */
export class TransferFramePool {
  private free: {id:number;buffer:ArrayBuffer}[];
  private loans = new Map<number,number>();
  readonly bytes: number;
  constructor(c: LabConfig) { this.bytes=frameFloats(c)*4; this.free=Array.from({length:FRAME_SLOTS},(_,id)=>({id,buffer:new ArrayBuffer(this.bytes)})); }
  take(sequence: number): {id:number;buffer:ArrayBuffer} | undefined {
    const slot=this.free.pop(); if(slot) this.loans.set(slot.id,sequence); return slot;
  }
  recycle(id: number, sequence: number, buffer: ArrayBuffer): void {
    if(!this.loans.has(id)||this.loans.get(id)!==sequence||!(buffer instanceof ArrayBuffer)||buffer.byteLength!==this.bytes) throw new Error('Invalid or duplicate transferable return');
    this.loans.delete(id);this.free.push({id,buffer});
  }
}
