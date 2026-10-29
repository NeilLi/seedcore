import {canonicalAssemblyString,parseStrictJson} from '@seedcore/contracts';
import {readBounded, type CapturedBodyPose} from '@seedcore/robot-canvas';
import {createCwBuildCandidate,gestureFrameAtTick,gestureHash,type CompiledGesture,type CompiledMjcf,type GestureBinding,type CwBuildCandidate} from '@seedcore/wasm-sim-bridge';

/** Client of a state-owning native simulation service. No browser token issuer or dispatch loop. */
export function setupGovernedSimulation(host: {
  current:()=>{model:CompiledMjcf;gesture:CompiledGesture;binding:GestureBinding};
  stopOffline:()=>void; display:(bodies:CapturedBodyPose[]|null)=>void;
}) {
  const el=<T extends HTMLElement>(id:string)=>document.getElementById(id) as T;
  const button=(id:string)=>el<HTMLButtonElement>(id);
  let profile:any, attempt:string|undefined, token:any, candidate:CwBuildCandidate|undefined;
  let generation=0, disposed=false, pending=false, stopping=false, timer:ReturnType<typeof setTimeout>|undefined;
  let capture:any, controller:AbortController|undefined;
  const status=(text:string,state:string)=>{el('gov-status').textContent=text;el('gov-status').dataset.state=state;};
  async function request(path:string, body?:unknown, signal?:AbortSignal, keepalive=false):Promise<any> {
    const response=await fetch(path,{...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:canonicalAssemblyString(body)}),signal,keepalive});
    const text=new TextDecoder('utf-8',{fatal:true}).decode(await readBounded(response,262144,{allowErrorStatus:true}));
    if(!response.ok)throw new Error(`Service rejected request (${response.status}): ${text.slice(0,300)}`);
    return parseStrictJson(text);
  }
  const currentCandidate=()=>{
    if(!profile?.configured)throw new Error('No trusted simulation endpoint configured');
    const c=host.current();return createCwBuildCandidate(c.model,c.gesture,c.binding,profile.endpointId);
  };
  const checkCurrent=()=>{
    if(!candidate||currentCandidate().candidateDigest!==candidate.candidateDigest)throw new Error('Build/gesture/endpoint changed');
  };
  const clear=()=>{
    capture=undefined;token=undefined;candidate=undefined;
    button('gov-start').disabled=true;button('gov-export').disabled=true;
    el<HTMLInputElement>('gov-tick').disabled=true;el('gov-frame').textContent='No governed capture.';
    el('gov-values').replaceChildren();host.display(null);
  };
  const refresh=()=>{
    let eligible=false;try{eligible=currentCandidate().binding.modelDigest===profile.modelDigest;}catch{}
    button('gov-admit').disabled=!eligible||pending;
  };
  const cancelRemote=(id:string,revoke=false)=>request(`/api/cw-g01/${id}/cancel`,{revoke},undefined,true);
  const invalidate=(reason='Build or gesture changed; request fresh admission.')=>{
    generation++;controller?.abort();controller=undefined;clearTimeout(timer);timer=undefined;
    const old=attempt;attempt=undefined;pending=false;stopping=false;clear();button('gov-stop').disabled=true;
    if(old)void cancelRemote(old).catch(()=>{});
    if(profile?.configured)status(reason,'stale');refresh();
  };
  const paint=(index:number)=>{
    checkCurrent();const sample=capture?.samples[index];if(!sample)return;
    host.display(sample.bodies);
    el('gov-frame').textContent=`Captured tick ${sample.tick} · ${sample.simTimeSeconds.toFixed(3)} s · read-only native simulation`;
    const g=host.current().gesture;
    el('gov-values').replaceChildren(...g.tracks.map((t,i)=>{
      const row=document.createElement('div');row.textContent=`${t.jointId}: target ${sample.ctrl[i].toFixed(6)} rad · observed ${sample.qpos[i].toFixed(6)} rad`;return row;
    }));
  };
  const acceptCapture=(raw:any)=>{
    checkCurrent();const c=host.current(), {captureDigest,...payload}=raw;
    if(raw.schemaVersion!=='seedcore.cw-g01.capture.v1'||raw.scope!=='local_simulation_only'||raw.physicalAcceptance!==false||raw.signed!==false||
      raw.sourceDigest!==profile.sourceDigest||raw.executorDigest!==profile.executorDigest||gestureHash(payload)!==captureDigest||raw.summary.id!==attempt||raw.summary.candidateDigest!==candidate!.candidateDigest||
      canonicalAssemblyString(raw.summary.binding)!==canonicalAssemblyString(candidate!.binding)||raw.summary.modelDigest!==candidate!.binding.modelDigest||
      !['completed','stopped','fenced'].includes(raw.summary.state)||!Array.isArray(raw.samples)||raw.samples.length!==raw.summary.executedSubsteps||raw.samples.length>120)
      throw new Error('Governed capture scope/binding/coverage mismatch');
    for(const [i,s] of raw.samples.entries()){
      const frame=gestureFrameAtTick(c.gesture,i+1);
      if(s.tick!==i+1||Math.abs(s.simTimeSeconds-(i+1)*.002)>1e-12||!Array.isArray(s.qpos)||s.qpos.length!==c.gesture.tracks.length||
        !s.qpos.every(Number.isFinite)||canonicalAssemblyString(s.ctrl)!==canonicalAssemblyString(frame.targetRad)||
        !Array.isArray(s.bodies)||s.bodies.length!==c.model.manifest.bodies.length||
        s.bodies.some((b:any,j:number)=>b.nodeId!==c.model.manifest.bodies[j].nodeId))throw new Error('Invalid captured frame');
    }
    if(raw.summary.state==='completed'&&raw.samples.length!==120)throw new Error('Incomplete capture cannot claim completion');
    capture=raw;
    const slider=el<HTMLInputElement>('gov-tick');slider.max=String(Math.max(0,raw.samples.length-1));slider.value='0';slider.disabled=!raw.samples.length;
    button('gov-export').disabled=false;if(raw.samples.length)paint(0);
  };
  async function terminal(summary:any,gen:number){
    clearTimeout(timer);timer=undefined;
    pending=false;button('gov-start').disabled=true;button('gov-stop').disabled=true;refresh();
    status(`${summary.state}: ${summary.executedSubsteps}/120 substeps${summary.reason?` · ${summary.reason}`:''}. Simulation only.`,summary.state);
    if(!attempt||!candidate||!summary.candidateDigest||!['completed','stopped','fenced'].includes(summary.state))return;
    const raw=await request(`/api/cw-g01/${attempt}/capture`,undefined,controller?.signal);
    if(gen!==generation||disposed)return;
    acceptCapture(raw);
  }
  function poll(gen:number){
    timer=setTimeout(async()=>{
      if(gen!==generation||!attempt||disposed)return;
      try{
        checkCurrent();const summary=await request(`/api/cw-g01/${attempt}/status`,undefined,controller?.signal);
        if(gen!==generation||disposed)return;
        if(['admitted','running','starting'].includes(summary.state)){
          if(summary.state==='running'&&!stopping)status(`Running · ${summary.executedSubsteps}/120 native substeps · admission enforced by service.`,'running');
          poll(gen);
        }else await terminal(summary,gen);
      }catch(e){if(gen===generation){invalidate('Service connection lost; local attempt deadline remains enforced.');status(String(e),'failed');}}
    },50);
  }
  button('gov-admit').onclick=async()=>{
    invalidate('Preparing current candidate…');
    const gen=generation;
    try{
      if(document.hidden)throw new Error('Cannot request a governed attempt in a hidden page');
      host.stopOffline();candidate=currentCandidate();attempt=crypto.randomUUID();controller=new AbortController();
      pending=true;refresh();button('gov-stop').disabled=false;status('Checking trusted registration, delegation and PDP policy…','checking');
      const result=await request('/api/cw-g01/admit',{requestId:attempt,candidate},controller.signal);
      if(gen!==generation||disposed||stopping)return;
      checkCurrent();
      if(result.state!=='admitted'){await terminal(result,gen);return;}
      token=result.executionToken;
      if(result.candidateDigest!==candidate.candidateDigest||result.endpointId!==profile.endpointId||!token)throw new Error('Admission reply binding mismatch');
      button('gov-start').disabled=false;status(`Admitted for local simulation · token ${result.tokenId}. Start before ${result.validUntil}.`,'admitted');poll(gen);
    }catch(e){if(gen===generation){invalidate();status(`Admission unavailable: ${String(e)}`,'denied');}}
  };
  button('gov-start').onclick=async()=>{
    const gen=generation;
    try{
      checkCurrent();if(!attempt||!token)throw new Error('Fresh admission required');
      if(document.hidden)throw new Error('Hidden page cannot start an attempt');
      button('gov-start').disabled=true;status('Verifying token and claiming this attempt once…','starting');
      const result=await request(`/api/cw-g01/${attempt}/start`,{executionToken:token,candidateDigest:candidate!.candidateDigest,binding:candidate!.binding,endpointId:profile.endpointId},controller?.signal);
      if(gen!==generation||disposed||stopping)return;
      checkCurrent();if(result.state==='running')status('Running · native state is owned by the trusted simulation service.','running');
      else await terminal(result,gen);
    }catch(e){if(gen===generation){invalidate();status(`Start refused: ${String(e)}`,'denied');}}
  };
  button('gov-stop').onclick=async()=>{
    const id=attempt,gen=generation;if(!id)return;
    stopping=true;
    button('gov-stop').disabled=true;button('gov-start').disabled=true;status('Stop requested; waiting for service acknowledgement…','stopping');
    try{const result=await cancelRemote(id);if(gen===generation)await terminal(result,gen);}
    catch(e){if(gen===generation){invalidate();status(`Stop acknowledgement unavailable: ${String(e)}`,'failed');}}
  };
  el<HTMLInputElement>('gov-tick').oninput=()=>{try{paint(Number(el<HTMLInputElement>('gov-tick').value));}catch{invalidate();}};
  button('gov-export').onclick=()=>{
    try{
      checkCurrent();if(!capture)throw new Error('No terminal capture');
      const url=URL.createObjectURL(new Blob([canonicalAssemblyString(capture)+'\n'],{type:'application/json'}));
      const a=document.createElement('a');a.href=url;a.download='attempt.cw-g01.capture.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(e){invalidate();status(String(e),'failed');}
  };
  const onHidden=()=>{if(document.hidden&&attempt)invalidate('Hidden page: previous attempt cancelled. Fresh admission required.');};
  document.addEventListener('visibilitychange',onHidden);
  void request('/api/cw-g01/profile').then(p=>{
    if(disposed)return;profile=p;
    el('gov-profile').textContent=p.configured?`${p.endpointId} · ${p.profile} · physical acceptance: false`:(p.reason||'No trusted endpoint configured.');
    status(p.configured?'Validate the exact reference gesture, then request admission.':'No trusted endpoint configured. Offline rehearsal remains available.',p.configured?'idle':'unavailable');refresh();
  }).catch(()=>{if(!disposed){el('gov-profile').textContent='Governed service unavailable.';status('No trusted endpoint configured. Offline rehearsal remains available.','unavailable');}});
  return {invalidate,refresh,dispose(){disposed=true;invalidate('Disposed');document.removeEventListener('visibilitychange',onHidden);}};
}
