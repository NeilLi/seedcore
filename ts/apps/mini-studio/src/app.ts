import {setupPlacement} from './placement.js';
import {setupDrc} from './drc.js';
import {canonicalAssemblyString} from '@seedcore/contracts';
import {AssemblyStore, RobotCanvas, prepareProxyScene, fetchAssemblyText, type ProxyScene, type Frozen, type StoreState, type Selection} from '@seedcore/robot-canvas';
const element = <T extends HTMLElement>(id:string) => document.getElementById(id) as T;
const button = (id:string) => element<HTMLButtonElement>(id);
const store = new AssemblyStore<ProxyScene>(prepareProxyScene);
const storageKey = 'seedcore.mini-studio.draft.v2';
let canvas: RobotCanvas | undefined, shownDigest: string | undefined, savedDigest: string | undefined;
let storageError = '';
try { canvas = new RobotCanvas(element<HTMLCanvasElement>('viewport'),selection=>store.select(selection)); }
catch {element('canvas-error').textContent = '3D preview unavailable in this browser. Use the parts and connections lists to inspect this draft.';}
function item(label:string,detail:string,selection:Selection,current:Frozen<Selection>): HTMLButtonElement {
  const result = document.createElement('button'), text = document.createElement('span'), hint = document.createElement('small');
  text.textContent = label; hint.textContent = detail; result.append(text,hint);
  result.setAttribute('aria-pressed',String(current?.kind===selection?.kind && current?.id===selection?.id));
  result.addEventListener('click',()=>store.select(selection)); return result;
}
function render(state:Frozen<StoreState<ProxyScene>>): void {
  const current = state.current;
  element('status').textContent = state.error ? `Import/edit rejected. Previous draft retained. ${state.error}` : state.loading ? 'Checking candidate and pinned assets… Previous accepted draft remains visible.' : current ? `Revision ${current.sequence} · ${current.assembly.nodes.length} parts · catalog and mesh pins checked · authoring only${storageError}` : 'Load the tabletop starter or import a v2 draft.';
  element('status').dataset.error = String(Boolean(state.error));
  button('undo').disabled = !state.canUndo; button('redo').disabled = !state.canRedo;
  button('export').disabled = !current; button('rename').disabled = !current;
  if(!current) return;
  const assembly = current.assembly;
  if (shownDigest !== current.revisionDigest) {
    canvas?.setBuild(current.scene,assembly); shownDigest = current.revisionDigest;
    element<HTMLInputElement>('name').value = assembly.identity.name;
  }
  if (savedDigest !== current.revisionDigest) {
    try { localStorage.setItem(storageKey,canonicalAssemblyString(assembly)); savedDigest = current.revisionDigest; storageError=''; }
    catch {storageError=' · Browser storage unavailable; export your draft to keep it.'; element('status').textContent += storageError;}
  }
  element('build-name').textContent = assembly.identity.name; element('node-count').textContent = String(assembly.nodes.length); element('edge-count').textContent = String(assembly.mechanical_tree.length);
  element('nodes').replaceChildren(...assembly.nodes.map(n=>item(n.display_name??n.node_id,`${n.role} · ${n.node_id}`,{kind:'node',id:n.node_id},current.selection)));
  element('edges').replaceChildren(...assembly.mechanical_tree.map(e=>item(e.edge_id,e.connection_type==='rigid_mount'?'Rigid mount':'Revolute · simulation limits',{kind:'edge',id:e.edge_id},current.selection)));
  canvas?.select(current.selection);
  const selection = current.selection;
  element('selection-title').textContent = selection ? selection.id : 'Select a part or connection';
  const node = selection?.kind==='node' ? assembly.nodes.find(n=>n.node_id===selection.id) : undefined;
  const edge = selection?.kind==='edge' ? assembly.mechanical_tree.find(e=>e.edge_id===selection.id) : undefined;
  element('selection-detail').textContent = node ? `${node.part_id} @ ${node.part_version} · exact catalog bytes pinned` : edge ? `${edge.parent_node_id} → ${edge.child_node_id} · ${edge.connection_type}` : 'Review the graph without changing the physical model.';
  element('content-digest').textContent = current.assemblyDigest;
  element('revision').textContent = `${current.sequence} · ${current.revisionDigest.slice(0,16)}…`;
}
store.subscribe(render);
button('starter').onclick = ()=>{void store.loadFrom(signal=>fetchAssemblyText('/api/starter',signal));};
button('import-text').onclick = ()=>{void store.loadText(element<HTMLTextAreaElement>('raw').value);};
element<HTMLInputElement>('file').onchange = event=>{
  const file = (event.target as HTMLInputElement).files?.[0];
  if(file) void store.loadFrom(async()=>{if(file.size>262144) throw new Error('File exceeds 256 KiB'); return new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());});
  (event.target as HTMLInputElement).value='';
};
button('undo').onclick = ()=>store.undo(); button('redo').onclick = ()=>store.redo(); button('fit').onclick = ()=>canvas?.fit();
element<HTMLFormElement>('rename-form').onsubmit = event=>{event.preventDefault(); const name=element<HTMLInputElement>('name').value; void store.edit(draft=>{draft.identity.name=name;});};
button('export').onclick = ()=>{
  const current = store.getState().current; if(!current) return;
  const url=URL.createObjectURL(new Blob([canonicalAssemblyString(current.assembly)+'\n'],{type:'application/json'}));
  const anchor=document.createElement('a'); anchor.href=url; anchor.download='assembly.sc-assembly.json'; anchor.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
};
const disposePlacement=setupPlacement(store,canvas);
const disposeDrc=setupDrc(store);
window.addEventListener('pagehide',()=>{disposePlacement();disposeDrc();store.dispose();canvas?.dispose();},{once:true});
let restored:string|null=null; try{restored=localStorage.getItem(storageKey);}catch{storageError=' · Browser storage unavailable; export your draft.';}
if(restored) void store.loadText(restored);
else void store.loadFrom(signal=>fetchAssemblyText('/api/starter',signal));
