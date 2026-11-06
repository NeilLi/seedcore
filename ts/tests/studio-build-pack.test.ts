import test from 'node:test';
import assert from 'node:assert/strict';
import { assertBuildPackCurrent } from '../apps/mini-studio/src/build-pack.js';

const binding = { revisionDigest: 'a'.repeat(64), assemblyDigest: 'b'.repeat(64),
  catalogDigest: 'c'.repeat(64), authorityEpoch: 3 };

test('draft pack binding requires an accepted nonloading current build', () => {
  assert.doesNotThrow(() => assertBuildPackCurrent(binding, { ...binding }));
  assert.throws(() => assertBuildPackCurrent(binding, null));
});
for (const key of ['revisionDigest', 'assemblyDigest', 'catalogDigest', 'authorityEpoch'] as const) {
  test(`draft pack refuses stale ${key}, including same-content undo epoch`, () => {
    const current = { ...binding, [key]: key === 'authorityEpoch' ? 4 : 'd'.repeat(64) };
    assert.throws(() => assertBuildPackCurrent(binding, current));
  });
}
