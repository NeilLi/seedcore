import {
  DrcWorkerCoordinator,
  parseDrcCatalogFromRaw,
  type DrcCatalog,
  type DrcFinding,
  type DrcReport,
} from '@seedcore/drc-solver';
import {
  AssemblyStore,
  readBounded,
  type Frozen,
  type ProxyScene,
  type Selection,
  type StoreState,
} from '@seedcore/robot-canvas';

async function fetchDrcCatalog(expectedDigest: string, signal: AbortSignal): Promise<DrcCatalog> {
  const response = await fetch('/api/placement-catalog', { signal });
  const data = JSON.parse(
    new TextDecoder('utf-8', { fatal: true }).decode(await readBounded(response, 2 * 1024 * 1024)),
  );
  if (
    data.scope !== 'offline_proxy_authoring' ||
    data.physical_acceptance !== false ||
    data.catalog_sha256 !== expectedDigest
  ) {
    throw new Error('DRC catalog scope or digest mismatch');
  }
  return parseDrcCatalogFromRaw({
    catalogSha256: data.catalog_sha256,
    catalogRawJson: data.catalog_raw_json,
    partDocuments: data.part_documents,
    provenance: 'verified_local_catalog',
  });
}

function selectionForFieldRefs(
  state: Frozen<StoreState<ProxyScene>>,
  fieldRefs: readonly string[],
): Selection {
  const assembly = state.current?.assembly;
  if (!assembly) return null;
  for (const ref of fieldRefs) {
    const nodeMatch = /^\/nodes\/(\d+)/.exec(ref);
    if (nodeMatch) {
      const node = assembly.nodes[Number(nodeMatch[1])];
      if (node) return { kind: 'node', id: node.node_id };
    }
    const netEpMatch = /^\/electrical_nets\/(\d+)\/endpoints\/(\d+)/.exec(ref);
    if (netEpMatch) {
      const ep = assembly.electrical_nets[Number(netEpMatch[1])]?.endpoints[Number(netEpMatch[2])];
      if (ep && assembly.nodes.some(n => n.node_id === ep.node_id)) {
        return { kind: 'node', id: ep.node_id };
      }
    }
    const edgeMatch = /^\/mechanical_tree\/(\d+)/.exec(ref);
    if (edgeMatch) {
      const edge = assembly.mechanical_tree[Number(edgeMatch[1])];
      if (edge) return { kind: 'edge', id: edge.edge_id };
    }
  }
  return null;
}

/** CW-A04 DRC & unknown-aware BOM panel. Never grants execution authority. */
export function setupDrc(store: AssemblyStore<ProxyScene>): () => void {
  const el = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
  const button = (id: string) => el<HTMLButtonElement>(id);
  let catalog: DrcCatalog | undefined;
  let catalogController: AbortController | undefined;
  let catalogGen = 0;
  let attemptedCatalogDigest: string | undefined;
  let evaluatedKey = '';
  let disposed = false;

  const coordinator = new DrcWorkerCoordinator(() => {
    const state = store.getState();
    if (!state.current) return null;
    return {
      revisionDigest: state.current.revisionDigest,
      assemblyDigest: state.current.assemblyDigest,
      catalogDigest: state.current.scene.catalogDigest,
      authorityEpoch: state.authorityEpoch,
    };
  });

  const setStatus = (text: string, error = false, state = 'ready') => {
    const statusEl = el('drc-status');
    statusEl.textContent = text;
    statusEl.dataset.error = String(error);
    statusEl.dataset.state = state;
  };

  const renderFindingItem = (finding: DrcFinding, state: Frozen<StoreState<ProxyScene>>): HTMLButtonElement => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.dataset.ruleId = finding.ruleId;
    btn.dataset.severity = finding.severity;
    btn.dataset.code = finding.code;
    const title = document.createElement('span');
    title.textContent = `[${finding.ruleId} · ${finding.severity.toUpperCase()}] ${finding.code}`;
    const detail = document.createElement('small');
    const refs = finding.fieldRefs.join(', ');
    detail.textContent = `${finding.message}${refs ? ` (${refs})` : ''}${finding.recommendation ? ` — ${finding.recommendation}` : ''}`;
    btn.append(title, detail);
    const target = selectionForFieldRefs(state, finding.fieldRefs);
    const currentSel = state.current?.selection;
    btn.setAttribute(
      'aria-pressed',
      String(Boolean(target && currentSel?.kind === target.kind && currentSel?.id === target.id)),
    );
    btn.addEventListener('click', () => {
      if (target) store.select(target);
    });
    return btn;
  };

  const renderReport = (report: DrcReport, revisionDigest: string, authorityEpoch: number) => {
    const state = store.getState();
    const dispEl = el('drc-disposition');
    dispEl.dataset.disposition = report.disposition;
    dispEl.textContent =
      report.disposition === 'conflict'
        ? `CONFLICT · ${report.counts.conflict} conflict, ${report.counts.blocked} blocked`
        : report.disposition === 'blocked'
          ? `BLOCKED · ${report.counts.blocked} open qualification item(s) · 0 conflicts`
          : 'PASS · Reviewed fixture complete · No motion authority';
    el('drc-assembly-digest').textContent = report.assemblyDigest;
    el('drc-plan-digest').textContent = report.electricalPlanDigest;
    el('drc-epoch').textContent = `Epoch ${authorityEpoch} · rev ${revisionDigest.slice(0, 12)}… · authority: none`;

    const mp = report.massProperties;
    el('drc-mass').textContent = `${mp.totalMassKg.toFixed(3)} kg`;
    el('drc-com').textContent = `[${mp.centerOfMassWorldM.map(v => (v * 1000).toFixed(2)).join(', ')}] mm`;
    const I = mp.inertiaWorldAtComKgM2;
    el('drc-inertia').textContent = `diag [${I.ixx.toExponential(3)}, ${I.iyy.toExponential(3)}, ${I.izz.toExponential(3)}] · off [${I.ixy.toExponential(2)}, ${I.ixz.toExponential(2)}, ${I.iyz.toExponential(2)}] kg·m²`;

    const bom = report.bom;
    el('drc-bom-summary').textContent = `$${bom.knownSubtotalUsd.toFixed(2)} known subtotal · ${bom.pricedPartCount} priced / ${bom.unpricedPartCount} unpriced instances (${bom.uniquePartCount} part families)`;
    el('drc-bom-list').replaceChildren(
      ...bom.lines.map(line => {
        const row = document.createElement('div');
        row.className = 'drc-row';
        row.dataset.partId = line.partId;
        const priceText =
          line.lineTotalUsd !== null && line.unitCostUsd !== null
            ? `$${line.unitCostUsd.toFixed(2)} × ${line.quantity} = $${line.lineTotalUsd.toFixed(2)} (${line.costBasis})`
            : `unpriced × ${line.quantity} (${line.costBasis}; excluded from subtotal)`;
        row.textContent = `${line.partId} @ ${line.version} · ${priceText}`;
        return row;
      }),
    );

    el('drc-routing-list').replaceChildren(
      ...report.routingProposals.map(prop => {
        const row = document.createElement('div');
        row.className = 'drc-row';
        const endpoints = prop.peripheralEndpoints
          .map(
            ep =>
              `${ep.nodeId}:${ep.interfaceId}${ep.assignedDeviceId !== null ? ` (ID ${ep.assignedDeviceId})` : ''}${ep.i2cAddress !== null ? ` (0x${ep.i2cAddress.toString(16)})` : ''}`,
          )
          .join(', ');
        row.textContent = `${prop.netId ?? prop.proposalId} · ${prop.kind} · ${prop.controllerNodeId}:${prop.controllerInterfaceId} → ${endpoints} · ${prop.status}`;
        return row;
      }),
    );

    el('drc-finding-count').textContent = String(report.findings.length);
    el('drc-findings').replaceChildren(...report.findings.map(f => renderFindingItem(f, state)));
    setStatus(
      `DRC worker checked ${state.current?.assembly.nodes.length ?? 0} parts · ${report.counts.conflict} conflict, ${report.counts.blocked} blocked · offline only.`,
      report.disposition === 'conflict',
      'ready',
    );
  };

  const runDrc = async () => {
    const state = store.getState();
    const current = state.current;
    if (!current || !catalog || state.loading || catalog.catalogDigest !== current.scene.catalogDigest) {
      return;
    }
    button('drc-recheck').disabled = true;
    setStatus('Running pure DRC worker on current revision…', false, 'loading');
    const outcome = await coordinator.evaluate({
      revisionDigest: current.revisionDigest,
      authorityEpoch: state.authorityEpoch,
      assembly: structuredClone(current.assembly) as import('@seedcore/contracts').RobotAssembly,
      catalog,
    });
    if (disposed) return;
    button('drc-recheck').disabled = !store.getState().current;
    if (outcome.status === 'committed') {
      renderReport(outcome.report, outcome.revisionDigest, outcome.authorityEpoch);
    } else if (outcome.status === 'rejected') {
      setStatus(`DRC worker rejected candidate: ${outcome.error}`, true, 'error');
    }
  };

  const loadCatalog = async (digest: string) => {
    attemptedCatalogDigest = digest;
    const gen = ++catalogGen;
    catalogController?.abort();
    catalogController = new AbortController();
    const active = catalogController;
    const timer = setTimeout(() => active.abort(), 10000);
    setStatus('Loading pinned DRC catalog…', false, 'loading');
    button('drc-retry').hidden = true;
    try {
      const loaded = await fetchDrcCatalog(digest, active.signal);
      if (
        disposed ||
        gen !== catalogGen ||
        store.getState().current?.scene.catalogDigest !== digest
      ) {
        return;
      }
      catalog = loaded;
      evaluatedKey = '';
      await runDrc();
    } catch (error) {
      if (!disposed && gen === catalogGen) {
        setStatus(
          `DRC catalog unavailable. ${error instanceof Error ? error.message : 'Load failed'}`,
          true,
          'error',
        );
        button('drc-retry').hidden = false;
      }
    } finally {
      clearTimeout(timer);
    }
  };

  const unsubscribe = store.subscribe(state => {
    const current = state.current;
    button('drc-recheck').disabled = !current || state.loading;
    if (!current) {
      coordinator.cancel();
      evaluatedKey = '';
      setStatus('Load a build to evaluate DRC, mass properties, and BOM.', false, 'idle');
      return;
    }
    if (state.loading) {
      coordinator.cancel();
      return;
    }
    const digest = current.scene.catalogDigest;
    if (catalog?.catalogDigest !== digest) {
      if (attemptedCatalogDigest !== digest) void loadCatalog(digest);
      return;
    }
    const key = `${current.revisionDigest}:${state.authorityEpoch}`;
    if (key !== evaluatedKey) {
      evaluatedKey = key;
      void runDrc();
    } else {
      const latest = coordinator.getLatest();
      if (
        latest &&
        latest.revisionDigest === current.revisionDigest &&
        latest.authorityEpoch === state.authorityEpoch
      ) {
        el('drc-findings').replaceChildren(
          ...latest.report.findings.map(f => renderFindingItem(f, state)),
        );
      }
    }
  });

  button('drc-recheck').onclick = () => {
    void runDrc();
  };
  button('drc-retry').onclick = () => {
    const digest = store.getState().current?.scene.catalogDigest;
    if (digest) void loadCatalog(digest);
  };

  return () => {
    disposed = true;
    ++catalogGen;
    catalogController?.abort();
    coordinator.dispose();
    unsubscribe();
  };
}
