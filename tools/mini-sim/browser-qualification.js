/* Developer-only qualification; uses the actual browser worker and transfers. */
(async () => {
  const C = MiniSimContracts, P = MiniRobotPhysics;
  const base = { target: [55*Math.PI/180,-70*Math.PI/180], strength: 16, mass: 0.7, motors: true, gravity: true };
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const report = { date: new Date().toISOString(), userAgent: navigator.userAgent,
    hardwareConcurrency: navigator.hardwareConcurrency, deviceMemoryGiB: navigator.deviceMemory ?? null,
    scope: 'Local browser worker/transfer/RAF harness; laptop only. Not full learner UI or release qualification.', results: [] };
  function qualify(lesson, changes, stall = false) {
    return new Promise((resolve, reject) => {
      const settings = { ...base, ...changes }, compiled = C.compile(settings);
      const worker = new Worker('../../apps/mini-robot-simulator/simulation-worker.js');
      const samples = [], frameIntervals = [], pauseLatencies = [], held = [];
      let seq = 0, lastTick = 0, lastFrame = null, raf, start, stallDone = false, paused = false, pauseSent;
      const watchdog = setTimeout(() => finish(new Error('Qualification timed out.')), 20000);
      function finish(error, result) {
        clearTimeout(watchdog); cancelAnimationFrame(raf); worker.terminate();
        error ? reject(error) : resolve(result);
      }
      function frame(time) {
        if (lastFrame !== null) frameIntervals.push(time-lastFrame);
        lastFrame = time; raf = requestAnimationFrame(frame);
      }
      raf = requestAnimationFrame(frame);
      function send(type, extra = {}) {
        worker.postMessage({ protocol: C.PROTOCOL, type, runId: 1, revision: 0, sequence: ++seq,
          applicationTick: lastTick, modelDigest: compiled.modelDigest, recipeDigest: compiled.recipeDigest, ...extra });
      }
      function recycle(message) {
        worker.postMessage({ protocol: C.PROTOCOL, type: 'recycle', bufferId: message.bufferId,
          frameSequence: message.frameSequence, buffer: message.buffer }, [message.buffer]);
        assert(message.buffer.byteLength === 0, 'transfer did not detach UI buffer');
      }
      worker.onerror = event => finish(new Error(event.message));
      worker.onmessage = ({ data: message }) => {
        try {
          assert(message.type !== 'rejected' && message.type !== 'error', message.error);
          lastTick = message.tick;
          if (message.buffer) {
            samples.push(...C.unpack(message.buffer,message.sampleCount));
            if (stall && !stallDone) {
              held.push(message);
              if (held.length === C.POOL_SIZE) {
                // Simulate the page not consuming snapshots, then block its event
                // loop. Worker must remain at this tick until buffers return.
                const end = performance.now()+250;
                while (performance.now()<end) {}
                pauseSent = performance.now(); send('pause');
              }
            } else recycle(message);
          }
          if (message.status === 'ready') { start = performance.now(); send('start'); }
          if (!stall && !paused && message.status === 'running' && message.tick >= 80) {
            paused = true; pauseSent = performance.now(); send('pause');
          }
          if (message.status === 'paused') {
            pauseLatencies.push(performance.now()-pauseSent);
            if (stall) {
              assert(message.tick === C.POOL_SIZE*C.CHUNK_TICKS, 'worker advanced with exhausted snapshot pool');
              stallDone = true; held.forEach(recycle);
            }
            send('start');
          }
          if (message.status === 'complete') {
            assert(samples.length === 361 && message.tick === C.TOTAL_TICKS, 'incomplete observation coverage');
            const model = P.createModel(compiled.parameters);
            let direct = P.createState(compiled.recipe.initial.q), maxError = 0;
            for (let tick = 0; tick <= C.TOTAL_TICKS; tick++) {
              if (tick%8 === 0) {
                const recorded = samples[tick/8];
                assert(Math.round(recorded.time/C.DT) === tick, 'missing or duplicated tick');
                for (const key of ['q','velocity']) for (let j = 0; j < 2; j++) {
                  maxError = Math.max(maxError,Math.abs(recorded[key][j]-direct[key][j]));
                }
              }
              if (tick < C.TOTAL_TICKS) direct = P.step(model,direct,
                s => settings.motors ? P.motor(model,s,settings.target,settings.strength) : [0,0],C.DT);
            }
            assert(maxError === 0, 'browser worker diverged from direct reference');
            frameIntervals.sort((a,b) => a-b);
            const frameP95Ms = frameIntervals[Math.ceil(frameIntervals.length*0.95)-1];
            finish(null, { lesson, stall, modelDigest: compiled.modelDigest, recipeDigest: compiled.recipeDigest,
              wallMs: performance.now()-start, samples: samples.length, finalTick: message.tick, maxAbsoluteTraceError: maxError,
              frameP95Ms, pauseLatenciesMs: pauseLatencies, diagnostics: message.diagnostics,
              gates: { frameP95: frameP95Ms <= 33, pauseAcknowledgement: pauseLatencies.every(x => x<=100),
                // One timer quantum (16.7 ms) over six seconds is the declared
                // wall-time measurement tolerance. Induced load must report waits.
                realtime: stall || message.diagnostics.activeWallMs <= 6000+C.CHUNK_TICKS*C.DT*1000,
                loadDiagnostic: !stall || message.diagnostics.bufferWaits > 0, coverage: true, trace: true } });
          }
        } catch (error) { finish(error); }
      };
      send('reset', { settings });
    });
  }
  try {
    for (const [lesson, changes, stall] of [['reach',{},false], ['gravity',{motors:false},false],
        ['heavy',{mass:1.8,strength:5},false], ['reach-ui-stall',{},true]]) {
      report.results.push(await qualify(lesson,changes,stall));
      document.getElementById('report').textContent = JSON.stringify(report,null,2);
    }
    report.passed = report.results.every(result => Object.values(result.gates).every(Boolean));
    document.getElementById('status').textContent = report.passed ? 'PASS — local qualification complete' : 'FAIL — inspect measured gates';
  } catch (error) {
    report.error = error.message; report.passed = false;
    document.getElementById('status').textContent = 'FAIL — '+error.message;
  }
  document.getElementById('report').textContent = JSON.stringify(report,null,2);
})();
