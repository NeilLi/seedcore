import assert from 'node:assert/strict';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import path from 'node:path';

export async function exerciseSimulation(page, output, passed, root) {
  const studio = path.join(root, 'artifacts/robotics/cw-s01/studio');
  const models = path.join(root, 'artifacts/robotics/cw-s01/models');
  await mkdir(studio, {recursive:true});
  const waitCompiled = () => page.waitForFunction(() => document.querySelector('#sim-status')?.dataset.state === 'compiled');
  const digest = () => page.locator('#sim-model-digest').textContent();
  const exportFile = async (id, name) => {
    const event = page.waitForEvent('download');
    await page.locator(id).click();
    const download = await event;
    assert.equal(download.suggestedFilename(), name.endsWith('.xml') ? 'assembly.mjcf.xml' : 'assembly.cw-s01.model.json');
    await download.saveAs(path.join(studio, name));
    return readFile(path.join(studio, name), 'utf8');
  };
  await page.locator('#starter').click();
  await page.locator('#simulation-tab').click();
  await page.waitForFunction(() => document.querySelectorAll('#sim-blocking li').length === 9);
  assert.equal(await page.locator('#sim-readiness').textContent(), 'BLOCKED');
  assert.equal(await page.locator('#drc-finding-count').textContent(), '10');
  assert.equal(await page.locator('#sim-deferred li').getAttribute('data-code'), 'MECHANICAL_PROXY_UNQUALIFIED');
  assert.deepEqual(await page.locator('#sim-blocking li').evaluateAll(rows => rows.map(r => r.dataset.code)), [
    'GPIO_PINS_UNASSIGNED','GPIO_PINS_UNASSIGNED','UART_PROTOCOL_UNKNOWN','UART_LOGIC_VOLTAGE_UNKNOWN',
    'POWER_UNKNOWN_RATING','POWER_RAIL_UNCONNECTED','POWER_UNKNOWN_RATING','POWER_RAIL_UNCONNECTED','BOM_UNPRICED_PARTS',
  ]);
  assert.equal(await page.locator('#sim-download-bundle').isDisabled(), true);
  assert.equal(await digest(), '—');
  passed('CW-S01 physical starter retains 10 DRC blockers and exact 9 simulation-blocking reasons');

  await page.locator('#simulation-reference').click();
  await waitCompiled();
  assert.equal(await page.locator('#sim-readiness').textContent(), 'READY (Offline Simulation Only)');
  assert.match(await page.locator('#sim-provenance').textContent(), /synthetic_fixture.*physicalAcceptance: false/);
  assert.equal(await page.locator('#sim-blocking li').count(), 0);
  assert.equal(await page.locator('#drc-finding-count').textContent(), '1');
  const original = await digest();
  const binding = JSON.parse(await page.locator('#sim-binding').textContent());
  assert.equal(binding.assemblyDigest, await page.locator('#content-digest').textContent());
  assert.match(binding.revisionDigest, /^[a-f0-9]{64}$/);
  assert.match(binding.catalogDigest, /^[a-f0-9]{64}$/);
  assert.match(binding.drcDigest, /^[a-f0-9]{64}$/);
  const manifest = JSON.parse(await page.locator('#sim-manifest').textContent());
  assert.equal(manifest.bodies.length, 4); assert.equal(manifest.joints.length, 2);
  assert.equal(manifest.joints[0].maxVelocityRadS, 1);
  assert.equal(manifest.joints[0].restAngleRad, 0);
  assert.ok(manifest.limitations.includes('Velocity limits are metadata, not enforced by MJCF.'));
  passed('CW-S01 explicit synthetic reference compiles with full DRC still blocked; manifest exposes scope and mapping');

  for (const mode of ['position','torque']) {
    await page.locator('#sim-mode').selectOption(mode); await waitCompiled();
    const name = `studio-reference-${mode}`;
    const bundle = await exportFile('#sim-download-bundle', `${name}.cw-s01.model.json`);
    const xml = await exportFile('#sim-download-xml', `${name}.xml`);
    assert.equal(bundle, await readFile(path.join(models, `${name}.cw-s01.model.json`), 'utf8'));
    assert.equal(xml, await readFile(path.join(models, `${name}.xml`), 'utf8'));
    assert.equal(xml, JSON.parse(bundle).xml);
    assert.equal(await page.locator('#sim-kp').isDisabled(), mode === 'torque');
    await page.context().grantPermissions(['clipboard-read','clipboard-write']);
    await page.locator('#sim-copy-bundle').click();
    await page.waitForFunction(() => document.querySelector('#sim-status')?.textContent === 'Copied current offline simulation artifact.');
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), bundle);
    await page.locator('#sim-copy-xml').click();
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), xml);
  }
  passed('CW-S01 position/torque XML and canonical bundles match fresh compiler bytes; copy/download preserve bytes');

  await page.locator('#sim-mode').selectOption('position'); await waitCompiled();
  assert.equal(await digest(), original);
  await page.locator('#sim-dt').fill('0.004'); await waitCompiled();
  assert.notEqual(await digest(), original);
  assert.match(await page.locator('#sim-xml').inputValue(), /timestep="0.004"/);
  await page.locator('#sim-dt').fill('0.02');
  await page.waitForFunction(() => document.querySelector('#sim-status')?.dataset.state === 'blocked');
  assert.equal(await digest(), '—'); assert.equal(await page.locator('#sim-copy-bundle').isDisabled(), true);
  await page.locator('#sim-dt').fill('0.002'); await waitCompiled();
  await page.locator('#sim-kp').fill('20'); await waitCompiled(); assert.notEqual(await digest(), original);
  await page.locator('#sim-kp').fill('10'); await waitCompiled(); assert.equal(await digest(), original);
  passed('CW-S01 timing/gain edits recompile deterministically; invalid settings clear artifacts and disable exports');

  const profile = await (await page.request.get(new URL('/api/simulation-reference', page.url()).href)).json();
  const changed = structuredClone(profile.assembly);
  changed.mechanical_tree.find(e => e.connection_type === 'articulated_joint').joint.rest_angle_rad = 0.1;
  // Hold validation to prove stale exports disappear before a pending edit commits.
  let release, heldResolve;
  const held = new Promise(resolve => {heldResolve = resolve;});
  const gate = new Promise(resolve => {release = resolve;});
  await page.route('**/api/assembly/validate', async route => {heldResolve(); await gate; await route.continue();});
  await page.locator('.raw summary').click(); await page.locator('#raw').fill(JSON.stringify(changed));
  await page.locator('#import-text').click(); await held;
  assert.equal(await digest(), '—'); assert.equal(await page.locator('#sim-download-xml').isDisabled(), true);
  release(); await waitCompiled(); await page.unroute('**/api/assembly/validate');
  const edited = await digest(); assert.notEqual(edited, original);
  assert.equal(JSON.parse(await page.locator('#sim-manifest').textContent()).joints[0].restAngleRad, 0.1);
  await page.locator('#undo').click(); await waitCompiled(); assert.equal(await digest(), original);
  assert.ok(JSON.parse(await page.locator('#sim-binding').textContent()).authorityEpoch > binding.authorityEpoch);
  await page.locator('#redo').click(); await waitCompiled(); assert.equal(await digest(), edited);
  await page.locator('.raw summary').click();
  passed('CW-S01 graph joint edit clears pending artifacts and recompiles; undo/redo restore content under fresh epochs');

  // A stale reference-catalog response cannot resurrect a model after switching to the physical starter.
  await page.locator('#starter').click();
  await page.waitForFunction(() => document.querySelectorAll('#sim-blocking li').length === 9);
  let catalogRelease, catalogHeldResolve;
  const catalogHeld = new Promise(resolve => {catalogHeldResolve = resolve;});
  const catalogGate = new Promise(resolve => {catalogRelease = resolve;});
  await page.route(`**/api/placement-catalog?digest=${profile.catalog.catalogSha256}`, async route => {
    catalogHeldResolve(); await catalogGate; try {await route.continue();} catch {}
  });
  await page.locator('#simulation-reference').click(); await catalogHeld;
  assert.equal(await digest(), '—');
  await page.locator('#starter').click();
  await page.waitForFunction(() => document.querySelectorAll('#sim-blocking li').length === 9);
  catalogRelease(); await page.unroute(`**/api/placement-catalog?digest=${profile.catalog.catalogSha256}`);
  await page.waitForTimeout(100);
  assert.equal(await digest(), '—'); assert.equal(await page.locator('#sim-download-bundle').isDisabled(), true);
  await page.locator('#simulation-reference').click(); await waitCompiled();
  await page.reload(); await page.locator('#simulation-tab').click(); await waitCompiled();
  assert.equal(await digest(), original);
  await page.waitForFunction(() => !document.querySelector('#placement-fields')?.disabled);
  assert.equal(await page.locator('#part-choice option').count(), 3);
  assert.match(await page.locator('#part-choice').inputValue(), /^synthetic\.cw-s01\./);
  passed('CW-S01 stale catalog loads cannot restore exports; synthetic draft reload retains provenance and deterministic identity');
  await page.screenshot({path:path.join(studio,'simulation-inspector.png'),fullPage:true});
  await writeFile(path.join(studio, 'browser-handoff.json'), JSON.stringify({scope:'offline_simulation_only', physicalAcceptance:false, modelDigest:original, binding},null,2)+'\n');
}
