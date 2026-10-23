// CW-SIM-02 / CW-SIM-03 / CW-SIM-04 source build, negative matrix, and native/Wasm MuJoCo 3.15.0 parity.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');

const root = path.resolve(__dirname, '../..');
const out = path.join(root, 'artifacts/robotics/cw-s02');
const python =
  process.env.SEEDCORE_TEST_PYTHON ||
  (fs.existsSync(path.join(root, '.venv/bin/python')) ? path.join(root, '.venv/bin/python') : 'python3');
const skipNative = process.argv.includes('--skip-native');

const report = {
  scope: 'offline_simulation_only',
  physical_acceptance: false,
  execution_authority: 'none',
  review_ids: ['CW-SIM-02', 'CW-SIM-03', 'CW-SIM-04'],
  profile: 'seedcore.cw-s02.mujoco-wasm-st.v1',
  engine: '@mujoco/mujoco@3.15.0',
  wasm_bytes: 10370402,
  wasm_sha256: 'd59c489dd521c80af6965756c5b90daff549fa281566544e4540c170d937633d',
  planar_fallback_used: false,
  native_included: !skipNative,
  browser_included: false, // Actual CSP-patched Chrome checks run via verify-authoring.cjs --browser.
  checks: [],
};

function run(label, command, args, env = {}) {
  const r = spawnSync(command, args, {
    cwd: root,
    encoding: 'utf8',
    env: { ...process.env, ...env },
    maxBuffer: 16 * 1024 * 1024,
  });
  process.stdout.write(r.stdout || '');
  process.stderr.write(r.stderr || '');
  const count = r.stdout?.match(/(?:# tests|ℹ tests) (\d+)/) || r.stdout?.match(/(\d+) passed/);
  report.checks.push({ label, exit_code: r.status, tests: count ? Number(count[1]) : null });
  if (r.status !== 0) throw new Error(`${label} failed: ${r.error?.message || r.status}`);
}

try {
  fs.mkdirSync(out, { recursive: true });
  run('generated assembly/component validators', process.execPath, [
    'tools/robotics/generate-assembly-schema.cjs',
    '--check',
  ]);
  for (const workspace of ['contracts', 'drc-solver', 'wasm-sim-bridge', 'robot-canvas', 'mini-studio']) {
    fs.rmSync(path.join(root, `ts/${workspace === 'mini-studio' ? 'apps' : 'packages'}/${workspace}/dist`), {
      recursive: true,
      force: true,
    });
    run(`${workspace} source build`, 'npm', ['--prefix', 'ts', 'run', '--workspace', `@seedcore/${workspace}`, 'build']);
  }
  run(
    'CW-S02 Wasm verification, clocks, capture and per-substep veto matrix',
    path.join(root, 'ts/node_modules/.bin/tsx'),
    ['--test', 'ts/tests/mujoco-cw-s02.test.ts'],
  );
  run('export CW-S02 Wasm FK and 120-substep rollouts', path.join(root, 'ts/node_modules/.bin/tsx'), [
    'tools/robotics/export-cw-s02.ts',
    path.join(out, 'models'),
  ]);
  if (!skipNative) {
    run(
      'native Python MuJoCo 3.15.0 vs Wasm inspection, FK and rollout parity',
      python,
      ['-m', 'pytest', 'tests/test_cw_s02_parity.py', '-q', '--tb=short'],
      {
        SEEDCORE_CW_S02_REQUIRE_NATIVE: '1',
        SEEDCORE_CW_S02_CASES_DIR: path.join(out, 'models'),
      },
    );
  }
  const cases = JSON.parse(fs.readFileSync(path.join(out, 'models/cases.json'), 'utf8'));
  report.starter = {
    drc_disposition: cases.starter.drc.disposition,
    simulation_ready: cases.starter.readiness.ready,
    blocked_findings: cases.starter.readiness.blockingFindings.length,
  };
  report.models = cases.models.map(c => ({
    name: c.name,
    model_digest: c.model.modelDigest,
    trace_digest: c.rollout.summary.traceDigest,
    executed_substeps: c.rollout.summary.executedSubsteps,
    captured_samples: c.rollout.summary.capturedSamples,
  }));
  report.status = skipNative ? 'wasm_checks_passed_native_not_run' : 'checks_passed';
} catch (error) {
  report.status = 'checks_failed';
  report.failure = error.message;
  process.exitCode = 1;
} finally {
  fs.mkdirSync(out, { recursive: true });
  report.source_revision = spawnSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).stdout.trim();
  report.working_tree_dirty = Boolean(
    spawnSync('git', ['status', '--porcelain'], { cwd: root, encoding: 'utf8' }).stdout.trim(),
  );
  const tracked = spawnSync('git', ['ls-files', '--cached', '--others', '--exclude-standard'], {
    cwd: root,
    encoding: 'utf8',
  })
    .stdout.trim()
    .split('\n');
  const prefixes = [
    'packages/simulation-fixtures/cw-s01/',
    'ts/apps/mini-studio/src/simulation.ts',
    'ts/apps/mini-studio/src/cw-s02-worker.ts',
    'ts/apps/mini-studio/build.mjs',
    'ts/packages/wasm-sim-bridge/',
    'ts/tests/mujoco-cw-s02.test.ts',
    'tools/robotics/verify-cw-s02.cjs',
    'tools/robotics/export-cw-s02.ts',
    'tests/test_cw_s02_parity.py',
    'src/seedcore/robotics/mini_studio_api.py',
    'ts/package-lock.json',
  ];
  report.inputs = tracked
    .filter(p => prefixes.some(prefix => p.startsWith(prefix)) && fs.existsSync(path.join(root, p)) && fs.statSync(path.join(root, p)).isFile())
    .map(p => ({
      path: p,
      sha256: crypto.createHash('sha256').update(fs.readFileSync(path.join(root, p))).digest('hex'),
    }));
  report.outputs = ['ts/apps/mini-studio/dist/cw-s02-worker.js', 'ts/apps/mini-studio/dist/mujoco.wasm']
    .filter(p => fs.existsSync(path.join(root, p)))
    .map(p => ({
      path: p,
      sha256: crypto.createHash('sha256').update(fs.readFileSync(path.join(root, p))).digest('hex'),
    }));
  fs.writeFileSync(path.join(out, 'verification.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(`CW-SIM-02..04: ${report.status}; artifacts/robotics/cw-s02/verification.json`);
}
