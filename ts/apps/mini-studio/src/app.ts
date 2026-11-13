import {setupMicroduck} from './microduck.js';
import {setupBeginner} from './beginner.js';
import {setupGallery} from './gallery.js';
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
let disposeDemo: (()=>void)|undefined;
try { canvas = new RobotCanvas(element<HTMLCanvasElement>('viewport'),selection=>store.select(selection),mode=>{
  element('view-mode').textContent=mode==='captured'?'RECORDED SIMULATION VIEW':'DESIGN VIEW';
}); }
catch {element('canvas-error').textContent = '3D preview unavailable in this browser. Use the parts and connections lists to inspect this draft.';}
function item(label:string,detail:string,selection:Selection,current:Frozen<Selection>): HTMLButtonElement {
  const result = document.createElement('button'), text = document.createElement('span'), hint = document.createElement('small');
  text.textContent = label; hint.textContent = detail; result.append(text,hint);
  result.setAttribute('aria-pressed',String(current?.kind===selection?.kind && current?.id===selection?.id));
  result.addEventListener('click',()=>store.select(selection)); return result;
}
function render(state:Frozen<StoreState<ProxyScene>>): void {
  const current = state.current;
  element('status').textContent = state.error ? `Could not apply that change. Your previous project is still here. ${state.error}` : state.loading ? 'Opening your robot and checking its parts…' : current ? `Project saved in this browser · ${current.assembly.nodes.length} parts · simulation model${storageError}` : 'Choose a robot or open a saved project file.';
  element('status').dataset.error = String(Boolean(state.error));
  button('undo').disabled = !state.canUndo; button('redo').disabled = !state.canRedo;
  button('export').disabled = !current; button('rename').disabled = !current;
  if(!current) return;
  document.body.dataset.studioView='project';
  element('studio-heading').textContent = 'Assembly & simulation lab';
  element('studio-description').textContent = 'Inspect a draft assembly or test the supported synthetic model. Choose Microduck to return to the complete robot.';
  element<HTMLDetailsElement>('advanced-lab').open = true;
  element('fit').hidden=false;
  element('viewport-hint').textContent='Drag to orbit · scroll to zoom · click a part to inspect';
  disposeDemo?.();disposeDemo=undefined;
  try { localStorage.setItem('seedcore.studio.last-view','project'); } catch {}
  const assembly = current.assembly;
  const practice = assembly.nodes.every(n=>n.part_id.startsWith('synthetic.cw-s01.'));
  document.body.dataset.robotChoice = practice ? 'practice' : 'custom';
  element('robot-title').textContent = practice ? 'Two-joint platform robot' : 'Tabletop design';
  element('robot-purpose').textContent = practice ? 'A fixed base, two motor joints and a platform. The colored joint rings mark where it turns.' : 'Inspect and customize this design. Simulation availability depends on its current checks.';
  if (shownDigest !== current.revisionDigest) {
    canvas?.setBuild(current.scene,assembly); shownDigest = current.revisionDigest;
    element<HTMLInputElement>('name').value = assembly.identity.name;
  }
  if (savedDigest !== current.revisionDigest) {
    try { localStorage.setItem(storageKey,canonicalAssemblyString(assembly)); savedDigest = current.revisionDigest; storageError=''; }
    catch {storageError=' · Browser storage unavailable; export your draft to keep it.'; element('status').textContent += storageError;}
  }
  element('build-name').textContent = assembly.identity.name; element('node-count').textContent = String(assembly.nodes.length); element('edge-count').textContent = String(assembly.mechanical_tree.length);
  const anatomy:Record<string,[string,string]> = {base:['Fixed base','Supports the robot'],servo_0:['Motor joint 1','Turns the upper section'],servo_1:['Motor joint 2','Turns the platform'],payload:['Top platform','The part this task controls']};
  element('nodes').replaceChildren(...assembly.nodes.map(n=>item(practice ? anatomy[n.node_id]?.[0]??n.node_id : n.display_name??n.node_id,practice ? anatomy[n.node_id]?.[1]??n.role : `${n.role} · ${n.node_id}`,{kind:'node',id:n.node_id},current.selection)));
  element('edges').replaceChildren(...assembly.mechanical_tree.map(e=>item(e.edge_id,e.connection_type==='rigid_mount'?'Fixed attachment':'Turning joint',{kind:'edge',id:e.edge_id},current.selection)));
  canvas?.select(current.selection);
  const selection = current.selection;
  element('selection-title').textContent = selection ? selection.id : 'Select a part or connection';
  const node = selection?.kind==='node' ? assembly.nodes.find(n=>n.node_id===selection.id) : undefined;
  const edge = selection?.kind==='edge' ? assembly.mechanical_tree.find(e=>e.edge_id===selection.id) : undefined;
  element('selection-detail').textContent = node ? `${node.part_id} @ ${node.part_version} · exact catalog bytes pinned` : edge ? `${edge.parent_node_id} → ${edge.child_node_id} · ${edge.connection_type}` : 'Choose a part in the picture or list to learn about it.';
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
const disposeGallery=setupGallery(store);
const disposePlacement=setupPlacement(store,canvas);
const disposeDrc=setupDrc(store,canvas);
const disposeBeginner=setupBeginner(store);
window.addEventListener('pagehide',()=>{disposeDemo?.();disposeBeginner();disposeGallery();disposePlacement();disposeDrc();store.dispose();canvas?.dispose();},{once:true});
let restored:string|null=null; try{restored=localStorage.getItem(storageKey);}catch{storageError=' · Browser storage unavailable; export your draft.';}
button('resume-project').disabled=!restored;
button('resume-project').onclick=()=>{
  let latest:string|null=null;try{latest=localStorage.getItem(storageKey);}catch{}
  if(latest)void store.loadText(latest);
};
button('show-demo').onclick=()=>{
  try { localStorage.setItem('seedcore.studio.last-view','demo'); } catch {}
  location.reload();
};
button('open-lab').onclick=()=>{
  element<HTMLDetailsElement>('advanced-lab').open = true;
  element('advanced-lab').scrollIntoView({block:'start'});
};
// The complete robot is the entry point even when a prior lab draft exists.
// Resuming that draft is explicit and preserves its original storage bytes.
{
  element('status').textContent=restored ? 'Microduck · complete robot model. Your lab project is saved; choose Continue saved project to reopen it.' : 'Microduck · complete robot model · head-pose exploration';
  element('view-mode').textContent='MICRODUCK · VISUAL EXPLORER';
  element('fit').hidden=true;
  element('viewport-hint').textContent='Drag to look around · scroll to zoom · try the head controls';
  disposeDemo=setupMicroduck();
}
