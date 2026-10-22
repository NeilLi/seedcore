/** Exact build-pinned, streaming-bounded local asset load before compilation. */
export async function readPinnedPhysics(response: Response, bytes: number, sha256: string): Promise<Uint8Array<ArrayBuffer>> {
  if(!Number.isInteger(bytes)||bytes<1||bytes>1048576||!/^[0-9a-f]{64}$/.test(sha256))throw new Error('Invalid physics build pin');
  if(!response.ok||!response.body)throw new Error('Pinned physics fetch failed');
  const out=new Uint8Array(bytes),reader=response.body.getReader();let offset=0;
  try {
    for(;;) {const {done,value}=await reader.read();if(done)break;if(offset+value.length>bytes)throw new Error('Physics byte count exceeds pin');out.set(value,offset);offset+=value.length;}
  }catch(error){await reader.cancel();throw error;}finally{reader.releaseLock();}
  if(offset!==bytes)throw new Error('Physics byte count mismatch');
  const actual=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',out)),v=>v.toString(16).padStart(2,'0')).join('');
  if(actual!==sha256)throw new Error('Physics SHA-256 mismatch');return out;
}
