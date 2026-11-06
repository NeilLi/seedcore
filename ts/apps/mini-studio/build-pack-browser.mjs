// Actual browser downloads; independent Python ZIP/CRC/hash/CSV/XML inspection.
import { chromium } from 'playwright';
import { spawn, spawnSync } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

const root = fileURLToPath(new URL('../../../', import.meta.url));
const output = path.join(root, 'artifacts/robotics/cw-e01/studio');
await mkdir(output, { recursive: true });
const port = process.env.SEEDCORE_PACK_TEST_PORT || '8781', base = `http://127.0.0.1:${port}`;
const python = process.env.SEEDCORE_TEST_PYTHON || path.join(root, '.venv/bin/python');
const server = spawn(python, ['scripts/robotics/serve_mini_studio.py', '--port', port],
  { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
let serverLog = '', browser;
server.stdout.on('data', bytes => { serverLog += bytes; });
server.stderr.on('data', bytes => { serverLog += bytes; });
const report = { scope: 'offline_design_only', physicalAcceptance: false, executionAuthority: 'none',
  checks: [], downloads: [], errors: [] };
const passed = name => { report.checks.push(name); console.log(`PASS ${name}`); };
const independentScript = String.raw`
import csv, hashlib, io, json, pathlib, sys, xml.etree.ElementTree as ET, zipfile
p = pathlib.Path(sys.argv[1])
with zipfile.ZipFile(p) as archive:
    infos = archive.infolist(); names = archive.namelist()
    assert len(names) == len(set(names)) and len(names) <= 288
    assert all(not n.startswith(('/', '\\')) and '\\' not in n and '..' not in pathlib.PurePosixPath(n).parts for n in names)
    assert all(i.compress_type == zipfile.ZIP_STORED and i.file_size == i.compress_size for i in infos)
    assert sum(i.file_size for i in infos) <= 8*1024*1024
    assert archive.testzip() is None
    manifest = json.loads(archive.read('manifest.json'))
    assert manifest['schemaVersion'] == 'seedcore.cw-e01.build-pack.v1'
    assert manifest['status'] == 'draft' and manifest['scope'] == 'offline_design_only'
    assert manifest['physicalAcceptance'] is False and manifest['executionAuthority'] == 'none'
    assert manifest['omittedAssets'] == {'visualMeshes': True, 'printableCad': True, 'firmware': True}
    assert set(names) == {f['path'] for f in manifest['files']} | {'manifest.json'}
    for item in manifest['files']:
        content = archive.read(item['path'])
        assert len(content) == item['bytes'] and hashlib.sha256(content).hexdigest() == item['sha256']
    bom = list(csv.DictReader(io.StringIO(archive.read('bom.csv').decode())))
    assert bom and all(not v.lstrip().startswith(('=', '+', '-', '@')) for row in bom for v in row.values() if v)
    ET.fromstring(archive.read('wiring.svg'))
    assert b'UNREVIEWED' in archive.read('wiring.svg') or manifest['wiring']['explicitNetCount'] == 0
    assert manifest['wiring']['unresolvedNetCount'] == manifest['wiring']['explicitNetCount']
    assert manifest['model']['included'] == ('model.mjcf.xml' in names)
    if manifest['model']['included']: ET.fromstring(archive.read('model.mjcf.xml'))
    assert not any(n.endswith(('.glb', '.stl', '.step', '.bin')) for n in names)
print(json.dumps({'status': 'checks_passed', 'manifest': manifest, 'entries': len(names), 'zipSha256': hashlib.sha256(p.read_bytes()).hexdigest()}))
`;
try {
  for (let i = 0; i < 100; i++) {
    if (server.exitCode !== null) throw new Error(`Service exited: ${serverLog}`);
    try { if (serverLog.includes('Uvicorn running on') && (await fetch(`${base}/api/starter`)).ok) break; } catch {}
    if (i === 99) throw new Error(`Service unavailable: ${serverLog}`);
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  const channel = process.env.SEEDCORE_BROWSER_CHANNEL || 'chrome';
  browser = await chromium.launch({ headless: true, ...(channel === 'bundled' ? {} : { channel }) });
  report.browser = browser.version();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  const page = await context.newPage();
  page.on('pageerror', error => report.errors.push(error.message));
  const mutations = [], requests = [];
  page.on('request', request => {
    requests.push(`${request.method()} ${request.url()}`);
    // Fixture load/edit validation is expected; export itself is checked against
    // an exact request-count snapshot in download().
    if (request.method() !== 'GET' && new URL(request.url()).pathname !== '/api/assembly/validate') mutations.push(request.url());
  });
  await page.goto(base);
  const waitPack = () => page.waitForFunction(() => document.querySelector('#build-pack-status')?.dataset.state === 'ready');
  await waitPack();
  await page.locator('#drc-tab').click();
  assert.match(await page.locator('#build-pack-status').textContent(), /5 unpriced/);
  const download = async name => {
    const before = await page.locator('#content-digest').textContent();
    const stored = await page.evaluate(() => localStorage.getItem('seedcore.mini-studio.draft.v2'));
    const count = requests.length;
    const event = page.waitForEvent('download'); await page.locator('#build-pack-download').click();
    const file = await event;
    assert.match(file.suggestedFilename(), /^draft-build-[a-f0-9]{12}\.zip$/);
    const target = path.join(output, name); await file.saveAs(target);
    assert.equal(await page.locator('#content-digest').textContent(), before);
    assert.equal(await page.evaluate(() => localStorage.getItem('seedcore.mini-studio.draft.v2')), stored);
    assert.equal(requests.length, count, 'export must not request admission, verification or network data');
    const result = spawnSync(python, ['-c', independentScript, target], { cwd: root, encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr || result.stdout);
    const inspected = JSON.parse(result.stdout);
    const ui = JSON.parse(await page.locator('#build-pack-details').textContent());
    assert.deepEqual(ui, inspected.manifest);
    report.downloads.push({ file: name, ...inspected });
    await writeFile(path.join(output, `${name}.verification.json`), JSON.stringify(inspected, null, 2) + '\n');
    return { bytes: await readFile(target), manifest: inspected.manifest };
  };
  const starter = await download('starter.zip');
  assert.equal(starter.manifest.model.included, false);
  assert.equal(starter.manifest.bom.unpricedPartCount, 5);
  assert.match(starter.manifest.model.reason, /DRC_NOT_READY/);
  passed('blocked physical starter exports original draft records with five unknown costs and explicit model omission');
  const repeat = await download('starter-repeat.zip');
  assert.deepEqual(starter.bytes, repeat.bytes);
  passed('actual browser repeated export is byte-identical and independent ZIP/CRC/hash/CSV/XML checks pass');

  await page.locator('#simulation-tab').click(); await page.locator('#simulation-reference').click(); await waitPack();
  await page.locator('#drc-tab').click();
  const reference = await download('synthetic-reference.zip');
  assert.equal(reference.manifest.model.included, true);
  assert.equal(reference.manifest.bom.unpricedPartCount, 0);
  passed('synthetic reference exports source-bound offline model using declared position gain 1 / timestep 0.002');

  await page.locator('#simulation-tab').click(); await page.locator('#sim-kp').fill('2');
  assert.equal(await page.locator('#build-pack-download').isDisabled(), true);
  await page.locator('#drc-tab').click(); await page.locator('#drc-recheck').click(); await waitPack();
  const settings = await download('synthetic-after-settings.zip');
  assert.deepEqual(reference.bytes, settings.bytes, 'fixed export preset stays independent of editor compiler controls');
  passed('compiler settings clear retained export until fresh DRC; explicit export preset remains deterministic');

  // Deliver an editor settings event in the same task after DRC dispatch and
  // before its asynchronous coordinator result. The old response must not
  // re-enable export even though assembly/revision/authority epoch are equal.
  await page.evaluate(() => {
    document.querySelector('#drc-recheck').click();
    const gain = document.querySelector('#sim-kp'); gain.value = '3';
    gain.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await page.waitForFunction(() => document.querySelector('#drc-status')?.dataset.state === 'ready');
  assert.equal(await page.locator('#build-pack-download').isDisabled(), true);
  assert.equal(await page.locator('#build-pack-status').getAttribute('data-state'), 'unavailable');
  await page.locator('#drc-recheck').click(); await waitPack();
  passed('settings changed during pending asynchronous DRC fence its delayed result until a newer explicit recheck');

  await page.locator('#inspect-tab').click(); await page.locator('#name').fill('Pack revision checked');
  await page.locator('#rename').click(); await waitPack(); await page.locator('#drc-tab').click();
  const edited = await download('edited-reference.zip');
  assert.notEqual(edited.manifest.bindings.assemblyDigest, reference.manifest.bindings.assemblyDigest);
  await page.locator('#undo').click(); await waitPack();
  const undo = await download('undo-reference.zip');
  assert.deepEqual(undo.bytes, reference.bytes);
  passed('edit and undo recompute current DRC and never reuse stale draft bindings');

  let release, notify; const held = new Promise(resolve => { notify = resolve; });
  const gate = new Promise(resolve => { release = resolve; });
  await page.route('**/api/starter', async route => { notify(); await gate; await route.continue(); });
  await page.locator('#starter').click(); await held;
  assert.equal(await page.locator('#build-pack-download').isDisabled(), true);
  assert.equal(await page.locator('#build-pack-details').textContent(), '');
  release(); await waitPack(); await page.unroute('**/api/starter');
  assert.equal(await page.locator('#content-digest').textContent(), starter.manifest.bindings.assemblyDigest);
  passed('pending asynchronous build load immediately clears the old manifest and export control');

  await page.locator('#build-pack').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(output, 'desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('#build-pack').scrollIntoViewIfNeeded();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: path.join(output, 'mobile.png') });
  await page.locator('#build-pack-download').focus();
  const keyboard = page.waitForEvent('download'); await page.keyboard.press('Enter');
  await (await keyboard).saveAs(path.join(output, 'keyboard-starter.zip'));
  passed('keyboard download and desktop/mobile containment work under strict CSP');
  assert.deepEqual(mutations, []); assert.deepEqual(report.errors, []);
  passed('all draft exports preserve authoring state and issue no mutation/control/verification requests');
  report.status = 'checks_passed';
} catch (error) {
  report.status = 'checks_failed'; report.failure = String(error.stack || error); process.exitCode = 1;
  console.error(report.failure);
} finally {
  await browser?.close(); server.kill('SIGTERM');
  report.sourceRevision = spawnSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).stdout.trim();
  report.inputs = [];
  for (const name of ['ts/apps/mini-studio/src/build-pack.ts', 'ts/apps/mini-studio/src/drc.ts',
    'ts/apps/mini-studio/src/index.html', 'ts/apps/mini-studio/build-pack-browser.mjs']) {
    report.inputs.push({ path: name, sha256: createHash('sha256').update(await readFile(path.join(root, name))).digest('hex') });
  }
  await writeFile(path.join(output, 'browser-verification.json'), JSON.stringify(report, null, 2) + '\n');
  await writeFile(path.join(output, 'server.log'), serverLog);
}
