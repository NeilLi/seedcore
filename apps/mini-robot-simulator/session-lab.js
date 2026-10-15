/* Host-backed simulation fixtures. No keys, token issuance, or serial APIs here. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let current = null, refreshing = false, busy = false, downloading = false, generation = 0;
  const message = (text, error = false) => { $('service-message').textContent = text; $('service-message').className = `service-note${error ? ' error' : ''}`; };
  async function api(path, body) {
    const response = await fetch(`/api/spine-demo/${path}`, body === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    });
    let data;
    try { data = await response.json(); } catch { throw new Error('Launch the local session-lab service to run this experiment.'); }
    if (!response.ok) throw new Error(data.detail || 'The experiment stopped.');
    return data;
  }
  function render(data) {
    current = data;
    const active = data.session?.state === 'active';
    $('decision').textContent = data.decision.status === 'denied' ? 'Denied' : active ? 'Admitted' : data.session ? 'Stopped' : 'Ready';
    $('reason').textContent = data.session?.reason || data.decision.reason;
    $('session-state').textContent = data.session?.state || 'No session';
    $('joint-state').textContent = data.session?.positions_rad.map(q => `${q.toFixed(4)} rad`).join(' · ') || '—';
    $('proof-state').textContent = data.verification?.disposition || 'Not yet sealed';
    $('record').textContent = JSON.stringify(data, null, 2);
    $('stop').disabled = $('revoke').disabled = !active;
    $('download').disabled = !data.verification || downloading;
    $('physics-preview').contentWindow?.postMessage({type:'seedcore.spine.preview.v1',
      profile:'simulation_only', running:active, joints:data.joints,
      target_rad:data.joints ? Array(data.joints).fill(data.target_rad) : []}, location.origin);
    if (!active) refreshing = false;
  }
  async function start() {
    if (busy) return;
    generation++;
    busy = true; refreshing = false; $('propose').disabled = true;
    try {
      render(await api('start', {case:$('experiment').value, joints:Number($('joint-count').value)}));
      refreshing = current.session?.state === 'active';
      message('Local simulation · no hardware connection.');
    } catch (error) { message(error.message, true); }
    finally { busy = false; $('propose').disabled = false; }
  }
  $('propose').addEventListener('click', start);
  for (const [id, operation] of [['stop','stop'],['revoke','revoke']]) {
    $(id).addEventListener('click', async () => {
      generation++;
      refreshing = false;
      try { render(await api(operation, {})); } catch (error) { message(error.message, true); }
    });
  }
  $('download').addEventListener('click', async () => {
    downloading = true; $('download').disabled = true;
    try {
      const evidence = await api('evidence');
      const verified = evidence.rust_verification.verified;
      $('proof-state').textContent = evidence.rust_verification.disposition;
      message(verified ? 'Rust verified the captured simulation attempt.' : 'Rust did not verify this evidence. Inspect the downloaded report.', !verified);
      const link = document.createElement('a');
      link.href = URL.createObjectURL(new Blob([JSON.stringify(evidence, null, 2)], {type:'application/json'}));
      link.download = 'seedcore-simulation-evidence.json'; link.click(); URL.revokeObjectURL(link.href);
    } catch (error) { message(error.message, true); }
    finally { downloading = false; $('download').disabled = !current?.verification; }
  });
  document.addEventListener('visibilitychange', () => { if (document.hidden) refreshing = false; });
  setInterval(async () => {
    if (!refreshing || busy || document.hidden) return;
    const attempt = generation;
    busy = true;
    try {
      const data = await api('refresh', {});
      if (attempt === generation) render(data);
    } catch (error) {
      refreshing = false;
      if (attempt !== generation) return;
      try {
        const data = await api('state');
        if (attempt !== generation) return;
        render(data);
        message(data.session?.state === 'fenced' ? 'Session ended. Review the recorded outcome.' : error.message,
          data.session?.state !== 'fenced');
      } catch { message(error.message, true); }
    }
    finally { busy = false; }
  }, 100);
  setInterval(async () => {
    if (busy || document.hidden) return;
    const attempt = generation;
    try {
      const data = await api('state');
      if (!busy && attempt === generation) render(data);
    } catch (error) {
      if (attempt === generation) { refreshing = false; message(error.message, true); }
    }
  }, 100);
  api('state').then(data => { render(data); $('propose').disabled = false; message('Local simulation · no hardware connection.'); })
    .catch(error => message(error.message, true));
})();
