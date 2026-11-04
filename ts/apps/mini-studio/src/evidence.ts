import {canonicalAssemblyString,parseStrictJson} from '@seedcore/contracts';
import {readBounded} from '@seedcore/robot-canvas';
import {gestureHash} from '@seedcore/wasm-sim-bridge';

export interface EvidenceCurrent {
  attempt:string; context:any; trustDigest:string; summary:any;
}
const MAX_BUNDLE=2*1024*1024;
const same=(a:unknown,b:unknown)=>canonicalAssemblyString(a)===canonicalAssemblyString(b);
const outcomes=['verified_completed','verified_interrupted','quarantine','unavailable','verifier_disagreement'];

/** Validate display authority against context retained before the bundle download. */
export function validateEvidenceResult(raw:any,current:EvidenceCurrent,bundleDigest:string):any {
  const c=current.context,s=raw?.summary;
  if(raw?.schemaVersion!=='seedcore.cw-g02.studio-verification.v1'||raw.scope!=='local_simulation_only'||raw.physicalAcceptance!==false||
    raw.executionAuthority!=='none'||!outcomes.includes(raw.disposition)||typeof raw.agreement!=='boolean'||
    raw.bundleSha256!==bundleDigest||!/^[a-f0-9]{64}$/.test(raw.retainedBundleSha256)||
    raw.matchesRetainedBundle!==(bundleDigest===raw.retainedBundleSha256)||!same(raw.expectedContext,c)||
    raw.expectedContextDigest!==gestureHash(c)||raw.trustSnapshotDigest!==current.trustDigest||
    !s||s.id!==current.attempt||s.endpointId!==c.endpointId||s.candidateDigest!==c.candidateDigest||
    !same(s.binding,c.binding)||s.modelDigest!==c.binding.modelDigest||s.sourceDigest!==c.sourceDigest||s.executorDigest!==c.executorDigest||
    s.state!==current.summary.state||s.reason!==current.summary.reason||s.executedSubsteps!==current.summary.executedSubsteps||
    !Number.isInteger(s.executedSubsteps)||s.executedSubsteps<1||s.executedSubsteps>120||s.totalSubsteps!==120)
    throw new Error('Evidence response does not match the current attempt, instance, revision or trust snapshot.');
  for(const name of ['python','rust']) {
    const report=raw[`${name}Report`],text=raw[`${name}ReportJson`];
    if((report===null)!==(text===null)||text!==null&&(typeof text!=='string'||!same(parseStrictJson(text),report)))
      throw new Error('Verifier report download differs from the displayed report.');
  }
  if(raw.disposition.startsWith('verified_')) {
    const p=raw.pythonReport,r=raw.rustReport;
    if(!raw.agreement||!raw.matchesRetainedBundle||!p||!r||
      [p,r].some(v=>v.schemaVersion!=='seedcore.cw-g02.verification.v1'||v.verified!==true||v.disposition!==raw.disposition||
        v.scope!=='local_simulation_only'||v.physicalAcceptance!==false||v.executionAuthority!=='none'||v.bundleSha256!==bundleDigest||
        v.expectedContextDigest!==raw.expectedContextDigest||v.trustSnapshotDigest!==current.trustDigest)||!same(p.sourceRefs,r.sourceRefs)||
      (raw.disposition==='verified_completed'&&(s.state!=='completed'||s.executedSubsteps!==120))||
      (raw.disposition==='verified_interrupted'&&(s.state!=='stopped'||s.executedSubsteps>=120)))
      throw new Error('Both independent verifiers and the retained original are required for a verified result.');
  }
  return raw;
}

export function setupEvidenceInspector(host:{current:()=>EvidenceCurrent;unavailableReason?:()=>string}) {
  const el=<T extends HTMLElement>(id:string)=>document.getElementById(id) as T;
  const button=(id:string)=>el<HTMLButtonElement>(id);
  const input=el<HTMLInputElement>('gov-evidence-import');
  let generation=0,controller:AbortController|undefined,owner:EvidenceCurrent|undefined;
  let inspected:Blob|undefined,result:any,busy=false,disposed=false;
  const setStatus=(text:string,state:string)=>{el('gov-evidence-status').textContent=text;el('gov-evidence-status').dataset.state=state;};
  function available(){try{return host.current();}catch{return undefined;}}
  function current(){
    const actual=host.current();
    if(!owner||!same(actual,owner))throw new Error('Attempt or authoring revision changed. Inspect the new attempt.');
    return actual;
  }
  function refresh(){
    const eligible=!!available();
    if(!eligible&&!owner&&!busy)setStatus(host.unavailableReason?.()||'A known terminal attempt and configured trust are required.','unavailable');
    button('gov-evidence-verify').disabled=!eligible||busy;input.disabled=!eligible||busy;
    button('gov-evidence-bundle').disabled=!eligible||!inspected||busy;
    button('gov-evidence-context').disabled=!eligible||!owner||busy;
    button('gov-evidence-python').disabled=!eligible||!result?.pythonReportJson||busy;
    button('gov-evidence-rust').disabled=!eligible||!result?.rustReportJson||busy;
  }
  function invalidate(){
    generation++;controller?.abort();controller=undefined;busy=false;owner=undefined;inspected=undefined;result=undefined;input.value='';
    el('gov-evidence-details').replaceChildren();
    setStatus('Verify a known terminal attempt under operator-configured trust.','unavailable');refresh();
  }
  async function bytes(response:Response,limit:number){
    const data=await readBounded(response,limit,{allowErrorStatus:true});
    if(!response.ok)throw new Error(`Evidence service (${response.status}): ${new TextDecoder().decode(data).slice(0,300)}`);
    return data;
  }
  function check(gen:number){if(disposed||generation!==gen)throw new DOMException('Inspection superseded','AbortError');current();}
  function paint(raw:any){
    const label:any={verified_completed:'Verified completed',verified_interrupted:'Verified interrupted',quarantine:'Quarantined',
      unavailable:'Verification unavailable',verifier_disagreement:'Verifier disagreement'};
    setStatus(`${label[raw.disposition]} · local simulation only. ${raw.reason||''}`,raw.disposition);
    const c=raw.expectedContext,s=raw.summary;
    const fields=[['Scope','Local simulation; physical acceptance: false; execution authority: none'],
      ['Outcome',`${s.state}${s.reason?` · ${s.reason}`:''}; ${s.executedSubsteps}/${s.totalSubsteps} captured substeps`],
      ['Attempt',`${c.requestId} · instance ${c.instanceId}`],['Endpoint',c.endpointId],['Model',c.binding.modelDigest],
      ['Revision / epoch',`${c.binding.revisionDigest} / ${c.binding.authorityEpoch}`],['Candidate',c.candidateDigest],
      ['Source',c.sourceDigest],['Executor',c.executorDigest],['Trust snapshot',raw.trustSnapshotDigest],
      ['Inspected bundle',raw.bundleSha256],['Retained original',raw.retainedBundleSha256],
      ['Python',raw.pythonReport?`${raw.pythonReport.disposition}${raw.pythonReport.error?` · ${raw.pythonReport.error}`:''}`:'Unavailable'],
      ['Rust',raw.rustReport?`${raw.rustReport.disposition}${raw.rustReport.error?` · ${raw.rustReport.error}`:''}`:'Unavailable']];
    el('gov-evidence-details').replaceChildren(...fields.map(([label,value])=>{
      const row=document.createElement('div');row.textContent=`${label}: ${value}`;return row;
    }));
  }
  async function inspect(file?:File){
    const gen=++generation;controller?.abort();controller=new AbortController();
    owner=undefined;inspected=file;result=undefined;busy=true;el('gov-evidence-details').replaceChildren();
    try{
      owner=structuredClone(host.current());
      setStatus('Verifying original bytes with Python and Rust…','checking');refresh();
      let raw:Uint8Array;
      if(file){
        if(file.size>MAX_BUNDLE||file.size===0)throw new Error('Imported evidence must contain 1 byte to 2 MiB. The selected file is retained for inspection.');
        raw=await bytes(new Response(file.stream()),MAX_BUNDLE);check(gen);
      }else{
        raw=await bytes(await fetch(`/api/cw-g02/${owner.attempt}/evidence`,{signal:controller.signal}),MAX_BUNDLE);check(gen);
        inspected=new Blob([new Uint8Array(raw)],{type:'application/json'});
      }
      const hashBytes=await crypto.subtle.digest('SHA-256',new Uint8Array(raw));check(gen);
      const hash=Array.from(new Uint8Array(hashBytes),v=>v.toString(16).padStart(2,'0')).join('');
      const response=await fetch(`/api/cw-g02/${owner.attempt}/verify`,{method:'POST',headers:{'Content-Type':'application/json'},
        body:new Blob([new Uint8Array(raw)],{type:'application/json'}),signal:controller.signal});
      const data=await bytes(response,262144);check(gen);
      result=validateEvidenceResult(parseStrictJson(new TextDecoder('utf-8',{fatal:true}).decode(data)),owner,hash);
      paint(result);
    }catch(error){
      if(gen===generation&&!disposed){setStatus(String(error),'unavailable');result=undefined;}
    }finally{if(gen===generation&&!disposed){busy=false;refresh();}}
  }
  function download(blob:Blob,name:string){
    current();const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  button('gov-evidence-verify').onclick=()=>void inspect();
  input.onchange=()=>{const file=input.files?.[0];if(file)void inspect(file);};
  button('gov-evidence-bundle').onclick=()=>{try{if(inspected)download(inspected,'inspected.cw-g02.bundle.json');}catch{invalidate();}};
  button('gov-evidence-context').onclick=()=>{try{if(owner)download(new Blob([canonicalAssemblyString(owner.context)+'\n'],{type:'application/json'}),'attempt.cw-g02.expected.json');}catch{invalidate();}};
  for(const language of ['python','rust'])button(`gov-evidence-${language}`).onclick=()=>{
    try{const raw=result?.[`${language}ReportJson`];if(raw)download(new Blob([raw],{type:'application/json'}),`attempt.${language}.verification.json`);}catch{invalidate();}
  };
  invalidate();
  return {refresh,invalidate,dispose(){disposed=true;invalidate();}};
}
