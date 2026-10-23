import type {AssemblyNode,RelativeTransform} from '@seedcore/contracts';
import {AssemblyStore,RobotCanvas,loadPlacementCatalog,discoverSnapCandidates,makeSnapProposal,commitSnapProposal,suggestPlacementPose,partForNode,composePose,inversePose,worldTransforms,type ProxyScene,type ProxyNode,type PlacementCatalog,type PlacementSource,type PlacementRequest,type SnapCandidate,type SnapProposal} from '@seedcore/robot-canvas';

/** Transient staging UI. No proposal or palette state is persisted in an assembly. */
export function setupPlacement(store:AssemblyStore<ProxyScene>,canvas:RobotCanvas|undefined):()=>void {
  const el=<T extends HTMLElement>(id:string)=>document.getElementById(id) as T;
  const input=(id:string)=>el<HTMLInputElement>(id),select=(id:string)=>el<HTMLSelectElement>(id),button=(id:string)=>el<HTMLButtonElement>(id);
  let catalog:PlacementCatalog|undefined,controller:AbortController|undefined,loadGeneration=0,attemptedDigest:string|undefined,disposed=false;
  let currentKey='',sourceKey='',candidates:SnapCandidate[]=[],request:PlacementRequest|undefined,proposal:SnapProposal|undefined;
  let binding:{revisionDigest:string;authorityEpoch:number}|undefined;
  const message=(text:string,error=false)=>{el('placement-status').textContent=text;el('placement-status').dataset.error=String(error);};
  const clear=(text?:string,keepDrag=false)=>{
    request=undefined;proposal=undefined;binding=undefined;candidates=[];select('snap-candidate').replaceChildren();select('snap-candidate').disabled=true;button('commit-placement').disabled=true;
    canvas?.setGhost(null);if(!keepDrag)canvas?.setPlacementDrag(undefined);if(text)message(text);
  };
  const tabs=['inspect','placement','drc','simulation'] as const;
  const activate=(name:(typeof tabs)[number])=>{
    for(const pane of tabs){const active=pane===name;el(`${pane}-panel`).hidden=!active;button(`${pane}-tab`).setAttribute('aria-selected',String(active));button(`${pane}-tab`).tabIndex=active?0:-1;}
  };
  for(const name of tabs){button(`${name}-tab`).onclick=()=>activate(name);button(`${name}-tab`).onkeydown=event=>{
    if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const idx=tabs.indexOf(name);const next=event.key==='Home'?tabs[0]:event.key==='End'?tabs[tabs.length-1]:event.key==='ArrowRight'?tabs[(idx+1)%tabs.length]:tabs[(idx+tabs.length-1)%tabs.length];activate(next);button(`${next}-tab`).focus();}
  };}
  const source=():PlacementSource=>{
    const current=store.getState().current;if(!current||!catalog)throw new Error('Load a build and its catalog first');
    if(select('placement-mode').value==='move'){
      const selected=current.selection;if(selected?.kind!=='node')throw new Error('Select a part in the graph to move its subtree');
      return {kind:'move',nodeId:selected.id};
    }
    const part=catalog.parts.find(p=>p.partId===select('part-choice').value);if(!part)throw new Error('Select a catalog part');
    return {kind:'new',node:{node_id:input('instance-id').value,part_id:part.partId,part_version:part.version,part_sha256:part.sha256,role:part.role}};
  };
  const sourceNode=(value:PlacementSource):AssemblyNode=>{
    if(value.kind==='new')return value.node;
    const node=store.getState().current?.assembly.nodes.find(n=>n.node_id===value.nodeId);if(!node)throw new Error('Selected node is unavailable');return structuredClone(node) as AssemblyNode;
  };
  const configureSource=()=>{
    clear('Stage a part to preview a mount. The accepted draft stays unchanged.');
    const current=store.getState().current;if(!current||!catalog)return;
    const moving=select('placement-mode').value==='move';el('new-part-fields').hidden=moving;input('instance-id').readOnly=moving;
    if(moving)input('instance-id').value=current.selection?.kind==='node'?current.selection.id:'';
    else {
      const part=catalog.parts.find(p=>p.partId===select('part-choice').value);if(!part)return;
      const base=part.partId.split('.').at(-1)!.replace(/[^a-z0-9_-]/g,'_').slice(0,50);let n=1,id='';
      do{id=`${base}_${String(n++).padStart(2,'0')}`;}while(current.assembly.nodes.some(node=>node.node_id===id));input('instance-id').value=id;
    }
    try {
      const part=partForNode(catalog,sourceNode(source()));select('child-port').replaceChildren(...part.ports.map(port=>new Option(port.port_id,port.port_id)));
      if(part.ports.some(p=>p.port_id==='mount.bottom'))select('child-port').value='mount.bottom';
    } catch(error){select('child-port').replaceChildren();message(String(error instanceof Error?error.message:error),true);}
  };
  const readPose=():RelativeTransform=>{
    const number=(id:string)=>{const text=input(id).value;if(!text.trim()||!Number.isFinite(Number(text)))throw new Error('Enter finite position and quaternion numbers');return Number(text);};
    return {position_m:[number('pose-x')/1000,number('pose-y')/1000,number('pose-z')/1000],quaternion_wxyz:[number('pose-w'),number('pose-qx'),number('pose-qy'),number('pose-qz')]};
  };
  const fillPose=(pose:RelativeTransform)=>{
    ['pose-x','pose-y','pose-z'].forEach((id,i)=>{input(id).value=String(pose.position_m[i]*1000);});
    ['pose-w','pose-qx','pose-qy','pose-qz'].forEach((id,i)=>{input(id).value=String(pose.quaternion_wxyz[i]);});
  };
  const ghost=(value:PlacementRequest,pose:RelativeTransform):ProxyNode[]=>{
    const current=store.getState().current!;
    if(value.source.kind==='new'){
      const part=partForNode(catalog!,value.source.node);return [{id:value.source.node.node_id,label:part.name,role:part.role,transform:pose,positions:[...part.positions],indices:[...part.indices]}];
    }
    const ids=new Set([value.source.nodeId]);for(let changed=true;changed;){changed=false;for(const edge of current.assembly.mechanical_tree)if(ids.has(edge.parent_node_id)&&!ids.has(edge.child_node_id)){ids.add(edge.child_node_id);changed=true;}}
    const delta=composePose(pose,inversePose(worldTransforms(current.assembly)[value.source.nodeId]));
    return current.scene.nodes.filter(node=>ids.has(node.id)).map(node=>({...node,positions:[...node.positions],indices:[...node.indices],transform:composePose(delta,node.transform)}));
  };
  const commit=async()=>{
    const selected=proposal,expected=binding,palette=catalog;
    if(!selected||!expected||!palette||store.getState().loading){message('Find a current compatible mount before committing.',true);return;}
    const result=await commitSnapProposal(store,palette,{...expected,proposal:selected});
    if(result==='committed')message('Mount committed as a new immutable revision. Undo restores the previous build.');
    else if(result==='rejected')message(`Mount rejected. ${store.getState().error??'The previous build is retained.'}`,true);
  };
  const showCandidate=()=>{
    const current=store.getState().current;if(!current||!catalog||!request)return;
    const candidate=candidates[Number(select('snap-candidate').value)];if(!candidate){proposal=undefined;binding=undefined;button('commit-placement').disabled=true;canvas?.setGhost(null);return;}
    proposal=makeSnapProposal(current.assembly,catalog,request,candidate);binding={revisionDigest:current.revisionDigest,authorityEpoch:store.getState().authorityEpoch};
    canvas?.setGhost(ghost(request,candidate.worldTransform),true);button('commit-placement').disabled=false;
    message(`${candidates.length} compatible mount${candidates.length===1?'':'s'} · ${(candidate.distanceM*1000).toFixed(2)} mm capture. Preview only; draft unchanged.`);
  };
  const evaluate=()=>{
    clear(undefined,true);const state=store.getState();if(!state.current||!catalog||state.loading)return;
    try {
      request={source:source(),childPortId:select('child-port').value,pose:readPose()};
      const result=discoverSnapCandidates(state.current.assembly,catalog,request);candidates=result.candidates;
      select('snap-candidate').replaceChildren(...candidates.map((c,i)=>new Option(`${c.parentNodeId} / ${c.parentPortId} · ${(c.distanceM*1000).toFixed(2)} mm`,String(i))));select('snap-candidate').disabled=!candidates.length;
      if(candidates.length)showCandidate();else {canvas?.setGhost(ghost(request,request.pose),false);message(`No compatible open mount within 15 mm and 5°. ${result.rejections.slice(0,3).join('; ')}. Draft unchanged.`,true);}
      const base={revisionDigest:state.current.revisionDigest,authorityEpoch:state.authorityEpoch};
      canvas?.setPlacementDrag({pose:structuredClone(request.pose),onPose:(next:RelativeTransform)=>{
        const live=store.getState();if(live.current?.revisionDigest!==base.revisionDigest||live.authorityEpoch!==base.authorityEpoch){clear();return;}fillPose(next);evaluate();
      },onDrop:()=>{void commit();}});
    }catch(error){clear();message(error instanceof Error?error.message:'Invalid placement',true);}
  };
  const loadCatalog=async(digest:string)=>{
    attemptedDigest=digest;const generation=++loadGeneration;controller?.abort();controller=new AbortController();const active=controller;
    const timer=setTimeout(()=>active.abort(),10000);el('catalog-status').textContent='Checking catalog and proxy asset pins…';button('catalog-retry').hidden=true;el<HTMLFieldSetElement>('placement-fields').disabled=true;
    try {
      const next=await loadPlacementCatalog(digest,active.signal);
      if(disposed||generation!==loadGeneration||store.getState().current?.scene.catalogDigest!==digest)return;
      catalog=next;select('part-choice').replaceChildren(...catalog.parts.map(p=>new Option(p.name.replace(' - illustrative draft',''),p.partId)));
      select('part-choice').value=catalog.parts.some(p=>p.partId==='seedcore.sensor-hat')?'seedcore.sensor-hat':catalog.parts[0].partId;el('catalog-status').textContent=`${catalog.parts.length} proxy parts · catalog and asset pins checked`;
      el<HTMLFieldSetElement>('placement-fields').disabled=store.getState().loading;configureSource();
    }catch(error){if(!disposed&&generation===loadGeneration){el('catalog-status').textContent=`Catalog unavailable. ${error instanceof Error?error.message:'Load failed'}`;button('catalog-retry').hidden=false;active.abort();}}
    finally{clearTimeout(timer);}
  };
  const unsubscribe=store.subscribe(state=>{
    const nextKey=state.current?`${state.current.revisionDigest}:${state.authorityEpoch}`:'';
    const nextSourceKey=select('placement-mode').value==='move'?JSON.stringify(state.current?.selection):'';
    if(state.loading||nextKey!==currentKey||nextSourceKey!==sourceKey)clear();
    const changed=nextKey!==currentKey||nextSourceKey!==sourceKey;currentKey=nextKey;sourceKey=nextSourceKey;
    el<HTMLFieldSetElement>('placement-fields').disabled=state.loading||!state.current||catalog?.catalogDigest!==state.current.scene.catalogDigest;
    const digest=state.current?.scene.catalogDigest;
    if(attemptedDigest&&digest&&attemptedDigest!==digest){++loadGeneration;controller?.abort();attemptedDigest=undefined;}
    if(changed&&catalog&&state.current&&catalog.catalogDigest===digest)configureSource();
    if(state.current&&catalog?.catalogDigest!==state.current.scene.catalogDigest&&attemptedDigest!==state.current.scene.catalogDigest)void loadCatalog(state.current.scene.catalogDigest);
  });
  button('catalog-retry').onclick=()=>{const digest=store.getState().current?.scene.catalogDigest;if(digest)void loadCatalog(digest);};
  select('placement-mode').onchange=configureSource;select('part-choice').onchange=configureSource;
  select('snap-candidate').onchange=showCandidate;
  el<HTMLFormElement>('placement-form').onsubmit=event=>{event.preventDefault();evaluate();};
  el('placement-form').oninput=event=>{if(!['placement-mode','part-choice','snap-candidate'].includes((event.target as HTMLElement).id))evaluate();};
  button('stage-placement').onclick=()=>{
    try {const current=store.getState().current;if(!current||!catalog)throw new Error('Load a build first');const preferred=current.selection?.kind==='node'?current.selection.id:undefined;fillPose(suggestPlacementPose(current.assembly,catalog,source(),select('child-port').value,preferred));evaluate();}
    catch(error){clear();message(error instanceof Error?error.message:'No open mount',true);}
  };
  button('commit-placement').onclick=()=>{void commit();};button('clear-placement').onclick=()=>clear('Preview cleared; accepted draft unchanged.');
  return ()=>{disposed=true;++loadGeneration;controller?.abort();unsubscribe();clear();};
}
