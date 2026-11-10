import type {AssemblyStore, ProxyScene} from '@seedcore/robot-canvas';

/** Guide actions use the same checked controls as the full workbench. */
export function setupBeginner(store: AssemblyStore<ProxyScene>): () => void {
  const button = (id: string) => document.getElementById(id) as HTMLButtonElement;
  const message = document.getElementById('lesson-status')!;
  const mode = button('detail-mode');
  const details = [...document.querySelectorAll<HTMLDetailsElement>('details.technical')];
  let technical = false;
  const setMode = (value: boolean) => {
    technical = value;
    mode.setAttribute('aria-pressed', String(value));
    mode.textContent = value ? 'Hide technical details' : 'Show technical details';
    details.forEach(detail => { detail.open = value; });
    try { localStorage.setItem('seedcore.studio.technical', String(value)); } catch { /* Optional preference. */ }
  };
  try { setMode(localStorage.getItem('seedcore.studio.technical') === 'true'); } catch { setMode(false); }
  mode.onclick = () => setMode(!technical);
  button('lesson-start').onclick = () => {
    button('gallery-synthetic').click();
    message.textContent = 'Opening your practice project. When it is ready, choose step 2.';
  };
  button('lesson-prepare').onclick = () => {
    button('simulation-tab').click();
    document.getElementById('simulation-panel')!.scrollIntoView({block:'start', behavior:'smooth'});
    button('sim-rehearsal-preset').click();
    message.textContent = 'Practice settings requested. When ready, choose step 3 to make a movement.';
  };
  button('lesson-motion').onclick = () => {
    button('moments-tab').click();
    document.getElementById('moments-panel')!.scrollIntoView({block:'start', behavior:'smooth'});
    message.textContent = 'Choose a size, create a tilt & return, check it, then try the movement.';
  };
  button('lesson-review').onclick = () => {
    button('moments-tab').click();
    document.getElementById('moment-tick')!.scrollIntoView({block:'center', behavior:'smooth'});
    message.textContent = 'Drag the recording slider to compare target and measured positions. Save the recording or your project file.';
  };
  const update = () => {
    button('lesson-start').disabled = store.getState().loading;
    button('lesson-prepare').disabled = button('sim-rehearsal-preset').disabled || store.getState().loading;
    button('lesson-motion').disabled = button('moment-example').disabled || store.getState().loading;
    button('lesson-review').disabled = (document.getElementById('moment-tick') as HTMLInputElement).disabled;
    if (store.getState().error) message.textContent = 'The project could not be changed. Your previous project is still here. See the message below and try again.';
  };
  const observer = new MutationObserver(update);
  for (const id of ['sim-rehearsal-preset','moment-example','moment-tick']) {
    observer.observe(document.getElementById(id)!, {attributes:true, attributeFilter:['disabled']});
  }
  const unsubscribe = store.subscribe(update);
  return () => { observer.disconnect(); unsubscribe(); };
}
