import type {AssemblyStore, ProxyScene} from '@seedcore/robot-canvas';

/** Guide actions use the same checked controls as the full workbench. */
export function setupBeginner(store: AssemblyStore<ProxyScene>): () => void {
  const button = (id: string) => document.getElementById(id) as HTMLButtonElement;
  const message = document.getElementById('lesson-status')!;
  const mode = button('detail-mode');
  const guide = document.getElementById('task-guide')!;
  const title = document.getElementById('task-title')!;
  const explanation = document.getElementById('task-state')!;
  const next = button('task-next');
  let preparing = false, disposed = false, operation = 0;
  let openingFrom: string | undefined;
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
  button('robot-microduck').onclick = () => button('show-demo').click();
  button('lesson-start').onclick = () => {
    openingFrom = store.getState().current?.revisionDigest ?? '';
    button('gallery-synthetic').click();
    message.textContent = 'Opening the two-joint platform robot. Follow the task guide beside its picture.';
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
  const waitFor = async (ready:()=>boolean, ticket:number, revision:string) => {
    const until = performance.now() + 10000;
    while (!ready()) {
      if (disposed || ticket !== operation || store.getState().current?.revisionDigest !== revision)
        throw new Error('Project changed. Prepare the task again for your current robot.');
      if (performance.now() > until) throw new Error('Setup could not finish. Open Try it to inspect the current checks, then retry.');
      await new Promise(resolve=>setTimeout(resolve,40));
    }
    if (disposed || ticket !== operation || store.getState().current?.revisionDigest !== revision)
      throw new Error('Project changed. Prepare the task again for your current robot.');
  };
  const showTaskChart = () => {
    const chart = document.getElementById('motion-preview')!;
    const panel = document.getElementById('moments-panel')!;
    if (matchMedia('(min-width:1051px)').matches) {
      panel.scrollTop += chart.getBoundingClientRect().top-panel.getBoundingClientRect().top;
    } else chart.scrollIntoView({block:'center'});
  };
  const prepareTask = async () => {
    const revision = store.getState().current?.revisionDigest;
    if (!revision || preparing) return;
    preparing = true;
    document.getElementById('task-error')!.hidden = true;
    const ticket = ++operation;
    update();
    try {
      await waitFor(()=>!button('sim-rehearsal-preset').disabled,ticket,revision);
      button('sim-rehearsal-preset').click();
      await waitFor(()=>!button('moment-example').disabled,ticket,revision);
      button('moment-example').click();
      button('moment-compile').click();
      if (document.getElementById('moment-status')!.dataset.state !== 'compiled')
        throw new Error(document.getElementById('moment-status')!.textContent || 'The movement could not be checked.');
      button('moments-tab').click();
      showTaskChart();
      message.textContent = 'Plan ready. Preview the dashed target curves, then choose Run checked simulation in the task guide.';
    } catch (error) {
      if (!disposed && ticket === operation) {
        const failure = error instanceof Error ? error.message : String(error);
        message.textContent = failure;
        document.getElementById('task-error')!.textContent = failure;
        document.getElementById('task-error')!.hidden = false;
      }
    } finally {
      if (!disposed && ticket === operation) { preparing = false; update(); }
    }
  };
  next.onclick = () => {
    if (guide.dataset.stage === 'choose') button('lesson-start').click();
    else if (guide.dataset.stage === 'prepare') void prepareTask();
    else if (guide.dataset.stage === 'preview') {
      button('moments-tab').click();
      button('moment-run').click();
    } else if (guide.dataset.stage === 'review') {
      button('moments-tab').click();
      const slider = document.getElementById('moment-tick') as HTMLInputElement;
      slider.value = String(Math.floor(Number(slider.max)/2));
      slider.dispatchEvent(new Event('input'));
      showTaskChart();
      slider.focus({preventScroll:true});
    }
  };
  button('task-recording').onclick = () => button('moment-export').click();
  button('task-project').onclick = () => button('export').click();
  button('task-stop').onclick = () => button('moment-stop').click();
  const update = () => {
    button('lesson-start').disabled = store.getState().loading;
    button('lesson-prepare').disabled = button('sim-rehearsal-preset').disabled || store.getState().loading;
    button('lesson-motion').disabled = button('moment-example').disabled || store.getState().loading;
    button('lesson-review').disabled = (document.getElementById('moment-tick') as HTMLInputElement).disabled;
    const state = store.getState();
    const practice = state.current?.assembly.nodes.length === 4 && state.current.assembly.nodes.every(n=>n.part_id.startsWith('synthetic.cw-s01.'));
    if (openingFrom !== undefined && !state.loading) {
      if (practice && state.current?.revisionDigest !== openingFrom) {
        document.querySelector('.workbench')!.scrollIntoView({block:'start'});
        document.getElementById('task-error')!.hidden = true;
        openingFrom = undefined;
      } else if (state.error) openingFrom = undefined;
    }
    const motionState = document.getElementById('moment-status')!.dataset.state;
    const captured = !button('lesson-review').disabled;
    const running = ['loading','running','stopping'].includes(motionState ?? '');
    const stage = !practice ? 'choose' : preparing ? 'preparing' : running ? 'running' : captured ? 'review' : !button('moment-run').disabled ? 'preview' : 'prepare';
    guide.dataset.stage = stage;
    document.getElementById('task-progress')!.textContent = ({choose:'1 / 4 · CHOOSE YOUR ROBOT',prepare:'2 / 4 · PREPARE A TASK',preparing:'2 / 4 · CHECKING YOUR TASK',preview:'3 / 4 · PREVIEW & SIMULATE',running:'3 / 4 · SIMULATING',review:'4 / 4 · REVIEW & SAVE'})[stage];
    title.textContent = practice ? 'Tilt the platform, then return' : 'Start with a robot and a task';
    explanation.textContent = stage === 'choose' ? 'Open the practice robot for a guided simulation. Your current project can be restored with Undo.'
      : stage === 'preparing' ? 'Applying the tested simulation settings and checking the whole movement. Your robot will stay still until you choose Run.'
      : stage === 'prepare' ? 'Prepare a tiny movement for both joints. Then preview its target curves before running the simulation.'
      : stage === 'preview' ? 'Plan checked: the dashed curves below show the intended tilt and return. Run the simulation to see how the joints respond.'
      : stage === 'running' ? document.getElementById('moment-status')!.textContent
      : motionState === 'completed' ? 'A recording is ready. Compare dashed targets with solid measured positions: completing the run does not mean the joints followed the targets exactly.'
      : 'This run was interrupted. Review the recorded samples; they do not establish completion of the task.';
    next.textContent = ({choose:'Open practice robot',prepare:'Prepare tilt & return',preparing:'Checking task…',preview:'Run checked simulation',running:'Simulation in progress…',review:'Review target vs. result'})[stage];
    next.disabled = state.loading || preparing || running;
    button('task-stop').hidden = !running;
    button('task-stop').disabled = button('moment-stop').disabled;
    button('task-recording').hidden = !captured;
    button('task-project').hidden = !captured;
    button('task-recording').disabled = button('moment-export').disabled;
    button('task-project').disabled = !state.current || state.loading;
    if (['failed','rejected','interrupted'].includes(motionState ?? '') && !preparing && !captured) {
      explanation.textContent = document.getElementById('moment-status')!.textContent;
    }
    if (state.error) message.textContent = 'The project could not be changed. Your previous project is still here. See the message below and try again.';
  };
  const observer = new MutationObserver(update);
  for (const id of ['sim-rehearsal-preset','moment-example','moment-tick']) {
    observer.observe(document.getElementById(id)!, {attributes:true, attributeFilter:['disabled']});
  }
  for (const id of ['moment-status','sim-status']) observer.observe(document.getElementById(id)!, {attributes:true,attributeFilter:['data-state'],childList:true});
  const unsubscribe = store.subscribe(update);
  return () => { disposed = true; ++operation; observer.disconnect(); unsubscribe(); };
}
