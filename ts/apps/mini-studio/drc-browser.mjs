import assert from 'node:assert/strict';
import path from 'node:path';

export async function exerciseDrc(page, output, passed) {
  const digest = () => page.locator('#content-digest').textContent();
  await page.locator('#drc-tab').focus();
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('#drc-panel').isVisible(), true);
  await page.waitForFunction(
    () => document.querySelector('#drc-status')?.getAttribute('data-state') === 'ready',
  );

  const currentDigest = await digest();
  assert.equal(await page.locator('#drc-assembly-digest').textContent(), currentDigest);
  assert.match((await page.locator('#drc-plan-digest').textContent()) ?? '', /^[a-f0-9]{64}$/);
  assert.equal(await page.locator('#drc-disposition').getAttribute('data-disposition'), 'blocked');
  assert.match((await page.locator('#drc-bom-summary').textContent()) ?? '', /\$0\.00 known subtotal/);
  assert.match((await page.locator('#drc-bom-summary').textContent()) ?? '', /7 unpriced instances/);
  assert.match((await page.locator('#drc-mass').textContent()) ?? '', /0\.260 kg/);
  passed('CW-DRC-01..03 worker report binds assembly/plan digests, 3D mass/COM/inertia, and unknown-aware BOM');

  const findingCount = await page.locator('#drc-findings button').count();
  assert.ok(findingCount >= 5);
  const firstFinding = page.locator('#drc-findings button').first();
  await firstFinding.focus();
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('#nodes button[aria-pressed=true]').count(), 1);
  assert.equal(await digest(), currentDigest);
  passed('CW-DRC-01..03 field-linked findings select referenced graph nodes without mutating the draft');

  // Verify starter (5 parts, 0.220 kg) vs edited (7 parts, 0.260 kg) DRC updates on load & undo
  await page.locator('#starter').click();
  await page.waitForFunction(
    () =>
      document.querySelector('#content-digest')?.textContent ===
        '2550d184c44a064c6ad6a2245a08f430f257c40ca8f3627e73eeb3fedd452acb' &&
      document.querySelector('#drc-assembly-digest')?.textContent ===
        '2550d184c44a064c6ad6a2245a08f430f257c40ca8f3627e73eeb3fedd452acb',
  );
  assert.match((await page.locator('#drc-mass').textContent()) ?? '', /0\.220 kg/);
  assert.match((await page.locator('#drc-bom-summary').textContent()) ?? '', /5 unpriced instances/);
  await page.locator('#undo').click();
  await page.waitForFunction(
    expected => document.querySelector('#drc-assembly-digest')?.textContent === expected,
    currentDigest,
  );
  assert.match((await page.locator('#drc-mass').textContent()) ?? '', /0\.260 kg/);
  passed('CW-A04 DRC worker recomputes deterministically across starter load and undo');

  await page.screenshot({ path: path.join(output, 'drc-panel.png'), fullPage: true });
}
